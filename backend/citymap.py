"""The street map robots read: an OpenStreetMap graph with real street names and metre lengths."""
import json
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from .geo import haversine, interpolate, project

DEFAULT_MAP = Path(__file__).resolve().parent / 'data' / 'city.json'


class Unreachable(ValueError):
    pass


def key(a, b):
    return (a, b) if a < b else (b, a)


@dataclass
class Edge:
    a: int
    b: int
    length: float
    name: str
    highway: str
    geometry: list  # oriented a -> b


class CityMap:
    def __init__(self, data):
        self.data = data
        self.name = data['name']
        self.nodes = [tuple(p) for p in data['nodes']]
        self.edges = {}
        self.graph = nx.Graph()
        for a, b, length, name, highway, geometry in data['edges']:
            if a > b:
                a, b, geometry = b, a, geometry[::-1]
            self.edges[(a, b)] = Edge(a, b, length, name, highway, [tuple(p) for p in geometry])
            self.graph.add_edge(a, b, length=length)
        self.hub = data['hub']['node']
        self.places = {p['id']: p for p in data['places']}
        self.custom = 0            # counter for points added on the dashboard

    @classmethod
    def load(cls, path=DEFAULT_MAP):
        return cls(json.loads(Path(path).read_text()))

    # --- geometry -------------------------------------------------------
    def length(self, a, b):
        return self.edges[key(a, b)].length

    def street(self, a, b):
        return self.edges[key(a, b)].name

    def geometry(self, a, b):
        g = self.edges[key(a, b)].geometry
        return g if a < b else g[::-1]

    def point(self, a, b, along):
        """(lat, lon) and heading at `along` metres from a toward b."""
        return interpolate(self.geometry(a, b), along)

    def to_dir(self, a, b, along_key):
        """Convert a distance measured from the key-ordered edge start into a distance from a."""
        return along_key if a < b else self.length(a, b) - along_key

    def nearest_edge(self, lat, lon):
        best = None
        for (a, b), edge in self.edges.items():
            # Cheap bounding filter before exact projection.
            if haversine((lat, lon), edge.geometry[0]) > edge.length + 150:
                continue
            along, lateral = project(edge.geometry, (lat, lon))
            if best is None or lateral < best[3]:
                best = (a, b, min(along, edge.length), lateral)
        if best is None:
            raise Unreachable('No street near this point.')
        return best

    # --- routing --------------------------------------------------------
    def _weight(self, blocked):
        return lambda a, b, d: None if key(a, b) in blocked else d['length']

    def distances_from(self, node, blocked=frozenset()):
        return nx.single_source_dijkstra_path_length(self.graph, node, weight=self._weight(blocked))

    def route(self, a, b, blocked=frozenset()):
        """Shortest street path between two intersections, avoiding blocked segments (A*, haversine heuristic)."""
        if a == b:
            return [a], 0.0
        try:
            path = nx.astar_path(self.graph, a, b, heuristic=lambda u, v: haversine(self.nodes[u], self.nodes[v]),
                                 weight=self._weight(blocked))
        except nx.NetworkXNoPath:
            raise Unreachable(f'No open street path to {self.label(b)}.') from None
        return path, self.path_length(path)

    def alternatives(self, a, b, blocked=frozenset(), count=2):
        """Up to `count` distinct shortest paths, used to offer the robot detour options."""
        g = nx.subgraph_view(self.graph, filter_edge=lambda u, v: key(u, v) not in blocked)
        found = []
        try:
            for tried, path in enumerate(nx.shortest_simple_paths(g, a, b, weight='length')):
                if not found or self.streets(path) != self.streets(found[-1]):
                    found.append(path)
                if len(found) == count or tried >= 12:
                    break
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            pass
        return found

    def path_length(self, path):
        return sum(self.length(a, b) for a, b in zip(path, path[1:]))

    def add_place(self, lat, lon, name, role):
        """A point the operator clicked, snapped to the closest intersection so robots can reach it."""
        a, b, along, lateral = self.nearest_edge(lat, lon)
        if lateral > 60:
            raise Unreachable('Click closer to a street.')
        node = a if along <= self.length(a, b) / 2 else b
        self.custom += 1
        pid = f'X{self.custom}'
        self.places[pid] = {'id': pid, 'role': role, 'name': name, 'kind': 'custom point', 'node': node}
        return pid

    # --- map reading ----------------------------------------------------
    def streets(self, path):
        """Street names along a path, merged: [(name, metres), ...]."""
        legs = []
        for a, b in zip(path, path[1:]):
            name = self.street(a, b)
            if legs and legs[-1][0] == name:
                legs[-1][1] += self.length(a, b)
            else:
                legs.append([name, self.length(a, b)])
        return [(n, round(m)) for n, m in legs]

    def describe(self, path, limit=4):
        legs = [f'{name} ({m} m)' for name, m in self.streets(path) if m >= 5]
        return ' → '.join(legs[:limit]) + (' → …' if len(legs) > limit else '')

    def label(self, node):
        if node == self.hub:
            return self.data['hub']['name']
        place = next((p for p in self.places.values() if p['node'] == node), None)
        if place:
            return place['name']
        names = sorted({self.street(node, n) for n in self.graph.neighbors(node)})
        return ' / '.join(names[:2])

    def public(self):
        return {'name': self.name, 'bbox': self.data['bbox'], 'center': self.data['center'],
                'attribution': self.data['attribution'], 'fetched': self.data['fetched'],
                'hub': {**self.data['hub'], 'pos': self.nodes[self.hub]},
                'places': [{**p, 'pos': self.nodes[p['node']]} for p in self.places.values()],
                'streets': [{'name': e.name, 'highway': e.highway, 'geometry': e.geometry} for e in self.edges.values()]}
