from fastapi.testclient import TestClient
from backend.main import app, engine, coordinator
from backend.models import AIInstructions, Delivery, Obstacle


def test_api_demo_and_validation():
    # No lifespan: deterministic stepping avoids a wall-clock race in this test.
    client=TestClient(app)
    client.post('/api/simulation/reset')
    assert client.get('/api/map').status_code==200
    assert client.post('/api/deliveries',json={'station':'Z'}).status_code==422
    s=client.post('/api/mission/sample').json()
    assert len(s['deliveries'])==5
    assert client.post('/api/mission/sample').status_code==409
    assert client.post('/api/optimize').json()['analytics']['optimized']>0
    assert client.post('/api/simulation/start').json()['status']=='running'
    for _ in range(12):engine.tick()
    pos=engine.position
    s=client.post('/api/corridors',json={'blocked':True}).json()
    assert tuple(s['position'])==pos
    assert s['analytics']['replans']>0
    assert client.post('/api/events/urgent',json={'station':'D'}).status_code==200
    assert client.post('/api/simulation/pause').json()['status']=='paused'
    assert client.post('/api/simulation/start').json()['status']=='running'
    for _ in range(600):engine.tick()
    assert client.get('/api/state').json()['status']=='completed'
    assert client.get('/api/analytics').json()['completed']==5


def test_ai_unavailable_is_truthful(monkeypatch):
    monkeypatch.setattr(coordinator,'available',False)
    before=engine.snapshot()
    result=TestClient(app).post('/api/ai/chat',json={'message':'Prioritize C.'}).json()
    assert not result['available'] and not result['applied']
    assert engine.snapshot()==before


def test_ai_commands_validated_atomically(monkeypatch):
    client=TestClient(app)
    client.post('/api/simulation/reset')
    monkeypatch.setattr(coordinator,'available',True)
    monkeypatch.setattr(coordinator,'ask',lambda *_:AIInstructions(explanation='Prioritize D.',deliveries=[Delivery(station='D',priority='urgent')]))
    r=client.post('/api/ai/chat',json={'message':'Deliver to D immediately'}).json()
    assert r['applied'] and engine.pending()[0]['priority']=='urgent'
    before=engine.snapshot()
    monkeypatch.setattr(coordinator,'ask',lambda *_:AIInstructions(explanation='Invalid',deliveries=[Delivery(station='A')],obstacles=[Obstacle(cell=engine.position)]))
    assert client.post('/api/ai/chat',json={'message':'Invalid command'}).status_code==409
    assert engine.snapshot()==before
