import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import copilot
from .fleet import TICK_SECONDS, Fleet
from .hazards import KINDS
from .llm import LLM
from .models import BatteryIn, Chat, ChatResponse, HazardIn, MissionIn, OrderIn, PlaceIn, PlaceUpdate, PriorityIn, SpeedIn

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
llm = LLM()
fleet = Fleet(llm=llm)


async def ticker():
    while True:
        await asyncio.sleep(TICK_SECONDS)
        with fleet.lock:
            fleet.tick()


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(ticker())
    discovery = asyncio.create_task(asyncio.to_thread(llm.connect))
    yield
    task.cancel()
    discovery.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title='RouteMind AI', version='2.0.0', lifespan=lifespan,
              description='Simulated sidewalk delivery fleet on a real OpenStreetMap street network, with an AI agent in every robot.')


@app.middleware('http')
async def always_fresh_page(request, call_next):
    # Browsers must re-check the dashboard page so a rebuilt frontend shows up on a normal reload.
    response = await call_next(request)
    if response.headers.get('content-type', '').startswith('text/html'):
        response.headers['Cache-Control'] = 'no-cache'
    return response


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse(status_code=409, content={'detail': str(exc)})


def state():
    return {**fleet.snapshot(), 'ai': llm.status()}


@app.get('/api/map')
def city_map():
    return {**fleet.city.public(), 'hazard_kinds': {k: {'label': v['label']} for k, v in KINDS.items()}}


@app.get('/api/state')
def get_state():
    with fleet.lock:
        return state()


@app.post('/api/mission/sample')
def sample():
    with fleet.lock:
        fleet.load_sample()
        return state()


@app.post('/api/orders')
def add_order(body: OrderIn):
    with fleet.lock:
        oid = fleet.add_order(body.pickup, body.dropoff, body.priority)
        fleet.event(f'Order #{oid} received', f"{fleet.place(body.pickup)['name']} → {fleet.place(body.dropoff)['name']}")
        fleet.dispatch(f'Order #{oid} received')
        return state()


@app.post('/api/places')
def add_place(body: PlaceIn):
    with fleet.lock:
        fleet.add_place(body.lat, body.lon, body.name.strip(), body.role)
        return state()


@app.patch('/api/places/{pid}')
def update_place(pid: str, body: PlaceUpdate):
    with fleet.lock:
        fleet.update_place(pid, body.name.strip() if body.name else None, body.role)
        return state()


@app.delete('/api/places/{pid}')
def remove_place(pid: str):
    with fleet.lock:
        fleet.remove_place(pid)
        return state()


@app.post('/api/orders/{oid}/priority')
def priority(oid: int, body: PriorityIn):
    with fleet.lock:
        fleet.set_priority(oid, body.priority)
        return state()


@app.post('/api/dispatch')
def redispatch():
    with fleet.lock:
        fleet.dispatch('Operator asked to re-optimise')
        return state()


@app.post('/api/simulation/start')
def start():
    with fleet.lock:
        fleet.start()
        return state()


@app.post('/api/simulation/pause')
def pause():
    with fleet.lock:
        fleet.pause()
        return state()


@app.post('/api/simulation/speed')
def speed(body: SpeedIn):
    with fleet.lock:
        fleet.set_speed(body.speed)
        return state()


@app.post('/api/simulation/reset')
def reset():
    with fleet.lock:
        fleet.reset()
        return state()


@app.post('/api/hazards')
def add_hazard(body: HazardIn):
    with fleet.lock:
        fleet.add_hazard(body.lat, body.lon, body.kind, body.announced)
        return state()


@app.delete('/api/hazards/{hid}')
def clear_hazard(hid: int):
    with fleet.lock:
        fleet.clear_hazard(hid)
        return state()


@app.post('/api/robots/{rid}/battery')
def battery(rid: str, body: BatteryIn):
    with fleet.lock:
        fleet.set_battery(rid, body.level)
        return state()


@app.post('/api/robots/{rid}/mission')
def plan_mission(rid: str, body: MissionIn):
    for n, w in enumerate(body.waypoints, 1):
        if not w.place and (w.lat is None or w.lon is None):
            raise ValueError(f'Point {n} needs a place or a map position.')
    with fleet.lock:
        fleet.plan_mission(rid, [w.model_dump() for w in body.waypoints])
        return state()


@app.post('/api/robots/{rid}/mission/start')
def start_mission(rid: str):
    with fleet.lock:
        fleet.start_mission(rid)
        return state()


@app.delete('/api/robots/{rid}/mission')
def cancel_mission(rid: str):
    with fleet.lock:
        fleet.cancel_mission(rid)
        return state()


@app.post('/api/ai/chat', response_model=ChatResponse)
def chat(body: Chat):
    if not llm.available:
        return ChatResponse(available=False, message=llm.reason, model=llm.model)
    with fleet.lock:
        snap = fleet.snapshot()
    try:
        reply = copilot.ask(llm, body.message, fleet, snap)
    except Exception:
        return ChatResponse(available=False, model=llm.model,
                            message='The AI request failed or returned invalid instructions. No changes applied.')
    with fleet.lock:
        try:
            applied = copilot.apply(reply, fleet)
        except ValueError as exc:
            return ChatResponse(available=True, model=llm.model, message=f'{reply.explanation}\n\nNot applied: {exc}')
    return ChatResponse(available=True, message=reply.explanation, applied=applied, model=llm.model)


# Single-server demo after `npm run build`.
dist = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
if dist.is_dir():
    app.mount('/', StaticFiles(directory=dist, html=True), name='dashboard')
