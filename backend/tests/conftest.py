import pytest

from backend.citymap import CityMap, key
from backend.fleet import Fleet


class FakeLLM:
    """Stands in for Gemma: returns scripted replies and records every prompt it was shown."""
    available = True
    model = 'fake-gemma'

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def generate(self, prompt, schema, info=None):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return schema.model_validate(reply)


@pytest.fixture(scope='session')
def city():
    return CityMap.load()


@pytest.fixture
def fleet(city):
    return Fleet(city=city, sync=True, seed=7, solver_ms=120)


def edge_ahead(f, r, metres):
    """An edge on the robot's route whose midpoint is at least `metres` ahead, with that midpoint."""
    dist = f.city.length(r.path[r.seg], r.path[r.seg+1]) - r.along if r.seg < len(r.path)-1 else 0
    for i in range(r.seg+1, len(r.path)-1):
        a, b = r.path[i], r.path[i+1]
        length = f.city.length(a, b)
        if dist + length/2 >= metres and length >= 20:
            (lat, lon), _ = f.city.point(a, b, length/2)
            return key(a, b), (lat, lon), dist + length/2
        dist += length
    raise AssertionError('route too short')


def place_on_route(f, r, kind, metres=60, **override):
    edge, (lat, lon), at = edge_ahead(f, r, metres)
    hid = f.add_hazard(lat, lon, kind)
    h = f.hazards[hid]
    assert key(h.a, h.b) == edge
    for k, v in override.items():
        setattr(h, k, v)
    return h


def run_until(f, condition, limit=4000):
    for _ in range(limit):
        if condition():
            return True
        f.tick()
    return condition()
