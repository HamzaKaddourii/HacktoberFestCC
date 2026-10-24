from fastapi.testclient import TestClient

from backend.main import app, fleet, llm


def test_api_flow_and_validation(monkeypatch):
    monkeypatch.setattr(fleet, 'solver_ms', 120)
    # No lifespan: the test steps the simulation itself instead of racing the wall clock.
    client = TestClient(app)
    client.post('/api/simulation/reset')
    city = client.get('/api/map').json()
    assert city['streets'] and city['places'] and city['hub']['pos']
    assert 'roadworks' in city['hazard_kinds']
    assert client.post('/api/simulation/start').status_code == 409          # nothing to deliver yet
    s = client.post('/api/mission/sample').json()
    assert len(s['orders']) == 6 and len(s['robots']) == 4
    assert client.post('/api/mission/sample').status_code == 409
    assert client.post('/api/orders', json={'pickup': 'D1', 'dropoff': 'P1'}).status_code == 422
    s = client.post('/api/orders', json={'pickup': 'P2', 'dropoff': 'D5', 'priority': 'urgent'}).json()
    assert len(s['orders']) == 7
    assert client.post('/api/simulation/start').json()['status'] == 'running'
    busy = next(r for r in s['robots'] if len(r['path']) > 3)
    lat, lon = busy['path'][3]
    assert client.post('/api/hazards', json={'lat': lat, 'lon': lon, 'kind': 'lava'}).status_code == 422
    assert client.post('/api/hazards', json={'lat': lat + 0.01, 'lon': lon, 'kind': 'roadworks'}).status_code == 409
    s = client.post('/api/hazards', json={'lat': lat, 'lon': lon, 'kind': 'roadworks'}).json()
    assert len(s['hazards']) == 1 and s['knowledge'] == []
    assert client.post('/api/simulation/speed', json={'speed': 99}).status_code == 422
    assert client.post('/api/robots/RM-9/battery', json={'level': 20}).status_code == 409
    for _ in range(5000):
        fleet.tick()
        if fleet.completed:
            break
    s = client.get('/api/state').json()
    assert s['status'] == 'completed' and s['metrics']['delivered'] == 7
    assert s['metrics']['plan']['optimized']['distance'] > 0


def test_chat_is_truthful_when_ai_is_unavailable(monkeypatch):
    monkeypatch.setattr(llm, 'available', False)
    before = fleet.snapshot()
    result = TestClient(app).post('/api/ai/chat', json={'message': 'Make order 1 urgent.'}).json()
    assert not result['available'] and not result['applied']
    assert fleet.snapshot()['orders'] == before['orders']
