from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from .planner import BASE, STATIONS, WALLS, WIDTH, HEIGHT, solve, graph, astar, PlanningError

BURN = 0.18
TICK_SECONDS = 0.6


class Engine:
    def __init__(self):
        self.lock = RLock()
        self.reset()

    def reset(self):
        self.position = BASE
        self.battery = 100.0
        self.deliveries = []
        self.blocked = set()
        self.precedence = []
        self.path = [BASE]
        self.stops = []
        self.cursor = 0
        self.status = 'idle'
        self.returning = False
        self.distance = 0
        self.trail = [BASE]
        self.replans = 0
        self.plan = None
        self.comparison = None
        self.events = []
        self.event('Mission ready', 'Load the sample mission or add your first delivery.')

    def event(self, title, detail, kind='info'):
        self.events.insert(0, {'id': len(self.events)+1, 'time': datetime.now(timezone.utc).isoformat(),
                              'title': title, 'detail': detail, 'kind': kind})

    def pending(self):
        return [d for d in self.deliveries if d['status'] == 'pending']

    def add(self, station, priority='normal'):
        if station not in STATIONS:
            raise PlanningError('Unknown station.')
        if any(d['station'] == station for d in self.deliveries):
            raise PlanningError(f'Station {station} already has a delivery in this mission. Reset to start a new mission.')
        self.deliveries.append({'station': station, 'priority': priority, 'status': 'pending'})

    def priority(self, station, priority='urgent'):
        found = next((d for d in self.deliveries if d['station'] == station), None)
        if found and found['status'] == 'completed':
            raise PlanningError(f'Station {station} has already been served.')
        if found:
            found['priority'] = priority
        else:
            self.add(station, priority)

    def obstacle(self, cell, blocked):
        cell = tuple(cell)
        if not (0 <= cell[0] < WIDTH and 0 <= cell[1] < HEIGHT):
            raise PlanningError('Cell is outside the warehouse.')
        if cell in WALLS or cell == self.position or cell == BASE or cell in STATIONS.values():
            raise PlanningError('Cannot edit a wall, station, charging dock, or occupied robot cell.')
        if blocked:
            self.blocked.add(cell)
        else:
            self.blocked.discard(cell)

    def transaction(self, update, reason):
        """Rollback invalid commands; valid disconnecting obstacles safely stop the robot."""
        backup = deepcopy({k: v for k, v in vars(self).items() if k != 'lock'})
        try:
            update()
            self.replan(reason)
        except Exception:
            for key, value in backup.items():
                setattr(self, key, value)
            raise

    def replan(self, reason='Route optimized'):
        was_running = self.status == 'running'
        was_paused = self.status == 'paused'
        was_charging = self.status == 'charging'
        old = max(0, len(self.path)-1-self.cursor)
        had_plan = self.plan is not None
        try:
            plan = solve(self.position, self.pending(), self.blocked, self.precedence)
        except PlanningError as exc:
            if 'Unreachable location' not in str(exc):
                raise
            self.path, self.stops, self.cursor = [self.position], [], 0
            self.status = 'blocked'
            self.plan = None
            self.event('Robot stopped safely', 'Charging dock is unreachable. Unblock a corridor to continue.', 'warning')
            return
        self.returning = was_charging or self.battery <= 20 or plan.distance*BURN+5 > self.battery
        if self.returning:
            path = astar(graph(self.blocked), self.position, BASE)
            if (len(path)-1)*BURN > self.battery:
                self.status = 'blocked'
                self.path, self.stops, self.cursor = [self.position], [], 0
                self.plan = None
                self.event('Battery safety stop', 'Insufficient charge to reach dock. Reset the simulated mission.', 'warning')
                return
            plan.path, plan.stops, plan.order = path, [], []
            plan.distance = len(path)-1
            plan.baseline = plan.distance
            reason += ' · Battery reserve: returning to charge; pending tasks retained'
        self.plan = plan
        self.path, self.stops, self.cursor = plan.path, plan.stops, 0
        if had_plan:
            self.replans += 1
            self.comparison = {'before': old, 'after': plan.distance, 'reason': reason}
        self.status = 'charging' if was_charging else 'running' if was_running else 'paused' if was_paused else 'ready'
        self.event(reason, f'{plan.distance} m remaining · '+(' → '.join(plan.order+['Dock'])), 'success')
        if plan.unreachable:
            self.event('Destinations unreachable', f"{', '.join(plan.unreachable)} remain pending, including any urgent tasks. Reachable tasks proceed.", 'warning')

    def start(self):
        if self.status == 'charging':
            raise PlanningError('Charging in progress. The mission resumes automatically at full charge.')
        if not self.pending() and self.position == BASE:
            raise PlanningError('Add deliveries before starting the robot.')
        if self.status != 'paused':
            self.replan('Mission started')
        if self.status == 'blocked':
            raise PlanningError('Unblock a corridor before starting.')
        self.status = 'running'

    def tick(self):
        if self.status == 'charging':
            self.battery = min(100, self.battery+5)
            if self.battery >= 100:
                self.status = 'running'
                self.replan('Battery restored · mission resumed')
            return
        if self.status != 'running':
            return
        self.arrive()
        if self.cursor < len(self.path)-1:
            next_cell = self.path[self.cursor+1]
            if next_cell in self.blocked or next_cell in WALLS or sum(abs(a-b) for a,b in zip(self.position,next_cell)) != 1:
                self.status = 'blocked'
                self.event('Safety stop', 'Remaining path is invalid.', 'warning')
                return
            self.cursor += 1
            self.position = next_cell
            self.trail.append(next_cell)
            self.distance += 1
            self.battery = max(0, self.battery-BURN)
            self.arrive()
        if self.cursor == len(self.path)-1:
            if self.returning and self.position == BASE:
                self.status = 'charging'
                self.event('Charging at dock', 'Outstanding deliveries will resume at full charge.')
            elif self.pending():
                self.status = 'blocked'
                self.event('Waiting for access', 'Unreachable deliveries are pending. Clear obstacles and start again.', 'warning')
            else:
                self.status = 'completed'
                self.event('Mission complete', f'All deliveries served. Robot docked after {self.distance} simulated metres.', 'success')

    def arrive(self):
        for stop in self.stops:
            if stop['index'] == self.cursor:
                for d in self.pending():
                    if d['station'] == stop['station']:
                        d['status'] = 'completed'
                        self.event(f"Delivery {d['station']} completed", 'Payload delivered at the planned stop.', 'success')

    def snapshot(self):
        done = sum(d['status'] == 'completed' for d in self.deliveries)
        remaining = max(0, len(self.path)-1-self.cursor)
        baseline = self.plan.baseline if self.plan else 0
        optimized = self.plan.distance if self.plan else 0
        return {'position': self.position, 'trail': self.trail, 'battery': round(self.battery, 1), 'status': self.status,
                'deliveries': deepcopy(self.deliveries), 'obstacles': sorted(self.blocked),
                'path': self.path[self.cursor:], 'order': [s['station'] for s in self.stops if s['index'] >= self.cursor
                                                         and any(d['station']==s['station'] for d in self.pending())],
                'events': self.events[:60], 'comparison': self.comparison,
                'unreachable': self.plan.unreachable if self.plan else [],
                'analytics': {'completed': done, 'pending': len(self.pending()), 'distance': self.distance,
                              'remaining': remaining, 'eta': round(remaining*TICK_SECONDS, 1),
                              'baseline': baseline, 'optimized': optimized, 'replans': self.replans,
                              'reduction': round((baseline-optimized)/baseline*100, 1) if baseline else 0,
                              'progress': round(done/len(self.deliveries)*100) if self.deliveries else 0}}
