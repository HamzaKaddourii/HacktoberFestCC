"""Fleet dispatcher: assigns pickup -> drop-off orders to robots with OR-Tools.

Model: multi-vehicle pickup-and-delivery. Each robot starts where it is now and ends at the hub.
Constraints: same robot picks up and drops off, pickup before drop-off, parcel capacity, battery range,
parcels already on board stay with their robot. Urgent drop-offs pay a cost for every metre driven
before them, so the solver serves them early. Orders that cannot be served are left unassigned.
Guided local search is time-bounded: good solutions, no global optimality guarantee.
"""
from dataclasses import dataclass, field

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

UNREACHABLE = 1_000_000
DROP_PENALTY = 200_000
URGENT_COST_PER_METRE = 3
SPAN_COST = 3  # cost per metre of the longest route: shares work so the last delivery lands sooner


@dataclass
class Vehicle:
    id: str
    start_costs: dict        # node -> metres from the robot's current position
    range_m: int             # usable battery range
    capacity_left: int       # free parcel slots (capacity - onboard)
    onboard: list = field(default_factory=list)   # order ids already carried


@dataclass
class Job:
    id: int
    pickup: int | None       # None when already on board
    dropoff: int
    urgent: bool = False


def dispatch(vehicles, jobs, hub, distances_from, time_limit_ms=250):
    """Returns ({vehicle_id: [(order_id, 'pickup'|'dropoff', node), ...]}, unassigned_ids, metrics).
    plans is None when the solver finds no solution in time; callers keep their current plans."""
    if not vehicles:
        return {}, [j.id for j in jobs], {}
    points = []                         # (kind, payload)
    for v in vehicles:
        points.append(('start', v))
    hub_index = len(points)
    points.append(('hub', hub))
    job_index = {}
    for j in jobs:
        p = None
        if j.pickup is not None:
            p = len(points)
            points.append(('pickup', j))
        d = len(points)
        points.append(('dropoff', j))
        job_index[j.id] = (p, d)

    def node_of(i):
        kind, payload = points[i]
        return hub if kind == 'hub' else None if kind == 'start' else payload.pickup if kind == 'pickup' else payload.dropoff

    cache = {}
    def from_node(n):
        if n not in cache:
            cache[n] = distances_from(n)
        return cache[n]

    n = len(points)
    matrix = [[0]*n for _ in range(n)]
    for i in range(n):
        kind, payload = points[i]
        row = payload.start_costs if kind == 'start' else from_node(node_of(i))
        for j in range(n):
            target = node_of(j)
            if target is None or i == j:
                continue
            matrix[i][j] = int(round(row.get(target, UNREACHABLE)))

    starts = list(range(len(vehicles)))
    manager = pywrapcp.RoutingIndexManager(n, len(vehicles), starts, [hub_index]*len(vehicles))
    routing = pywrapcp.RoutingModel(manager)
    transit = routing.RegisterTransitCallback(lambda a, b: matrix[manager.IndexToNode(a)][manager.IndexToNode(b)])
    routing.SetArcCostEvaluatorOfAllVehicles(transit)
    # A robot can always afford the trip home, otherwise the whole model would be infeasible.
    ranges = [max(v.range_m, int(v.start_costs.get(hub, 0)) + 1) for v in vehicles]
    routing.AddDimensionWithVehicleCapacity(transit, 0, ranges, True, 'Distance')
    distance = routing.GetDimensionOrDie('Distance')
    distance.SetGlobalSpanCostCoefficient(SPAN_COST)

    def demand(index):
        kind = points[manager.IndexToNode(index)][0]
        return 1 if kind == 'pickup' else -1 if kind == 'dropoff' else 0
    load_cb = routing.RegisterUnaryTransitCallback(demand)
    capacity = [v.capacity_left + len(v.onboard) for v in vehicles]
    routing.AddDimensionWithVehicleCapacity(load_cb, 0, capacity, False, 'Load')
    load = routing.GetDimensionOrDie('Load')
    for k, v in enumerate(vehicles):
        load.CumulVar(routing.Start(k)).SetValue(len(v.onboard))

    owner = {oid: k for k, v in enumerate(vehicles) for oid in v.onboard}
    solver = routing.solver()
    for j in jobs:
        p, d = job_index[j.id]
        di = manager.NodeToIndex(d)
        if p is None:
            # Already on board: only its robot may deliver it; dropping it is a last resort.
            routing.VehicleVar(di).SetValues([-1, owner[j.id]])
            routing.AddDisjunction([di], UNREACHABLE)
        else:
            pi = manager.NodeToIndex(p)
            routing.AddPickupAndDelivery(pi, di)
            solver.Add(routing.VehicleVar(pi) == routing.VehicleVar(di))
            solver.Add(distance.CumulVar(pi) <= distance.CumulVar(di))
            solver.Add(routing.ActiveVar(pi) == routing.ActiveVar(di))
            routing.AddDisjunction([pi], DROP_PENALTY)
            routing.AddDisjunction([di], DROP_PENALTY)
        if j.urgent:
            distance.SetCumulVarSoftUpperBound(di, 0, URGENT_COST_PER_METRE)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(time_limit_ms)
    solution = routing.SolveWithParameters(params)

    if solution is None:
        return None, [j.id for j in jobs], {}
    plans, served = {v.id: [] for v in vehicles}, set()
    routes = {}
    if solution:
        for k, v in enumerate(vehicles):
            index, seq = routing.Start(k), [starts[k]]
            while not routing.IsEnd(index):
                index = solution.Value(routing.NextVar(index))
                node = manager.IndexToNode(index)
                seq.append(node)
                kind, payload = points[node]
                if kind in ('pickup', 'dropoff'):
                    plans[v.id].append((payload.id, kind, node_of(node)))
                    served.add(payload.id)
            routes[v.id] = seq
    unassigned = [j.id for j in jobs if j.id not in served]
    metrics = {'optimized': route_metrics(routes, matrix),
               'greedy': greedy_metrics(vehicles, jobs, job_index, matrix, hub_index)}
    return plans, unassigned, metrics


def route_metrics(routes, matrix):
    lengths = [sum(matrix[a][b] for a, b in zip(seq, seq[1:])) for seq in routes.values()]
    lengths = [m for m in lengths if m < UNREACHABLE]
    return {'distance': sum(lengths), 'makespan': max(lengths, default=0)}


def greedy_metrics(vehicles, jobs, job_index, matrix, hub_index):
    """Baseline a simple dispatcher would produce: each order, in arrival order, goes to the robot
    whose current route end is cheapest, appended as pickup then drop-off. Same constraints on
    reachability, so the comparison is like for like."""
    tails = {k: k for k in range(len(vehicles))}
    lengths = {k: 0 for k in range(len(vehicles))}
    owner = {oid: k for k, v in enumerate(vehicles) for oid in v.onboard}
    for j in jobs:
        p, d = job_index[j.id]
        if p is None:
            k = owner[j.id]
            lengths[k] += matrix[tails[k]][d]
            tails[k] = d
            continue
        k = min(tails, key=lambda k: matrix[tails[k]][p] + matrix[p][d])
        cost = matrix[tails[k]][p] + matrix[p][d]
        if cost >= UNREACHABLE:
            continue
        lengths[k] += cost
        tails[k] = d
    totals = [lengths[k] + matrix[tails[k]][hub_index] for k in lengths]
    totals = [t for t in totals if t < UNREACHABLE]
    return {'distance': sum(totals), 'makespan': max(totals, default=0)}
