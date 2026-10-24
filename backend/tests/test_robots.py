import json

from backend.citymap import key
from backend.fleet import CAMERA_RANGE, DECIDE_DISTANCE, RESERVE, SPEED, TICK_SECONDS, Fleet
from backend.geo import haversine
from backend.tests.conftest import FakeLLM, edge_ahead, place_on_route, run_until


def started(f):
    f.load_sample()
    f.start()
    return next(r for r in f.robots if r.stops)


def not_ahead(f, r, h):
    """The obstacle is no longer anywhere ahead on the robot's remaining route."""
    return all(seen is not h for _, seen in f.ahead(r, float('inf')))


def ai(action, **kw):
    return {'analysis': kw.pop('analysis', f'I choose {action}.'), 'action': action, **kw}


def test_mission_completes_without_teleporting(fleet):
    fleet.load_sample()
    fleet.start()
    step = SPEED * TICK_SECONDS * fleet.speed + 0.5
    last = {r.id: fleet.pos(r)[0] for r in fleet.robots}
    for _ in range(4000):
        fleet.tick()
        for r in fleet.robots:
            here = fleet.pos(r)[0]
            assert haversine(last[r.id], here) <= step
            last[r.id] = here
        if fleet.completed:
            break
    assert fleet.completed
    assert all(o['status'] == 'delivered' for o in fleet.orders.values())
    assert all(fleet.loc(r)[0] == fleet.city.hub for r in fleet.robots)


def test_hidden_obstacle_is_only_known_after_the_camera_sees_it(fleet):
    r = started(fleet)
    h = place_on_route(fleet, r, 'roadworks', metres=120, label='construction', confidence=0.95)
    assert fleet.knowledge == {} and h.seen_by == []
    fleet.tick()
    assert r.sensors['camera'] is None               # 120 m ahead: out of camera range
    assert run_until(fleet, lambda: r.id in h.seen_by)
    assert r.sensors['camera']['distance_m'] <= CAMERA_RANGE
    assert run_until(fleet, lambda: r.thoughts)
    thought = r.thoughts[0]
    assert thought['source'] == 'reflex' and thought['action'] == 'detour'
    assert thought['saw'] == h.view
    assert not_ahead(fleet, r, h)
    assert key(h.a, h.b) in {k['edge'] for k in fleet.knowledge.values()}    # roadworks are shared with the fleet
    assert run_until(fleet, lambda: fleet.completed)


def test_robot_stops_before_the_obstacle_to_think(fleet):
    llm = FakeLLM(ai('wait', wait_seconds=10), ai('detour', detour_option=1))
    f = Fleet(city=fleet.city, llm=llm, sync=True, seed=3, solver_ms=120)
    r = started(f)
    h = place_on_route(f, r, 'parked_vehicle', metres=90)
    assert run_until(f, lambda: llm.prompts)
    d, seen = f.ahead(r, CAMERA_RANGE)[0]
    assert seen is h and DECIDE_DISTANCE - 2 <= d <= DECIDE_DISTANCE + 0.01
    assert r.status == 'waiting'


def test_ai_decision_is_applied_and_shared(fleet):
    llm = FakeLLM(ai('detour', detour_option=1, hazard_kind='roadworks', expected_duration='long',
                     share_with_fleet=True, radio_message='Works on this street.'))
    f = Fleet(city=fleet.city, llm=llm, sync=True, seed=1, solver_ms=120)
    r = started(f)
    h = place_on_route(f, r, 'roadworks', metres=80)
    assert run_until(f, lambda: r.thoughts)
    t = r.thoughts[0]
    assert t['source'] == 'ai' and t['model'] == 'fake-gemma' and t['action'] == 'detour'
    assert t['detail'].startswith('+')
    assert f.knowledge[h.id]['by'] == r.id and f.knowledge[h.id]['until'] is not None
    assert f.counts['ai'] == 1


def test_observation_contains_sensors_map_and_memory_but_no_ground_truth(fleet):
    llm = FakeLLM(ai('wait', wait_seconds=10), ai('detour', detour_option=1))
    f = Fleet(city=fleet.city, llm=llm, sync=True, seed=2, solver_ms=120)
    r = started(f)
    # Ambiguous scene: the classifier says "person", the description says roadworks.
    h = place_on_route(f, r, 'roadworks', metres=80, view='Two workers in hi-vis vests are setting up metal fences around an open manhole.',
                       label='person', confidence=0.61, clears_at=None)
    assert run_until(f, lambda: len(llm.prompts) == 2)
    first = json.loads(llm.prompts[0].split('OBSERVATION:\n')[1])
    second = json.loads(llm.prompts[1].split('OBSERVATION:\n')[1])
    assert first['trigger'] == 'camera' and second['trigger'] == 'still_blocked'
    assert first['sensors']['camera']['detection']['description'] == h.view
    assert first['sensors']['lidar']['free_gap_m'] == h.gap
    assert first['options']['detour'][0]['via']                 # detours described with real street names
    assert first['position']['street'] and first['next_stops']
    assert second['encounter']['waits'] == 1 and second['memory']
    assert 'Wait and re-scan' in second['memory'][-1] and 'still blocked' in second['memory'][-1]
    text = llm.prompts[0].split('OBSERVATION:\n')[1]
    assert 'roadworks' not in text and 'passable' not in text and 'clears_at' not in text


def test_invalid_or_failed_ai_falls_back_to_reflex(fleet):
    llm = FakeLLM(ai('proceed_slowly'), RuntimeError('quota exceeded'))
    f = Fleet(city=fleet.city, llm=llm, sync=True, seed=4, solver_ms=120)
    r = started(f)
    place_on_route(f, r, 'flooding', metres=80)
    assert run_until(f, lambda: r.thoughts)
    t = r.thoughts[-1]
    assert t['source'] == 'reflex' and 'too narrow' in t['note']    # unsafe AI choice rejected
    other = next(o for o in f.robots if o.stops and o is not r)
    place_on_route(f, other, 'flooding', metres=80)
    assert run_until(f, lambda: other.thoughts)
    assert other.thoughts[0]['source'] == 'reflex' and 'RuntimeError' in other.thoughts[0]['note']


def test_pedestrians_wait_then_continue(fleet):
    r = started(fleet)
    h = place_on_route(fleet, r, 'pedestrians', metres=60, label='person', clears_at=None)
    assert run_until(fleet, lambda: r.status == 'waiting')
    h.clears_at = fleet.time + 5
    assert run_until(fleet, lambda: r.thoughts[0]['outcome'] is not None)
    assert r.thoughts[0]['outcome'].startswith('cleared after')
    assert r.status in ('moving', 'serving')


def test_narrow_gap_is_passed_slowly(fleet):
    r = started(fleet)
    h = place_on_route(fleet, r, 'sidewalk_obstacle', metres=60)
    assert h.passable
    path_before = list(r.path)
    assert run_until(fleet, lambda: r.thoughts and r.thoughts[0]['outcome'])
    assert r.thoughts[0]['action'] == 'proceed_slowly' and r.thoughts[0]['outcome'] == 'passed safely'
    assert r.path == path_before


def test_proceeding_into_a_blocked_path_triggers_the_bumper(fleet):
    llm = FakeLLM(ai('proceed_slowly'), ai('detour', detour_option=1))
    f = Fleet(city=fleet.city, llm=llm, sync=True, seed=5, solver_ms=120)
    r = started(f)
    h = place_on_route(f, r, 'parked_vehicle', metres=70, gap=0.85)   # the lidar says it fits...
    assert run_until(f, lambda: len(llm.prompts) == 1)
    h.gap = 0.3                                                       # ...but the van door opens
    assert run_until(f, lambda: len(llm.prompts) == 2)
    second = json.loads(llm.prompts[1].split('OBSERVATION:\n')[1])
    assert second['trigger'] == 'bumper' and 'proceed_slowly' not in second['options']
    assert r.thoughts[-1]['outcome'].startswith('bumper stop')


def test_announced_closure_reroutes_without_seeing_it(fleet):
    r = started(fleet)
    _, (lat, lon), _ = edge_ahead(fleet, r, 150)
    hid = fleet.add_hazard(lat, lon, 'road_closure', announced=True)
    assert fleet.knowledge[hid]['by'] == 'City notice'
    assert not_ahead(fleet, r, fleet.hazards[hid])
    assert fleet.hazards[hid].seen_by == []


def test_low_battery_wakes_the_agent_and_safety_reflex_overrides(fleet):
    r = started(fleet)
    fleet.tick()
    r.battery = 24.0
    fleet.tick()
    assert r.thoughts and r.thoughts[0]['trigger'] == 'low_battery'
    assert r.returning                    # 24% does not cover this plan, so the reflex sends it home
    other = next(o for o in fleet.robots if o.stops and o is not r)
    other.battery, other.battery_alerted = RESERVE, True
    fleet.tick()
    assert other.returning
    assert any('safety reflex' in e['title'] for e in fleet.events)


def test_request_dispatch_reports_and_replans(fleet):
    llm = FakeLLM(ai('request_dispatch', blocks_path=True, expected_duration='permanent'))
    f = Fleet(city=fleet.city, llm=llm, sync=True, seed=6, solver_ms=120)
    r = started(f)
    h = place_on_route(f, r, 'road_closure', metres=70)
    before = f.counts['dispatches']
    assert run_until(f, lambda: r.thoughts)
    assert f.counts['dispatches'] == before + 1
    assert h.id in f.knowledge and f.knowledge[h.id]['until'] is None
    assert not_ahead(f, r, h)


def test_repeat_reports_are_trusted_longer(fleet):
    from backend.agent import Decision
    r = started(fleet)
    h = place_on_route(fleet, r, 'road_closure', metres=60)
    d = Decision(analysis='Closed again.', action='detour', expected_duration='long', share_with_fleet=True)
    fleet.share(r, h, d)
    first = fleet.knowledge[h.id]['until'] - fleet.time
    fleet.share(r, h, d)
    assert fleet.knowledge[h.id]['until'] - fleet.time == 2 * first


def test_stale_private_notes_never_strand_a_robot(fleet):
    r = started(fleet)
    target = r.stops[0]['node']
    # Pretend the robot privately noted every street around its next stop.
    for n in fleet.city.graph.neighbors(target):
        r.avoid[key(target, n)] = [0.0]
        r.avoid_until[key(target, n)] = fleet.time + 999
    fleet.assign(r, [dict(s) for s in r.stops])     # falls back to the shared fleet map
    assert r.avoid == {} and r.path[r.stops[0]['index']] == target
