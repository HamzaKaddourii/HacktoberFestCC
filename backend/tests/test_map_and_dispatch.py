import networkx as nx
import pytest

from backend.citymap import Unreachable, key
from backend.dispatcher import Job, Vehicle, dispatch
from backend.fleet import CAPACITY


def test_real_map_is_connected_and_named(city):
    assert nx.is_connected(city.graph)
    assert city.hub in city.graph
    assert len(city.edges) > 100
    assert all(p['node'] in city.graph for p in city.places.values())
    assert {p['role'] for p in city.places.values()} == {'pickup', 'dropoff'}
    assert sum(not e.name.startswith('unnamed') for e in city.edges.values()) > len(city.edges) * 0.9


def test_route_avoids_blocked_street_and_reports_unreachable(city):
    a, b = city.hub, city.places['D1']['node']
    path, length = city.route(a, b)
    assert path[0] == a and path[-1] == b
    assert length == pytest.approx(city.path_length(path))
    edge = key(path[len(path)//2], path[len(path)//2 + 1])
    detour, longer = city.route(a, b, {edge})
    assert edge not in {key(u, v) for u, v in zip(detour, detour[1:])}
    assert longer >= length
    around = {key(b, n) for n in city.graph.neighbors(b)}
    with pytest.raises(Unreachable):
        city.route(a, b, around)


def test_nearest_edge_snaps_clicks_to_streets(city):
    (a, b), edge = next(iter(city.edges.items()))
    (lat, lon), _ = city.point(a, b, edge.length/2)
    sa, sb, along, lateral = city.nearest_edge(lat, lon)
    assert lateral < 1 and along == pytest.approx(edge.length/2, abs=2)
    assert city.streets([a, b])[0][0] == edge.name


def plan_is_valid(plan, onboard=()):
    load, seen = len(onboard), set(onboard)
    for oid, kind, _ in plan:
        if kind == 'pickup':
            seen.add(oid)
            load += 1
        else:
            assert oid in seen, 'drop-off before pickup'
            load -= 1
        assert 0 <= load <= CAPACITY


def test_sample_dispatch_beats_greedy_and_respects_constraints(fleet):
    fleet.load_sample()
    assert all(o['status'] == 'assigned' for o in fleet.orders.values())
    for r in fleet.robots:
        plan_is_valid([(s['order'], s['kind'], s['node']) for s in r.stops])
    metrics = fleet.plan_metrics
    assert metrics['optimized']['distance'] < metrics['greedy']['distance']
    assert metrics['optimized']['makespan'] < metrics['greedy']['makespan']


def test_onboard_parcels_stay_and_urgent_goes_first(city):
    dist = lambda n: city.distances_from(n)
    hub_costs = dist(city.hub)
    p = [pl['node'] for pl in city.places.values() if pl['role'] == 'pickup']
    d = [pl['node'] for pl in city.places.values() if pl['role'] == 'dropoff']
    vehicles = [Vehicle('A', hub_costs, 8000, CAPACITY-1, [1]), Vehicle('B', hub_costs, 8000, CAPACITY, [])]
    jobs = [Job(1, None, d[0]), Job(2, p[0], d[1]), Job(3, p[1], d[2]), Job(4, p[2], d[3], urgent=True)]
    plans, unassigned, _ = dispatch(vehicles, jobs, city.hub, dist, 300)
    assert not unassigned
    assert (1, 'dropoff', d[0]) in plans['A']
    owner = next(v for v, plan in plans.items() if any(oid == 4 for oid, _, _ in plan))
    drops = [oid for oid, kind, _ in plans[owner] if kind == 'dropoff']
    assert drops[0] == 4
    for v, plan in plans.items():
        plan_is_valid(plan, onboard=[1] if v == 'A' else [])


def test_unreachable_order_is_left_waiting(city):
    pickup = city.places['P1']['node']
    blocked = frozenset(key(pickup, n) for n in city.graph.neighbors(pickup))
    dist = lambda n: city.distances_from(n, blocked)
    vehicles = [Vehicle('A', dist(city.hub), 8000, CAPACITY, [])]
    jobs = [Job(1, pickup, city.places['D1']['node']), Job(2, city.places['P2']['node'], city.places['D2']['node'])]
    plans, unassigned, _ = dispatch(vehicles, jobs, city.hub, dist, 150)
    assert unassigned == [1]
    assert [oid for oid, _, _ in plans['A']] == [2, 2]
