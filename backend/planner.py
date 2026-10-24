"""Grid-distance routing. All distances are simulated metres (one per grid edge)."""
from dataclasses import dataclass
import networkx as nx
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

WIDTH, HEIGHT = 25, 17
BASE = (2, 14)
STATIONS = {'A': (3, 3), 'B': (12, 2), 'C': (21, 3), 'D': (21, 13), 'E': (11, 13),
            'F': (3, 8), 'G': (8, 2), 'H': (16, 2), 'I': (22, 8), 'J': (16, 14)}
SHELVES = [(5, 4, 3, 3), (10, 5, 5, 2), (17, 4, 3, 3),
           (5, 10, 3, 3), (10, 9, 5, 2), (17, 10, 3, 3)]
WALLS = {(x, y) for x in range(WIDTH) for y in range(HEIGHT)
         if x in (0, WIDTH-1) or y in (0, HEIGHT-1)}
for x, y, w, h in SHELVES:
    WALLS.update((a, b) for a in range(x, x+w) for b in range(y, y+h))
# Named corridor is a concrete cross-aisle gate, not an ambiguous station-to-station line.
CORRIDORS = {'A-C': [(x, 8) for x in range(9, 16)]}


class PlanningError(ValueError):
    pass


def graph(blocked=()):
    g = nx.grid_2d_graph(WIDTH, HEIGHT)
    g.remove_nodes_from(WALLS | set(blocked))
    return g


def astar(g, start, end):
    try:
        return nx.astar_path(g, tuple(start), tuple(end),
                             heuristic=lambda a, b: abs(a[0]-b[0])+abs(a[1]-b[1]))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        raise PlanningError(f'Unreachable location: {tuple(end)}') from None


@dataclass
class Plan:
    order: list
    path: list
    stops: list
    distance: int
    baseline: int
    unreachable: list


def solve(start, deliveries, blocked=(), precedence=()):
    """One vehicle, fixed return to base. Urgent stops precede every normal stop.

    OR-Tools local search is time-bounded and is not a global optimality guarantee.
    Unreachable deliveries stay pending and are excluded from both comparisons.
    """
    g = graph(blocked)
    astar(g, start, BASE)  # Returning safely is mandatory.
    reachable, unreachable = [], []
    for d in deliveries:
        try:
            astar(g, start, STATIONS[d['station']])
            reachable.append(d)
        except PlanningError:
            unreachable.append(d['station'])
    points = [tuple(start)] + [STATIONS[d['station']] for d in reachable] + [BASE]
    paths = [[astar(g, a, b) for b in points] for a in points]
    distances = [[len(p)-1 for p in row] for row in paths]
    n = len(points)
    baseline = sum(distances[i][i+1] for i in range(n-1))
    if not reachable:
        return Plan([], paths[0][-1], [], distances[0][-1], baseline, unreachable)
    manager = pywrapcp.RoutingIndexManager(n, 1, [0], [n-1])
    routing = pywrapcp.RoutingModel(manager)
    cost = routing.RegisterTransitCallback(lambda i, j: distances[manager.IndexToNode(i)][manager.IndexToNode(j)])
    routing.SetArcCostEvaluatorOfAllVehicles(cost)
    step = routing.RegisterTransitCallback(lambda i, j: 1)
    routing.AddDimension(step, 0, n+1, True, 'Visit')
    ranks = routing.GetDimensionOrDie('Visit')
    indices = {d['station']: manager.NodeToIndex(i+1) for i, d in enumerate(reachable)}
    constraints = list(precedence)
    constraints += [(a['station'], b['station']) for a in reachable for b in reachable
                    if a['priority'] == 'urgent' and b['priority'] == 'normal']
    dag = nx.DiGraph()
    dag.add_nodes_from(indices)
    for a, b in constraints:
        if a in indices and b in indices:
            dag.add_edge(a, b)
            routing.solver().Add(ranks.CumulVar(indices[a]) < ranks.CumulVar(indices[b]))
    if not nx.is_directed_acyclic_graph(dag):
        raise PlanningError('Conflicting priority/order constraints. Remove the conflicting order or priority.')
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(180)
    solution = routing.SolveWithParameters(params)
    if solution is None:
        raise PlanningError('No feasible sequence found within the solver time limit.')
    visit = [0]
    index = routing.Start(0)
    while not routing.IsEnd(index):
        index = solution.Value(routing.NextVar(index))
        visit.append(manager.IndexToNode(index))
    path, stops, order = [tuple(start)], [], []
    for a, b in zip(visit, visit[1:]):
        path.extend(paths[a][b][1:])
        if b != n-1:
            station = reachable[b-1]['station']
            order.append(station)
            stops.append({'station': station, 'index': len(path)-1})
    return Plan(order, path, stops, len(path)-1, baseline, unreachable)
