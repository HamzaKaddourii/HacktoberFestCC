"""Small geodesy helpers. Coordinates are (lat, lon) in degrees, distances in metres."""
from math import asin, atan2, cos, degrees, radians, sin, sqrt

EARTH_RADIUS = 6_371_000


def haversine(a, b):
    lat1, lon1, lat2, lon2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2
    return 2*EARTH_RADIUS*asin(sqrt(h))


def bearing(a, b):
    """Compass bearing from a to b: 0 = north, 90 = east."""
    lat1, lon1, lat2, lon2 = map(radians, (a[0], a[1], b[0], b[1]))
    x = sin(lon2-lon1)*cos(lat2)
    y = cos(lat1)*sin(lat2) - sin(lat1)*cos(lat2)*cos(lon2-lon1)
    return (degrees(atan2(x, y)) + 360) % 360


def compass(deg):
    return ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'][round(deg/45) % 8]


def polyline_length(points):
    return sum(haversine(a, b) for a, b in zip(points, points[1:]))


def interpolate(points, along):
    """Point and heading at `along` metres from the start of a polyline."""
    if len(points) == 1:
        return tuple(points[0]), 0.0
    last = len(points) - 2
    for i, (a, b) in enumerate(zip(points, points[1:])):
        step = haversine(a, b)
        if along <= step or i == last:
            t = 0 if step == 0 else max(0.0, min(1.0, along/step))
            return (a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t), bearing(a, b)
        along -= step


def project(points, p):
    """Distance along a polyline of the point closest to p, and the lateral distance to it."""
    best, best_along, walked = float('inf'), 0.0, 0.0
    # Local equirectangular projection is accurate to centimetres at city scale.
    k = cos(radians(p[0]))
    to_xy = lambda q: ((q[1]-p[1])*k*111_320, (q[0]-p[0])*110_540)
    for a, b in zip(points, points[1:]):
        (ax, ay), (bx, by) = to_xy(a), to_xy(b)
        dx, dy = bx-ax, by-ay
        seg = dx*dx + dy*dy
        t = 0 if seg == 0 else max(0.0, min(1.0, -(ax*dx + ay*dy)/seg))
        cx, cy = ax+dx*t, ay+dy*t
        dist = sqrt(cx*cx + cy*cy)
        if dist < best:
            best, best_along = dist, walked + sqrt(seg)*t
        walked += sqrt(seg)
    return best_along, best
