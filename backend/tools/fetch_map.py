"""Download a real street network from OpenStreetMap and save it as backend/data/city.json.

    python -m backend.tools.fetch_map --place "Le Marais, Paris" --radius 650
    python -m backend.tools.fetch_map --bbox 48.853,2.351,48.865,2.369 --name "Le Marais, Paris"

The snapshot is committed so the demo works offline; re-run this to move the fleet to another city.
Map data © OpenStreetMap contributors, ODbL.
"""
import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

import networkx as nx

from backend.geo import haversine, polyline_length

USER_AGENT = 'RouteMindAI-hackathon/1.0 (educational demo)'
OVERPASS = 'https://overpass-api.de/api/interpreter'
NOMINATIM = 'https://nominatim.openstreetmap.org/search'
OUTPUT = Path(__file__).resolve().parents[1] / 'data' / 'city.json'
# Streets a sidewalk robot can follow. Sidewalk robots may travel both directions of one-way streets.
HIGHWAYS = 'primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|unclassified|living_street|pedestrian'
PICKUP_KINDS = {'restaurant', 'fast_food', 'cafe', 'pharmacy', 'bakery', 'supermarket', 'convenience', 'florist', 'deli', 'books'}
DROP_KINDS = {'clinic', 'doctors', 'hospital', 'school', 'library', 'bank', 'post_office', 'townhall', 'office', 'hotel', 'theatre', 'museum'}


def request(url, data=None):
    req = urllib.request.Request(url, data=data, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as res:
        return json.loads(res.read())


def overpass(query):
    # The public Overpass server rate-limits and returns 429/502/504 under load; back off and retry.
    for attempt in range(5):
        try:
            return request(OVERPASS, urllib.parse.urlencode({'data': query}).encode())['elements']
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 502, 503, 504) or attempt == 4:
                raise
            print(f'Overpass busy (HTTP {exc.code}); retrying in {10*(attempt+1)} s…')
            time.sleep(10*(attempt+1))


def bbox_for_place(place, radius):
    hits = request(f'{NOMINATIM}?{urllib.parse.urlencode({"q": place, "format": "json", "limit": 1})}')
    if not hits:
        raise SystemExit(f'Place not found: {place}')
    lat, lon = float(hits[0]['lat']), float(hits[0]['lon'])
    dlat = radius/111_320
    dlon = radius/(111_320*math.cos(math.radians(lat)))
    return lat-dlat, lon-dlon, lat+dlat, lon+dlon


def build_graph(ways, bbox):
    s, w, n, e = bbox
    inside = lambda p: s <= p[0] <= n and w <= p[1] <= e
    uses = Counter()
    for way in ways:
        uses.update(way['nodes'])
        uses.update([way['nodes'][0], way['nodes'][-1]])
    g = nx.Graph()
    for way in ways:
        tags = way.get('tags', {})
        name = tags.get('name') or tags.get('ref') or f"unnamed {tags.get('highway', 'street')}"
        ids, coords = way['nodes'], [(p['lat'], p['lon']) for p in way['geometry']]
        start = 0
        # Split each way at intersections so every edge connects two decision points.
        for i in range(1, len(ids)):
            if uses[ids[i]] < 2 and i != len(ids)-1:
                continue
            u, v, geometry = ids[start], ids[i], coords[start:i+1]
            start = i
            if u == v or not (inside(geometry[0]) and inside(geometry[-1])):
                continue
            length = polyline_length(geometry)
            if length < 0.5:
                continue
            if g.has_edge(u, v) and g.edges[u, v]['length'] <= length:
                continue
            g.add_node(u, pos=geometry[0])
            g.add_node(v, pos=geometry[-1])
            g.add_edge(u, v, length=length, name=name, highway=tags.get('highway'), geometry=geometry, a=u)
    return g.subgraph(max(nx.connected_components(g), key=len)).copy()


def spread(candidates, count, taken):
    """Farthest-point sampling so destinations cover the whole district."""
    chosen = []
    pool = [c for c in candidates if c['node'] not in taken]
    while pool and len(chosen) < count:
        if not chosen:
            pick = pool[0]
        else:
            pick = max(pool, key=lambda c: min(haversine(c['pos'], o['pos']) for o in chosen))
        chosen.append(pick)
        taken.add(pick['node'])
        pool = [c for c in pool if c['node'] not in taken]
    return chosen


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--place', help='Free-text place resolved with OpenStreetMap Nominatim')
    parser.add_argument('--radius', type=float, default=650, help='Half-width of the area in metres (with --place)')
    parser.add_argument('--bbox', help='south,west,north,east')
    parser.add_argument('--name', help='Display name for the area')
    parser.add_argument('--output', default=str(OUTPUT))
    args = parser.parse_args()
    if not args.bbox and not args.place:
        parser.error('Use --place or --bbox.')
    bbox = tuple(map(float, args.bbox.split(','))) if args.bbox else bbox_for_place(args.place, args.radius)
    box = ','.join(f'{v:.6f}' for v in bbox)

    print('Downloading streets…')
    ways = [w for w in overpass(f'[out:json][timeout:120];way["highway"~"^({HIGHWAYS})$"]["area"!="yes"]({box});out body geom;')
            if w.get('geometry')]
    g = build_graph(ways, bbox)
    print(f'{g.number_of_nodes()} intersections, {g.number_of_edges()} street segments')

    print('Downloading places…')
    pois = overpass(f'[out:json][timeout:120];(node["amenity"]["name"]({box});node["shop"]["name"]({box});'
                    f'node["office"]["name"]({box});node["tourism"~"hotel|museum"]["name"]({box}););out body;')
    ids = list(g.nodes)
    index = {osm: i for i, osm in enumerate(ids)}
    positions = [g.nodes[osm]['pos'] for osm in ids]
    pickups, drops = [], []
    for poi in pois:
        tags = poi['tags']
        kind = tags.get('amenity') or tags.get('shop') or ('office' if 'office' in tags else tags.get('tourism'))
        if kind not in PICKUP_KINDS | DROP_KINDS:
            continue
        pos = (poi['lat'], poi['lon'])
        node = min(range(len(positions)), key=lambda i: haversine(pos, positions[i]))
        if haversine(pos, positions[node]) > 60 or len(tags['name']) > 32:
            continue
        place = {'name': tags['name'], 'kind': kind, 'node': node, 'pos': positions[node],
                 'street': tags.get('addr:street')}
        (pickups if kind in PICKUP_KINDS else drops).append(place)

    centre = ((bbox[0]+bbox[2])/2, (bbox[1]+bbox[3])/2)
    hub = min((i for i, osm in enumerate(ids) if g.degree(osm) >= 3), key=lambda i: haversine(centre, positions[i]))
    taken = {hub}
    chosen_pickups = spread(sorted(pickups, key=lambda p: haversine(centre, p['pos'])), 8, taken)
    # Prefer public destinations (clinics, schools, hotels...) and use offices only to fill gaps.
    public = sorted([p for p in drops if p['kind'] != 'office'], key=lambda p: haversine(centre, p['pos']))
    chosen_drops = spread(public, 12, taken)
    chosen_drops += spread([p for p in drops if p['kind'] == 'office'], 12-len(chosen_drops), taken)
    places = []
    for role, group in (('pickup', chosen_pickups), ('dropoff', chosen_drops)):
        for p in group:
            places.append({'id': f'{role[0].upper()}{len([q for q in places if q["role"] == role])+1}', 'role': role,
                           'name': p['name'], 'kind': p['kind'], 'node': p['node']})

    edges = []
    for u, v, data in g.edges(data=True):
        geometry = data['geometry'] if data['a'] == u else data['geometry'][::-1]
        edges.append([index[u], index[v], round(data['length'], 1), data['name'], data['highway'],
                      [[round(lat, 6), round(lon, 6)] for lat, lon in geometry]])
    city = {'name': args.name or args.place or 'Custom area', 'bbox': [round(v, 6) for v in bbox],
            'center': [round(centre[0], 6), round(centre[1], 6)], 'fetched': date.today().isoformat(),
            'attribution': 'Map data © OpenStreetMap contributors (ODbL)',
            'nodes': [[round(lat, 6), round(lon, 6)] for lat, lon in positions], 'edges': edges,
            'hub': {'name': 'RouteMind Hub', 'node': hub}, 'places': places}
    Path(args.output).write_text(json.dumps(city, ensure_ascii=False, separators=(',', ':')))
    print(f'Saved {args.output}: {len(chosen_pickups)} pickup places, {len(chosen_drops)} drop-off places')


if __name__ == '__main__':
    main()
