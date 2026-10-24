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
    assert client.post('/api/orders', json={'pickup': 'D1', 'dropoff': 'P1'}).status_code == 409
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


def test_model_replies_with_stray_tokens_still_parse():
    from backend.llm import extract_json
    assert extract_json('{"explanation": "Done <|endoftext|>"\n}\n```') == {'explanation': 'Done '}
    assert extract_json('```json\n{"action": "wait"}\n```') == {'action': 'wait'}


def test_custom_points_can_be_added_edited_protected_and_removed(monkeypatch):
    monkeypatch.setattr(fleet, 'solver_ms', 120)
    client = TestClient(app)
    client.post('/api/simulation/reset')
    hub = client.get('/api/map').json()['hub']['pos']
    lat, lon = hub[0] + 0.002, hub[1] + 0.001
    s = client.post('/api/places', json={'lat': lat, 'lon': lon, 'name': 'Our stand', 'role': 'pickup'}).json()
    point = next(p for p in s['places'] if p['name'] == 'Our stand')
    assert point['id'].startswith('X') and point['role'] == 'pickup' and point['kind'] == 'custom point'
    assert client.post('/api/places', json={'lat': lat, 'lon': lon, 'name': ' ', 'role': 'pickup'}).status_code == 409
    assert client.post('/api/places', json={'lat': lat + 0.05, 'lon': lon, 'name': 'Far', 'role': 'pickup'}).status_code == 409
    s = client.patch(f"/api/places/{point['id']}", json={'name': 'Hackathon stand'}).json()
    assert any(p['name'] == 'Hackathon stand' for p in s['places'])
    s = client.post('/api/orders', json={'pickup': point['id'], 'dropoff': 'D1'}).json()
    order = s['orders'][-1]
    assert order['pickup_name'] == 'Hackathon stand' and order['status'] == 'assigned'
    # In use by an open order: cannot change type or delete.
    assert client.patch(f"/api/places/{point['id']}", json={'role': 'dropoff'}).status_code == 409
    assert client.delete(f"/api/places/{point['id']}").status_code == 409
    client.post('/api/simulation/start')
    for _ in range(4000):
        fleet.tick()
        if fleet.completed:
            break
    s = client.get('/api/state').json()
    assert s['orders'][-1]['status'] == 'delivered'
    assert client.patch(f"/api/places/{point['id']}", json={'role': 'dropoff'}).status_code == 200
    s = client.delete(f"/api/places/{point['id']}").json()
    assert all(p['id'] != point['id'] for p in s['places'])
    assert s['orders'][-1]['pickup_name'] == 'Hackathon stand'      # delivered order keeps its name


def test_selected_robot_stops_carry_map_positions(monkeypatch):
    monkeypatch.setattr(fleet, 'solver_ms', 120)
    client = TestClient(app)
    client.post('/api/simulation/reset')
    s = client.post('/api/mission/sample').json()
    stops = [stop for r in s['robots'] for stop in r['stops']]
    assert stops and all(len(stop['pos']) == 2 for stop in stops)


def test_operator_route_for_one_robot(monkeypatch):
    monkeypatch.setattr(fleet, 'solver_ms', 120)
    client = TestClient(app)
    client.post('/api/simulation/reset')
    hub = client.get('/api/map').json()['hub']['pos']
    waypoints = [{'place': 'P1'}, {'lat': hub[0] + 0.002, 'lon': hub[1] + 0.002, 'name': 'Team table'}, {'place': 'D2'}]
    assert client.post('/api/robots/RM-2/mission', json={'waypoints': [{'name': 'nowhere'}]}).status_code == 409
    s = client.post('/api/robots/RM-2/mission', json={'waypoints': waypoints}).json()
    r = next(x for x in s['robots'] if x['id'] == 'RM-2')
    assert r['status'] == 'planned' and r['mission']['state'] == 'saved'
    assert [p['name'] for p in r['mission']['points']][1] == 'Team table'
    assert [st['kind'] for st in r['stops']] == ['waypoint'] * 3 and len(r['path']) > 3
    # The dispatcher leaves a robot with a drawn route alone.
    s = client.post('/api/orders', json={'pickup': 'P3', 'dropoff': 'D4'}).json()
    assert s['orders'][-1]['robot'] != 'RM-2'
    start = fleet.robot('RM-2').distance
    for _ in range(20):
        fleet.tick()
    assert fleet.robot('RM-2').distance == start                    # saved, not started: it waits
    s = client.post('/api/robots/RM-2/mission/start').json()
    assert s['running'] and next(x for x in s['robots'] if x['id'] == 'RM-2')['mission']['state'] == 'running'
    reached = []
    for _ in range(4000):
        fleet.tick()
        m = fleet.robot('RM-2').mission
        if m:
            reached = [p['n'] for p in m['points'] if p['done']]
        if m is None:
            break
    assert fleet.robot('RM-2').mission is None                      # route finished and cleared
    assert any('RM-2 finished its route' in e['title'] for e in fleet.events)
    titles = [e['title'] for e in reversed(fleet.events) if e['title'].startswith('RM-2 reached point')]
    assert titles == ['RM-2 reached point 1', 'RM-2 reached point 2', 'RM-2 reached point 3']
    assert fleet.loc(fleet.robot('RM-2'))[0] == fleet.city.hub


def test_failed_calls_are_retried_then_raise_for_offline_rules():
    from types import SimpleNamespace
    import pytest
    from backend.agent import Decision
    from backend.llm import LLM

    class Busy(Exception):
        code = 503

    calls = []

    def flaky(fail_times):
        def generate_content(model, contents, config=None):
            calls.append(model)
            if len(calls) <= fail_times:
                raise Busy('high demand')
            return SimpleNamespace(text='{"analysis": "Go around.", "action": "detour"}')
        return generate_content

    llm = LLM()
    llm.model, llm.attempts = 'gemma-main', 3
    llm.client = SimpleNamespace(models=SimpleNamespace(generate_content=flaky(2)))
    info = {}
    assert llm.generate('prompt', Decision, info).action == 'detour'
    assert info['tries'] == 3 and calls == ['gemma-main'] * 3          # same model, no backups
    calls.clear()
    llm.client = SimpleNamespace(models=SimpleNamespace(generate_content=flaky(99)))
    info = {}
    with pytest.raises(Busy):
        llm.generate('prompt', Decision, info)
    assert info['tries'] == 3 and len(calls) == 3
