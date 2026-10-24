import itertools
import pytest
from backend.planner import BASE, STATIONS, WALLS, PlanningError, astar, graph, solve
from backend.engine import Engine


def deliveries(names, urgent=()):
    return [{'station': s, 'priority': 'urgent' if s in urgent else 'normal'} for s in names]


def assert_traversable(path, blocked=()):
    for a, b in zip(path, path[1:]):
        assert sum(abs(x-y) for x, y in zip(a,b)) == 1
        assert b not in WALLS and b not in blocked


def test_astar_shortest_and_obstacle_detour():
    g = graph()
    p = astar(g, (2, 8), (22, 8))
    assert len(p)-1 == 20
    blocked = {(12, 8)}
    detour = astar(graph(blocked), (2,8), (22,8))
    assert len(detour) > len(p)
    assert_traversable(detour, blocked)


def test_unreachable_explicit():
    blocked = {(20,3), (22,3), (21,2), (21,4)}
    with pytest.raises(PlanningError, match='Unreachable'):
        astar(graph(blocked), BASE, STATIONS['C'])
    p = solve(BASE, deliveries('AC'), blocked)
    assert p.unreachable == ['C']
    assert p.order == ['A']
    assert_traversable(p.path, blocked)


def test_solver_distance_matches_path_and_small_bruteforce():
    tasks = deliveries('CADBE')
    p = solve(BASE, tasks)
    assert p.distance == len(p.path)-1
    assert p.path[0] == p.path[-1] == BASE
    assert set(p.order) == set('ABCDE')
    assert p.distance < p.baseline
    assert_traversable(p.path)
    g = graph()
    def cost(order):
        points = [BASE]+[STATIONS[s] for s in order]+[BASE]
        return sum(len(astar(g,a,b))-1 for a,b in zip(points,points[1:]))
    # Exact enumeration is a test oracle for this five-station fixture, not a solver guarantee.
    assert p.distance == min(cost(order) for order in itertools.permutations('ABCDE'))


def test_urgent_precedes_normal_and_conflicts_rejected():
    p = solve(BASE, deliveries('ABCDE', urgent='D'))
    assert p.order[0] == 'D'
    with pytest.raises(PlanningError, match='Conflicting'):
        solve(BASE, deliveries('AD', urgent='D'), precedence=[('A','D')])


def test_replanning_preserves_progress_no_teleport_and_completes():
    e = Engine()
    for s in 'CADBE':
        e.add(s)
    e.start()
    for _ in range(250):
        e.tick()
        if any(d['status']=='completed' for d in e.deliveries):
            break
    completed = {d['station'] for d in e.deliveries if d['status']=='completed'}
    assert completed
    position, traveled = e.position, e.distance
    block = next(c for c in e.path[e.cursor+2:] if c not in STATIONS.values() and c != BASE and c != position)
    e.transaction(lambda: e.obstacle(block, True), 'Corridor blocked')
    assert e.position == position and e.distance == traveled
    assert e.path[0] == position
    assert_traversable(e.path, e.blocked)
    assert {d['station'] for d in e.deliveries if d['status']=='completed'} == completed
    assert e.status == 'running'
    for _ in range(500):
        old = e.position
        e.tick()
        assert sum(abs(x-y) for x,y in zip(old,e.position)) <= 1
        if e.status == 'completed':
            break
    assert e.status == 'completed' and e.position == BASE
    assert not e.pending()


def test_invalid_update_rolls_back():
    e=Engine()
    e.add('A')
    e.start()
    before=e.snapshot()
    def invalid():
        e.priority('D')
        e.obstacle(e.position, True)
    with pytest.raises(PlanningError):
        e.transaction(invalid, 'invalid')
    assert e.snapshot()==before


def test_pause_low_battery_charging_and_resume():
    e=Engine()
    for s in 'CADBE': e.add(s)
    e.start()
    for _ in range(7): e.tick()
    e.status='paused'
    old=e.position
    e.tick()
    assert e.position==old
    e.start()
    e.transaction(lambda:setattr(e,'battery',15), 'Low battery')
    assert e.returning and e.path[-1]==BASE
    charging_seen=False
    for _ in range(700):
        e.tick()
        charging_seen |= e.status=='charging'
        if e.status=='completed': break
    assert charging_seen
    assert e.status=='completed'
    assert not e.pending()


def test_disconnect_base_stops_safely_and_recovers():
    e=Engine()
    e.add('C')
    e.start()
    for _ in range(5):e.tick()
    position=e.position
    neighbors={(1,14),(3,14),(2,13),(2,15)}
    e.transaction(lambda:[e.obstacle(c,True) for c in neighbors], 'Dock blocked')
    assert e.position==position and e.status=='blocked'
    e.tick()
    assert e.position==position
    e.transaction(lambda:e.obstacle((2,13),False), 'Access restored')
    e.start()
    assert e.status=='running'


def test_ten_stations_supported():
    p=solve(BASE, deliveries('ABCDEFGHIJ'))
    assert len(p.order)==10 and len(set(p.order))==10
    assert_traversable(p.path)


def test_replan_keeps_pause_and_charge_states():
    e=Engine()
    e.add('C')
    e.start()
    e.status='paused'
    e.transaction(lambda:e.priority('A'), 'Urgent A')
    assert e.status=='paused'
    e.position=BASE
    e.status='charging'
    e.battery=40
    e.transaction(lambda:e.priority('D'), 'Urgent D')
    assert e.status=='charging'
    e.tick()
    assert e.battery==45


def test_trail_records_every_real_step():
    e=Engine()
    e.add('C')
    e.start()
    for _ in range(12):e.tick()
    assert len(e.trail)==e.distance+1
    assert e.trail[-1]==e.position
    assert_traversable(e.trail)
