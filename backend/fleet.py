"""Fleet engine: the simulated city, the robots, their sensors, their brains and the dispatcher server.

Who knows what:
- The world (self.hazards) is ground truth. Robots only see it through their sensors.
- The fleet map (self.knowledge) is what the server knows: hazards robots reported, or closures the
  city announced. Every robot plans with it.
- Each robot also keeps private knowledge (robot.avoid) of obstacles it decided to avoid itself.
"""
import random
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import RLock

from . import hazards as hz
from .agent import ACTION_LABELS, TRIGGERS, RobotAgent
from .citymap import CityMap, Unreachable, key
from .dispatcher import Job, Vehicle, dispatch
from .geo import compass, haversine

TICK_SECONDS = 0.25      # wall-clock seconds between simulation steps
SPEED = 1.8              # m/s, a typical sidewalk delivery robot
SLOW = 0.5               # m/s when approaching or passing an obstacle
CAMERA_RANGE = 35.0      # metres ahead the camera and lidar can see along the route
DECIDE_DISTANCE = 12.0   # the robot stops this far from an obstacle and decides
BURN = 0.012             # battery % per metre, about 8 km per charge
RESERVE = 8.0            # % kept for getting home; reaching it triggers the safety reflex
LOW_BATTERY = 25.0       # % that wakes the agent to rethink the plan
CHARGE_RATE = 1.0        # % per simulated second at the hub
CAPACITY = 3             # parcel compartments per robot
DWELL = 6.0              # seconds to load or unload a parcel
RETRY = 30.0             # seconds between quiet re-dispatch attempts for waiting orders
KNOWLEDGE_TTL = {'seconds': 60, 'minutes': 300, 'long': 1200, 'permanent': None, 'unknown': 300}
ROBOTS = [('RM-1', 'Atlas', '#b8ef71', 100), ('RM-2', 'Bolt', '#7cc4fa', 96),
          ('RM-3', 'Comet', '#f5a971', 88), ('RM-4', 'Dash', '#c9a7f7', 74)]
SAMPLE = [(0, 2, 'normal'), (1, 1, 'normal'), (2, 4, 'normal'), (3, 7, 'normal'), (4, 6, 'normal'), (5, 10, 'normal')]


class Robot:
    def __init__(self, rid, name, color, battery, hub):
        self.id, self.name, self.color = rid, name, color
        self.battery = float(battery)
        self.path, self.seg, self.along = [hub], 0, 0.0
        self.stops = []            # [{'order', 'kind', 'node', 'index'}], index = position in path
        self.status = 'idle'       # idle | moving | serving | thinking | waiting | charging | blocked
        self.load = []             # order ids on board
        self.distance = 0.0
        self.returning = False
        self.avoid = {}            # private knowledge: edge -> [metres from key-ordered start]
        self.avoid_until = {}      # edge -> simulated time when the robot stops trusting that note
        self.encounter = None      # the obstacle currently being handled
        self.thinking = None       # token of the decision in flight
        self.wait_until = None
        self.dwell_until = None
        self.battery_alerted = False
        self.sensors = {}
        self.thoughts = deque(maxlen=25)


class Fleet:
    def __init__(self, city=None, llm=None, sync=False, solver_ms=300, seed=None):
        self.city = city or CityMap.load()
        self.llm = llm
        self.agent = RobotAgent(llm)
        self.sync = sync
        self.solver_ms = solver_ms
        self.rng = random.Random(seed)
        self.lock = RLock()
        self.executor = None if sync else ThreadPoolExecutor(max_workers=4, thread_name_prefix='robot-brain')
        self.reset()

    # ------------------------------------------------------------------ setup
    def reset(self):
        self.time = 0.0
        self.clock_start = datetime.now().replace(microsecond=0)
        self.running = False
        self.completed = False
        self.speed = 8
        hub = self.city.hub
        self.robots = [Robot(rid, name, color, battery, hub) for rid, name, color, battery in ROBOTS]
        self.orders, self.hazards, self.by_edge, self.knowledge = {}, {}, {}, {}
        self.events = []
        self.ids = {'order': 0, 'hazard': 0, 'event': 0, 'thought': 0}
        self.counts = {'ai': 0, 'reflex': 0, 'ai_ms': 0, 'reports': 0, 'reroutes': 0, 'dispatches': 0}
        self.plan_metrics = None
        self.retry_at = 0.0
        self.confirmations = {}    # hazard id -> how many times robots reported it
        self.event('Fleet ready', f'{len(self.robots)} robots docked at {self.city.label(hub)} · {self.city.name}.')

    def clock(self):
        return (self.clock_start + timedelta(seconds=self.time)).strftime('%H:%M:%S')

    def event(self, title, detail, kind='info', robot=None):
        self.ids['event'] += 1
        self.events.insert(0, {'id': self.ids['event'], 'time': self.clock(), 'title': title, 'detail': detail,
                               'kind': kind, 'robot': robot})
        del self.events[150:]

    def robot(self, rid):
        found = next((r for r in self.robots if r.id == rid), None)
        if not found:
            raise ValueError(f'Unknown robot {rid}.')
        return found

    def place(self, pid):
        if pid not in self.city.places:
            raise ValueError(f'Unknown place {pid}.')
        return self.city.places[pid]

    # ------------------------------------------------------------------ orders & controls
    def add_order(self, pickup, dropoff, priority='normal'):
        p, d = self.place(pickup), self.place(dropoff)
        if p['role'] != 'pickup' or d['role'] != 'dropoff':
            raise ValueError('Orders go from a pickup place (P…) to a drop-off place (D…).')
        self.ids['order'] += 1
        oid = self.ids['order']
        self.orders[oid] = {'id': oid, 'pickup': pickup, 'dropoff': dropoff, 'priority': priority, 'status': 'queued',
                            'robot': None, 'created': self.clock(), 'delivered_at': None}
        self.completed = False
        return oid

    def load_sample(self):
        if self.orders:
            raise ValueError('Reset the current mission before loading the sample.')
        pickups = [p for p in self.city.places.values() if p['role'] == 'pickup']
        drops = [p for p in self.city.places.values() if p['role'] == 'dropoff']
        for i, j, priority in SAMPLE:
            self.add_order(pickups[i % len(pickups)]['id'], drops[j % len(drops)]['id'], priority)
        self.event('Sample mission loaded', f'{len(SAMPLE)} orders from real places in {self.city.name}.')
        self.dispatch('New mission')

    def set_priority(self, oid, priority):
        order = self.orders.get(oid)
        if not order:
            raise ValueError(f'Unknown order #{oid}.')
        if order['status'] == 'delivered':
            raise ValueError(f'Order #{oid} is already delivered.')
        order['priority'] = priority
        self.event(f'Order #{oid} is now {priority}', f"{self.place(order['pickup'])['name']} → {self.place(order['dropoff'])['name']}", 'warning' if priority == 'urgent' else 'info')
        self.dispatch(f'Order #{oid} priority changed')

    def start(self):
        if not self.orders:
            raise ValueError('Load the sample mission or add an order first.')
        self.running = True
        self.event('Fleet running', f'Simulation at ×{self.speed}.', 'success')
        if any(o['status'] == 'queued' for o in self.orders.values()):
            self.dispatch('Fleet started')

    def pause(self):
        self.running = False
        self.event('Fleet paused', 'Robots hold position; decisions in progress still complete.')

    def set_speed(self, speed):
        self.speed = speed

    def set_battery(self, rid, level):
        r = self.robot(rid)
        r.battery = float(level)
        r.battery_alerted = False
        self.event(f'{r.id} battery set to {level}%', 'Operator-triggered battery event.', 'warning', r.id)

    # ------------------------------------------------------------------ hazards
    def add_hazard(self, lat, lon, kind, announced=False):
        if kind not in hz.KINDS:
            raise ValueError(f'Unknown obstacle type {kind}.')
        a, b, along, lateral = self.city.nearest_edge(lat, lon)
        if lateral > 40:
            raise ValueError('Click closer to a street.')
        pos, _ = self.city.point(a, b, along)
        self.ids['hazard'] += 1
        h = hz.make(self.ids['hazard'], kind, a, b, along, tuple(round(x, 6) for x in pos), self.city.street(a, b),
                    self.time, self.rng)
        h.announced = announced
        self.hazards[h.id] = h
        self.by_edge.setdefault(key(a, b), []).append(h)
        label = hz.KINDS[kind]['label']
        if announced:
            self.knowledge[h.id] = {'hazard': h.id, 'edge': key(a, b), 'along': along, 'pos': h.pos, 'street': h.street,
                                    'kind': kind, 'blocks': not h.passable, 'by': 'City notice', 'since': self.time,
                                    'until': None, 'message': f'{label} announced on {h.street}'}
            self.event(f'City notice: {label}', f'{h.street}. The server knows in advance and re-routes the fleet.', 'warning')
            self.reroute_affected(key(a, b), None, 'city notice')
        else:
            self.event(f'Unannounced obstacle: {label}', f'{h.street}. No robot knows yet; they must see it.', 'warning')
        return h.id

    def clear_hazard(self, hid):
        h = self.hazards.pop(hid, None)
        if not h:
            raise ValueError(f'Unknown obstacle {hid}.')
        self.by_edge[key(h.a, h.b)].remove(h)
        if h.announced:
            self.knowledge.pop(hid, None)
        self.event(f'Obstacle removed: {hz.KINDS[h.kind]["label"]}', f'{h.street}. Robots still trust their reports until they expire.')
        stuck = [r for r in self.robots if r.status == 'blocked']
        for r in stuck:
            r.status = 'moving'
        if stuck:
            self.dispatch('Obstacle removed')

    def remember(self, r, h, duration='unknown'):
        """The robot notes an obstacle privately, for as long as it expects it to last."""
        edge = key(h.a, h.b)
        r.avoid.setdefault(edge, []).append(h.along)
        r.avoid_until[edge] = self.time + (KNOWLEDGE_TTL[duration] or 1800)

    def blockers(self, robot=None):
        out = {}
        for k in self.knowledge.values():
            if k['blocks']:
                out.setdefault(k['edge'], []).append(k['along'])
        if robot:
            for edge, positions in robot.avoid.items():
                out.setdefault(edge, []).extend(positions)
        return out

    # ------------------------------------------------------------------ robot geometry
    def loc(self, r):
        if r.seg >= len(r.path)-1:
            return r.path[-1], None, 0.0
        if r.along < 1e-6:
            return r.path[r.seg], None, 0.0
        return r.path[r.seg], r.path[r.seg+1], r.along

    def pos(self, r):
        a, b, along = self.loc(r)
        if b is None:
            heading = 0.0
            if r.seg < len(r.path)-1:
                heading = self.city.point(a, r.path[r.seg+1], 0)[1]
            return self.city.nodes[a], heading
        return self.city.point(a, b, along)

    def options(self, r, blockers):
        """Ways the robot can leave its current spot: (node, metres to it, path prefix, start offset)."""
        a, b, along = self.loc(r)
        if b is None:
            return [(a, 0.0, [a], 0.0)]
        length = self.city.length(a, b)
        positions = [self.city.to_dir(a, b, x) for x in blockers.get(key(a, b), [])]
        opts = []
        if not any(p > along for p in positions):
            opts.append((b, length-along, [a, b], along))
        if not any(p < along for p in positions):
            opts.append((a, along, [b, a], length-along))   # turn around on the sidewalk
        return opts

    def plan_route(self, r, targets, blockers):
        blocked = frozenset(blockers)
        best = None
        for node, cost, prefix, start_along in self.options(r, blockers):
            try:
                path, length = self.city.route(node, targets[0], blocked)
            except Unreachable:
                continue
            if best is None or cost+length < best[0]:
                best = (cost+length, prefix + path[1:], start_along)
        if best is None:
            raise Unreachable(f'No open street path to {self.city.label(targets[0])}.')
        path, indices = best[1], [len(best[1])-1]
        for target in targets[1:]:
            leg, _ = self.city.route(path[-1], target, blocked)
            path += leg[1:]
            indices.append(len(path)-1)
        return path, best[2], indices

    def assign(self, r, stops):
        targets = [s['node'] for s in stops] + [self.city.hub]
        try:
            path, start_along, indices = self.plan_route(r, targets, self.blockers(r))
        except Unreachable:
            if not r.avoid:
                raise
            # Its private notes make the plan impossible: forget them and trust the shared fleet map.
            r.avoid.clear()
            r.avoid_until.clear()
            path, start_along, indices = self.plan_route(r, targets, self.blockers(r))
        r.path, r.seg, r.along = path, 0, start_along
        r.stops = [{'order': s['order'], 'kind': s['kind'], 'node': s['node'], 'index': indices[i]} for i, s in enumerate(stops)]
        if r.status == 'idle' and len(path) > 1:
            r.status = 'moving'

    def remaining(self, r, upto=None):
        """Metres along the current path from the robot to path index `upto` (default: the end)."""
        upto = len(r.path)-1 if upto is None else upto
        if r.seg >= upto:
            return 0.0
        total = self.city.length(r.path[r.seg], r.path[r.seg+1]) - r.along
        return total + sum(self.city.length(r.path[i], r.path[i+1]) for i in range(r.seg+1, upto))

    def to_hub(self, r):
        best = None
        for node, cost, _, _ in self.options(r, self.blockers(r)):
            try:
                total = cost + self.city.route(node, self.city.hub, frozenset(self.blockers(r)))[1]
            except Unreachable:
                continue
            best = total if best is None else min(best, total)
        return best

    def ahead(self, r, limit):
        """Ground-truth hazards on the route within `limit` metres: what the sensors physically see."""
        found, dist = [], -r.along
        for i in range(r.seg, len(r.path)-1):
            a, b = r.path[i], r.path[i+1]
            for h in self.by_edge.get(key(a, b), []):
                d = dist + self.city.to_dir(a, b, h.along)
                if -0.5 <= d <= limit:
                    found.append((d, h.id, h))
            dist += self.city.length(a, b)
            if dist > limit:
                break
        return [(d, h) for d, _, h in sorted(found)]

    # ------------------------------------------------------------------ sensing
    def sense(self, r):
        (lat, lon), heading = self.pos(r)
        found = self.ahead(r, CAMERA_RANGE)
        camera = lidar = None
        if found:
            d, h = found[0]
            camera = {'distance_m': round(d, 1), 'description': h.view, 'classifier': h.label, 'confidence': h.confidence}
            lidar = {'obstacle_distance_m': round(max(d, 0), 1), 'free_gap_m': h.gap, 'robot_width_m': hz.ROBOT_WIDTH,
                     'moving_objects': hz.KINDS[h.kind]['moving']}
            if r.id not in h.seen_by:
                h.seen_by.append(r.id)
                self.event(f'{r.id} camera: something on {h.street}', f"{round(d)} m ahead · classifier '{h.label}' ({h.confidence:.2f})", 'info', r.id)
        jitter = lambda: self.rng.uniform(-2.5, 2.5) / 111_000
        r.sensors = {'gps': [round(lat + jitter(), 6), round(lon + jitter(), 6)], 'gps_accuracy_m': 3.0,
                     'heading': round(heading), 'camera': camera, 'lidar': lidar, 'battery': round(r.battery, 1)}
        return found[0] if found else None

    # ------------------------------------------------------------------ simulation step
    def tick(self):
        if not self.running:
            return
        dt = TICK_SECONDS * self.speed
        self.time += dt
        self.expire()
        for r in self.robots:
            self.update(r, dt)
        if self.time >= self.retry_at:
            self.retry_at = self.time + RETRY
            stuck = [r for r in self.robots if r.status == 'blocked']
            for r in stuck:
                r.status = 'moving'     # look again: obstacles or reports may have cleared
            if stuck or any(o['status'] == 'queued' for o in self.orders.values()):
                self.dispatch('Retrying waiting orders', quiet=True)
        self.check_complete()

    def expire(self):
        for h in [h for h in self.hazards.values() if h.clears_at is not None and self.time >= h.clears_at]:
            self.hazards.pop(h.id)
            self.by_edge[key(h.a, h.b)].remove(h)
            self.event(f'{hz.KINDS[h.kind]["label"]} cleared by itself', f'{h.street} (ground truth; robots find out by looking).')
        for hid, k in list(self.knowledge.items()):
            if k['until'] is not None and self.time >= k['until']:
                self.knowledge.pop(hid)
                self.event('Fleet report expired', f"{k['street']}: robots will route through it again.")

    def update(self, r, dt):
        for edge, until in list(r.avoid_until.items()):
            if self.time >= until:
                r.avoid.pop(edge, None)
                r.avoid_until.pop(edge)
        if r.status == 'charging':
            r.battery = min(100.0, r.battery + CHARGE_RATE*dt)
            if r.battery >= 100:
                r.status, r.battery_alerted = 'idle', False
                self.event(f'{r.id} fully charged', 'Back in service.', 'success', r.id)
                if r.load or any(o['status'] == 'queued' for o in self.orders.values()):
                    self.dispatch(f'{r.id} back in service')
            return
        if r.status == 'serving':
            if self.time >= r.dwell_until:
                r.status = 'moving'
            return
        if r.status == 'waiting':
            r.encounter['waited'] += dt
            if self.time >= r.wait_until:
                self.after_wait(r)
            return
        if r.status != 'moving':
            return
        if r.along < 1e-6 and self.serve_stops(r):
            return      # a re-plan can put a stop exactly where the robot stands
        if r.seg >= len(r.path)-1 and not r.stops:
            self.arrived_home(r)
            return
        hit = self.sense(r)
        passing = r.encounter is not None and r.encounter['mode'] == 'passing'
        if hit and not (passing and r.encounter['hazard'] == hit[1].id):
            d, h = hit
            if d <= DECIDE_DISTANCE + 1e-6:
                self.begin_encounter(r, h)
                self.trigger(r, 'camera', h)
                return
            budget = min(SLOW*dt, d - DECIDE_DISTANCE)   # cautious approach while the camera watches it
        elif hit:
            d, h = hit
            budget = SLOW*dt
            if not h.passable and d - budget <= 1.0:
                self.advance(r, max(0.0, d-1.0))
                self.outcome(r, 'bumper stop: the gap was too narrow')
                self.trigger(r, 'bumper', h)
                return
        else:
            if passing:
                self.outcome(r, 'passed safely')
                self.event(f'{r.id} passed the obstacle', 'Slow pass completed without contact.', 'success', r.id)
                r.encounter = None
            budget = SPEED*dt
        self.advance(r, budget)
        self.check_battery(r)

    def advance(self, r, metres):
        while metres > 1e-9 and r.seg < len(r.path)-1:
            a, b = r.path[r.seg], r.path[r.seg+1]
            length = self.city.length(a, b)
            step = min(metres, length - r.along)
            r.along += step
            metres -= step
            r.distance += step
            r.battery = max(0.0, r.battery - step*BURN)
            if r.along >= length - 1e-6:
                r.seg, r.along = r.seg+1, 0.0
                if self.serve_stops(r):
                    return

    def serve_stops(self, r):
        here = [s for s in r.stops if s['index'] == r.seg]
        if not here:
            return False
        for s in here:
            order = self.orders[s['order']]
            place = self.place(order[s['kind']])
            if s['kind'] == 'pickup':
                order['status'], order['robot'] = 'onboard', r.id
                r.load.append(order['id'])
                self.event(f"{r.id} picked up order #{order['id']}", place['name'], 'success', r.id)
            else:
                order['status'], order['delivered_at'] = 'delivered', self.clock()
                if order['id'] in r.load:
                    r.load.remove(order['id'])
                self.event(f"{r.id} delivered order #{order['id']}", place['name'], 'success', r.id)
        r.stops = [s for s in r.stops if s['index'] != r.seg]
        r.status, r.dwell_until = 'serving', self.time + DWELL
        return True

    def arrived_home(self, r):
        if r.path[-1] != self.city.hub:
            r.status = 'blocked'
            return
        if r.returning or r.battery < 60:
            r.status, r.returning = 'charging', False
            self.event(f'{r.id} charging at the hub', f'Battery {round(r.battery)}%.', 'info', r.id)
        else:
            r.status = 'idle'
            if r.load:
                self.dispatch(f'{r.id} still carries {len(r.load)} parcel(s)')

    def check_battery(self, r):
        if r.returning:
            return
        if r.battery <= RESERVE:
            self.event(f'{r.id} safety reflex', 'Battery reserve reached: returning to the hub without waiting for the agent.', 'warning', r.id)
            self.send_home(r, 'safety reflex')
        elif r.battery < LOW_BATTERY and not r.battery_alerted and r.status == 'moving':
            r.battery_alerted = True
            self.trigger(r, 'low_battery')

    def check_complete(self):
        if self.completed or not self.orders or any(o['status'] != 'delivered' for o in self.orders.values()):
            return
        if all(r.status in ('idle', 'charging') for r in self.robots):
            self.completed = True
            total = round(sum(r.distance for r in self.robots))
            self.event('Mission complete', f'All {len(self.orders)} orders delivered · fleet drove {total} m.', 'success')

    # ------------------------------------------------------------------ decisions
    def begin_encounter(self, r, h):
        if r.encounter is None or r.encounter['hazard'] != h.id:
            r.encounter = {'hazard': h.id, 'waits': 0, 'waited': 0.0, 'decisions': 0, 'since': self.time, 'mode': 'thinking'}

    def trigger(self, r, trigger, h=None):
        obs = self.observe(r, trigger, h)
        r.status = 'thinking'
        if r.encounter:
            r.encounter['mode'] = 'thinking'
            r.encounter['decisions'] += 1
        token = object()
        r.thinking = token
        hid = h.id if h else None
        if self.sync or not (self.llm and self.llm.available):
            self.apply(r, token, trigger, hid, self.agent.decide(obs))
        else:
            future = self.executor.submit(self.agent.decide, obs)
            future.add_done_callback(lambda f: self._decided(r, token, trigger, hid, f))

    def _decided(self, r, token, trigger, hid, future):
        with self.lock:
            self.apply(r, token, trigger, hid, future.result())

    def apply(self, r, token, trigger, hid, result):
        if r not in self.robots or r.thinking is not token:
            return      # stale: the mission was reset or the robot was re-planned meanwhile
        r.thinking = None
        d = result['decision']
        h = self.hazards.get(hid) if hid else None
        self.record(r, trigger, d, result)
        if result['source'] == 'ai':
            self.counts['ai'] += 1
            self.counts['ai_ms'] += result['latency_ms']
        else:
            self.counts['reflex'] += 1
        brain = result['model'] or 'reflex rules'
        self.event(f'{r.id} decided: {ACTION_LABELS[d.action]}', f'[{brain}] {d.analysis}', 'ai' if result['source'] == 'ai' else 'info', r.id)
        if trigger != 'low_battery' and h is None:
            self.outcome(r, 'the obstacle was gone before acting')
            r.status, r.encounter = 'moving', None
            return
        if h and d.share_with_fleet:
            self.share(r, h, d)
        action = d.action
        if action == 'continue':
            r.status, r.encounter = 'moving', None
        elif action == 'proceed_slowly':
            r.encounter['mode'], r.status = 'passing', 'moving'
        elif action == 'wait':
            r.encounter['mode'] = 'waiting'
            r.encounter['waits'] += 1
            r.status, r.wait_until = 'waiting', self.time + d.wait_seconds
            r.thoughts[0]['detail'] = f'{d.wait_seconds} s'
        elif action == 'detour':
            if not self.take_detour(r, h, d.detour_option, d.expected_duration):
                self.ask_dispatcher(r, h, d)
        elif action == 'request_dispatch':
            self.ask_dispatcher(r, h, d)
        elif action == 'return_to_hub':
            if h:
                self.remember(r, h, d.expected_duration)
            self.send_home(r, 'agent decision')

    def record(self, r, trigger, d, result):
        self.ids['thought'] += 1
        camera = r.sensors.get('camera') if trigger != 'low_battery' else None
        lidar = r.sensors.get('lidar') if trigger != 'low_battery' else None
        a, b, _ = self.loc(r)
        nxt = b if b is not None else (r.path[r.seg+1] if r.seg < len(r.path)-1 else None)
        r.thoughts.appendleft({
            'id': self.ids['thought'], 'time': self.clock(), 'robot': r.id, 'trigger': trigger,
            'trigger_label': TRIGGERS[trigger], 'street': self.city.street(a, nxt) if nxt is not None else self.city.label(a),
            'saw': camera['description'] if camera else f'Battery at {round(r.battery)}%',
            'classifier': f"{camera['classifier']} ({camera['confidence']:.2f})" if camera else None,
            'gap': lidar['free_gap_m'] if lidar else None,
            'source': result['source'], 'model': result['model'], 'latency_ms': result['latency_ms'], 'note': result['note'],
            'analysis': d.analysis, 'hazard_kind': d.hazard_kind, 'expected_duration': d.expected_duration,
            'action': d.action, 'action_label': ACTION_LABELS[d.action], 'detail': '',
            'shared': d.share_with_fleet, 'radio': d.radio_message, 'outcome': None})

    def outcome(self, r, text):
        if r.thoughts and r.thoughts[0]['outcome'] is None:
            r.thoughts[0]['outcome'] = text

    def after_wait(self, r):
        h = self.hazards.get(r.encounter['hazard'])
        hit = self.sense(r)
        if h is None or hit is None or hit[1] is not h:
            waited = round(r.encounter['waited'])
            self.outcome(r, f'cleared after {waited} s')
            self.event(f'{r.id}: path clear again', f'Waited {waited} s; continuing.', 'success', r.id)
            if r.encounter['hazard'] in self.knowledge:
                k = self.knowledge.pop(r.encounter['hazard'])
                self.event(f'{r.id} → fleet: {k["street"]} is clear', 'Report withdrawn after a fresh look.', 'success', r.id)
            r.status, r.encounter = 'moving', None
            return
        self.outcome(r, f"still blocked after {round(r.encounter['waited'])} s")
        self.trigger(r, 'still_blocked', h)

    def detours(self, r, h):
        blockers = self.blockers(r)
        blockers.setdefault(key(h.a, h.b), []).append(h.along)
        target = r.stops[0]['node'] if r.stops else self.city.hub
        current = self.remaining(r, r.stops[0]['index'] if r.stops else None)
        found = []
        for node, cost, prefix, start_along in self.options(r, blockers):
            for path in self.city.alternatives(node, target, frozenset(blockers), 2):
                full = prefix + path[1:]
                found.append({'total': cost + self.city.path_length(path), 'path': full, 'start_along': start_along})
        found.sort(key=lambda c: c['total'])
        unique = []
        for c in found:
            if all(self.city.streets(c['path']) != self.city.streets(u['path']) for u in unique):
                unique.append(c)
        unique = unique[:2]
        for c in unique:
            c['extra_m'] = round(c['total'] - current)
            c['via'] = self.city.describe(c['path'])
            # What makes this option different from the other one, so the agent can tell them apart.
            others = {name for o in unique if o is not c for name, _ in self.city.streets(o['path'])}
            c['distinct'] = [f'{name} ({m} m)' for name, m in self.city.streets(c['path']) if name not in others and m >= 5][:4]
        return unique

    def take_detour(self, r, h, option, duration='unknown'):
        candidates = self.detours(r, h)
        if not candidates:
            return False
        c = candidates[min(option, len(candidates))-1]
        self.remember(r, h, duration)
        path, indices = list(c['path']), [len(c['path'])-1]
        try:
            for stop in r.stops[1:]:
                leg, _ = self.city.route(path[-1], stop['node'], frozenset(self.blockers(r)))
                path += leg[1:]
                indices.append(len(path)-1)
            if r.stops:
                leg, _ = self.city.route(path[-1], self.city.hub, frozenset(self.blockers(r)))
                path += leg[1:]
        except Unreachable:
            return False
        r.path, r.seg, r.along = path, 0, c['start_along']
        for stop, index in zip(r.stops, indices):
            stop['index'] = index
        r.thoughts[0]['detail'] = f"+{c['extra_m']} m via {c['via']}"
        self.outcome(r, f"took detour (+{c['extra_m']} m)")
        self.counts['reroutes'] += 1
        r.status, r.encounter = 'moving', None
        return True

    def ask_dispatcher(self, r, h, d):
        if h is not None:
            self.remember(r, h, d.expected_duration)
            if h.id not in self.knowledge:
                # Asking for help reports the obstacle to the server even if not broadcast as a warning.
                self.share(r, h, d, quiet=True)
        r.status, r.encounter = 'moving', None
        self.outcome(r, 'handed the problem to the dispatcher')
        self.dispatch(f'{r.id} asked for help', include_busy=r)

    def send_home(self, r, why):
        r.returning, r.encounter, r.thinking = True, None, None
        released = [o for o in self.orders.values() if o['status'] == 'assigned' and o['robot'] == r.id]
        for o in released:
            o['status'], o['robot'] = 'queued', None
        r.status = 'moving'
        try:
            self.assign(r, [])
        except Unreachable:
            r.status = 'blocked'
            self.event(f'{r.id} cannot reach the hub', 'All routes home are blocked. Clear an obstacle.', 'warning', r.id)
        self.outcome(r, 'returning to the hub')
        self.event(f'{r.id} returning to the hub', f"{why}; parcels on board stay on board, {len(released)} unpicked order(s) released.", 'warning', r.id)
        if released:
            self.dispatch(f'{r.id} went to recharge')

    def share(self, r, h, d, quiet=False):
        ttl = KNOWLEDGE_TTL[d.expected_duration]
        seen = self.confirmations.get(h.id, 0)
        self.confirmations[h.id] = seen + 1
        if seen and ttl is not None:
            # Reported before and still there: the fleet trusts this report longer each time.
            ttl *= 2 ** seen
            self.event(f'{r.id} confirms: still blocked', f'{h.street}: reported {seen + 1} times, the fleet now trusts it for {round(ttl/60)} min.', 'warning', r.id)
        self.knowledge[h.id] = {'hazard': h.id, 'edge': key(h.a, h.b), 'along': h.along, 'pos': h.pos, 'street': h.street,
                                'kind': d.hazard_kind, 'blocks': d.blocks_path, 'by': r.id, 'since': self.time,
                                'until': None if ttl is None else self.time + ttl,
                                'message': d.radio_message or f"{d.hazard_kind.replace('_', ' ')} on {h.street}"}
        self.counts['reports'] += 1
        if not quiet:
            self.event(f'{r.id} → fleet: {d.hazard_kind.replace("_", " ")}', f'{h.street}. "{d.radio_message}"' if d.radio_message else h.street, 'warning', r.id)
        if d.blocks_path:
            self.reroute_affected(key(h.a, h.b), r, f'report from {r.id}')

    def reroute_affected(self, edge, reporter, source):
        for o in self.robots:
            if o is reporter or o.status not in ('moving', 'serving'):
                continue
            ahead = {key(o.path[i], o.path[i+1]) for i in range(o.seg, len(o.path)-1)}
            if edge not in ahead:
                continue
            before = self.remaining(o)
            try:
                self.assign(o, [dict(s) for s in o.stops])
            except Unreachable:
                self.dispatch(f'{o.id} cut off by {source}')
                continue
            self.counts['reroutes'] += 1
            self.event(f'Server re-routed {o.id}', f'Avoids {self.city.street(*edge)} using the {source} ({round(before)} → {round(self.remaining(o))} m).', 'success', o.id)

    # ------------------------------------------------------------------ observation for the agent
    def observe(self, r, trigger, h):
        (lat, lon), heading = self.pos(r)
        if r.seg < len(r.path)-1:
            u, v = r.path[r.seg], r.path[r.seg+1]
            street, nxt, to_next = self.city.street(u, v), self.city.label(v), self.city.length(u, v) - r.along
        else:
            street = nxt = self.city.label(r.path[-1])
            to_next = 0
        hub_m = self.to_hub(r)
        needed = self.remaining(r)
        stops = []
        for s in r.stops[:4]:
            o = self.orders[s['order']]
            p = self.place(o[s['kind']])
            stops.append(f"{'Pick up' if s['kind'] == 'pickup' else 'Drop off'} order #{o['id']}"
                         f"{' (URGENT)' if o['priority'] == 'urgent' else ''} at {p['name']} ({p['kind']}), "
                         f"{round(self.remaining(r, s['index']))} m away")
        encounter = {'waits': 0, 'seconds_waited': 0, 'decisions_so_far': 0, 'seconds_since_first_seen': 0}
        if h and r.encounter:
            e = r.encounter
            encounter = {'waits': e['waits'], 'seconds_waited': round(e['waited']), 'decisions_so_far': e['decisions'],
                         'seconds_since_first_seen': round(self.time - e['since'])}
        reports = sorted(self.knowledge.values(), key=lambda k: haversine(k['pos'], (lat, lon)))[:5]
        if trigger == 'low_battery':
            options = {'continue': f'Keep the current plan ({round(needed)} m left including the trip home).',
                       'return_to_hub': f'Go to the hub now ({round(hub_m or 0)} m) and recharge. Unpicked orders go back to the dispatcher.',
                       'request_dispatch': 'Ask the dispatcher to re-plan with my reduced range; it may move my unpicked orders to other robots.'}
        else:
            options = {}
            if trigger != 'bumper':
                options['proceed_slowly'] = 'Pass the obstacle at 0.5 m/s. Only safe if the lidar gap fits the robot.'
            options['wait'] = 'Hold position here, then re-scan after wait_seconds.'
            detours = self.detours(r, h)
            if detours:
                options['detour'] = [{'option': i+1, 'extra_m': c['extra_m'], 'extra_seconds': round(c['extra_m']/SPEED),
                                      'via': c['via'], 'only_this_option_uses': c['distinct']} for i, c in enumerate(detours)]
            options['request_dispatch'] = 'Report the obstacle to the fleet server and let it re-plan all robots; it may hand my unpicked orders to another robot.'
            options['return_to_hub'] = f'Abort and return to the hub ({round(hub_m or 0)} m).'
        memory = []
        for t in reversed(list(r.thoughts)[:6]):
            line = f"{t['time']} · {t['trigger_label']} on {t['street']}"
            if t['classifier']:
                line += f" · camera: {t['classifier']}"
            line += f" → {t['action_label']}{' ' + t['detail'] if t['detail'] else ''} → {t['outcome'] or 'in progress'}"
            memory.append(line)
        return {
            'robot': f'{r.id} "{r.name}"', 'city': self.city.name, 'clock': self.clock(),
            'trigger': trigger, 'trigger_meaning': TRIGGERS[trigger],
            'position': {'gps': r.sensors.get('gps', [round(lat, 6), round(lon, 6)]), 'gps_accuracy_m': 3.0,
                         'street': street, 'heading': compass(heading), 'next_intersection': nxt,
                         'metres_to_next_intersection': round(to_next)},
            'battery': {'percent': round(r.battery, 1), 'range_m': max(0, int((r.battery-RESERVE)/BURN)),
                        'needed_for_plan_m': round(needed), 'metres_to_hub': None if hub_m is None else round(hub_m)},
            'parcels_on_board': [{'order': oid, 'deliver_to': self.place(self.orders[oid]['dropoff'])['name'],
                                  'urgent': self.orders[oid]['priority'] == 'urgent'} for oid in r.load],
            'capacity': CAPACITY,
            'next_stops': stops,
            'sensors': {'camera': {'range_m': CAMERA_RANGE, 'detection': r.sensors.get('camera') if trigger != 'low_battery' else None},
                        'lidar': r.sensors.get('lidar') if trigger != 'low_battery' else None},
            'encounter': encounter,
            'fleet_reports': [f"{k['by']} · {round(self.time-k['since'])} s ago · {k['kind'].replace('_', ' ')} on {k['street']}"
                              f" ({'blocks the street' if k['blocks'] else 'passable'})" for k in reports],
            'options': options,
            'memory': memory,
        }

    # ------------------------------------------------------------------ dispatcher
    def start_costs(self, r, blockers):
        costs = {}
        for node, cost, _, _ in self.options(r, blockers):
            for n, d in self.city.distances_from(node, frozenset(blockers)).items():
                if cost + d < costs.get(n, float('inf')):
                    costs[n] = cost + d
        return costs

    def dispatch(self, reason, include_busy=None, quiet=False):
        """Re-plan the fleet. quiet=True only logs when a waiting order actually got a robot."""
        blockers = self.blockers()
        waiting = {o['id'] for o in self.orders.values() if o['status'] == 'queued'}
        vehicles = []
        for r in self.robots:
            busy = r.status in ('thinking', 'waiting') and r is not include_busy
            if r.returning or busy or r.status in ('charging', 'blocked'):
                continue
            costs = self.start_costs(r, blockers)
            if self.city.hub not in costs:
                continue
            vehicles.append(Vehicle(r.id, costs, max(0, int((r.battery-RESERVE)/BURN)), CAPACITY-len(r.load), list(r.load)))
        planned = {v.id for v in vehicles}
        jobs = []
        for o in self.orders.values():
            urgent = o['priority'] == 'urgent'
            drop = self.place(o['dropoff'])['node']
            if o['status'] == 'onboard' and o['robot'] in planned:
                jobs.append(Job(o['id'], None, drop, urgent))
            elif o['status'] == 'queued' or (o['status'] == 'assigned' and o['robot'] in planned):
                jobs.append(Job(o['id'], self.place(o['pickup'])['node'], drop, urgent))
        if not jobs and not any(r.stops for r in self.robots if r.id in planned):
            return
        plans, unassigned, metrics = dispatch(vehicles, jobs, self.city.hub,
                                              lambda n: self.city.distances_from(n, frozenset(blockers)), self.solver_ms)
        if plans is None:
            self.event('Dispatcher found no plan in time', 'Current routes kept; try again.', 'warning')
            return
        for v in vehicles:
            r = self.robot(v.id)
            stops = [{'order': oid, 'kind': kind, 'node': node} for oid, kind, node in plans[v.id]]
            for oid, kind, _ in plans[v.id]:
                if kind == 'pickup':
                    self.orders[oid]['status'], self.orders[oid]['robot'] = 'assigned', r.id
            try:
                self.assign(r, stops)
            except Unreachable:
                for o in self.orders.values():
                    if o['status'] == 'assigned' and o['robot'] == r.id:
                        o['status'], o['robot'] = 'queued', None
                r.stops, r.status = [], 'blocked'
                self.event(f'{r.id} cannot follow its plan', 'Its route is blocked by known obstacles; unpicked orders go back to the queue.', 'warning', r.id)
        for oid in unassigned:
            o = self.orders[oid]
            if o['status'] != 'onboard':
                o['status'], o['robot'] = 'queued', None
        if jobs:
            self.plan_metrics = metrics
        if quiet and not any(self.orders[oid]['status'] != 'queued' for oid in waiting):
            return
        self.counts['dispatches'] += 1
        busy = len([r for r in self.robots if r.stops])
        detail = f'{reason} · {len(jobs)} open orders across {busy} robots'
        if metrics.get('optimized') and jobs:
            detail += f" · OR-Tools {metrics['optimized']['distance']} m vs greedy {metrics['greedy']['distance']} m"
        if unassigned:
            detail += f' · {len(unassigned)} waiting (no robot can reach or carry them now)'
        self.event('Dispatcher plan updated', detail, 'success')

    # ------------------------------------------------------------------ public state
    def path_coords(self, r):
        (lat, lon), _ = self.pos(r)
        coords = [[round(lat, 6), round(lon, 6)]]
        if r.seg >= len(r.path)-1:
            return coords
        geometry, walked = self.city.geometry(r.path[r.seg], r.path[r.seg+1]), 0.0
        for p, q in zip(geometry, geometry[1:]):
            walked += haversine(p, q)
            if walked > r.along:
                coords.append(list(q))
        for i in range(r.seg+1, len(r.path)-1):
            coords.extend(list(p) for p in self.city.geometry(r.path[i], r.path[i+1])[1:])
        return coords

    def robot_public(self, r):
        (lat, lon), heading = self.pos(r)
        a, b, _ = self.loc(r)
        nxt = b if b is not None else (r.path[r.seg+1] if r.seg < len(r.path)-1 else None)
        status = 'returning' if r.returning and r.status == 'moving' else r.status
        stops = []
        for s in r.stops:
            o = self.orders[s['order']]
            stops.append({'order': o['id'], 'kind': s['kind'], 'place': self.place(o[s['kind']])['name'],
                          'urgent': o['priority'] == 'urgent', 'metres': round(self.remaining(r, s['index']))})
        return {'id': r.id, 'name': r.name, 'color': r.color, 'status': status, 'pos': [round(lat, 6), round(lon, 6)],
                'heading': round(heading), 'battery': round(r.battery, 1), 'load': r.load, 'capacity': CAPACITY,
                'distance': round(r.distance), 'street': self.city.street(a, nxt) if nxt is not None else self.city.label(a),
                'stops': stops, 'path': self.path_coords(r), 'sensors': r.sensors,
                'wait_left': round(r.wait_until - self.time) if r.status == 'waiting' else None,
                'thoughts': list(r.thoughts)[:12]}

    def snapshot(self):
        delivered = sum(o['status'] == 'delivered' for o in self.orders.values())
        orders = []
        for o in self.orders.values():
            orders.append({**o, 'pickup_name': self.place(o['pickup'])['name'], 'dropoff_name': self.place(o['dropoff'])['name']})
        status = 'completed' if self.completed else 'running' if self.running else 'paused' if self.time else 'ready'
        return {
            'clock': self.clock(), 'time': round(self.time), 'running': self.running, 'speed': self.speed, 'status': status,
            'robots': [self.robot_public(r) for r in self.robots],
            'orders': orders,
            'hazards': [h.public(self.time) for h in self.hazards.values()],
            'knowledge': [{'hazard': k['hazard'], 'pos': k['pos'], 'street': k['street'], 'kind': k['kind'], 'blocks': k['blocks'],
                           'by': k['by'], 'message': k['message'],
                           'expires_in': None if k['until'] is None else max(0, round(k['until']-self.time))}
                          for k in self.knowledge.values()],
            'events': self.events[:80],
            'metrics': {'delivered': delivered, 'orders': len(self.orders),
                        'fleet_distance': round(sum(r.distance for r in self.robots)),
                        'active': sum(r.status not in ('idle', 'charging') for r in self.robots),
                        'ai_decisions': self.counts['ai'], 'reflex_decisions': self.counts['reflex'],
                        'avg_ai_ms': round(self.counts['ai_ms']/self.counts['ai']) if self.counts['ai'] else None,
                        'reports': self.counts['reports'], 'reroutes': self.counts['reroutes'],
                        'dispatches': self.counts['dispatches'],
                        'hazards_seen': sum(bool(h.seen_by) for h in self.hazards.values()),
                        'plan': self.plan_metrics},
        }
