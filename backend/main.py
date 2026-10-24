import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .engine import Engine, TICK_SECONDS
from .planner import WIDTH, HEIGHT, WALLS, SHELVES, STATIONS, BASE, CORRIDORS, PlanningError
from .models import Delivery, Obstacle, Corridor, Chat, ChatResponse, StateResponse, MapResponse, AnalyticsResponse
from .ai import Coordinator

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
engine = Engine()
coordinator = Coordinator()


async def ticker():
    while True:
        await asyncio.sleep(TICK_SECONDS)
        with engine.lock:
            engine.tick()


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(ticker())
    discovery = asyncio.create_task(asyncio.to_thread(coordinator.connect))
    yield
    task.cancel()
    discovery.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title='RouteMind AI', version='1.0.0', lifespan=lifespan,
              description='Single-process, in-memory robot simulation. Distances are simulated grid metres.')


@app.exception_handler(PlanningError)
async def planning_error(request, exc):
    return JSONResponse(status_code=409, content={'detail': str(exc)})


@app.get('/api/map', response_model=MapResponse)
def warehouse():
    return {'width': WIDTH, 'height': HEIGHT, 'walls': sorted(WALLS), 'shelves': SHELVES,
            'stations': STATIONS, 'base': BASE, 'corridors': CORRIDORS, 'metres_per_cell': 1,
            'seconds_per_step': TICK_SECONDS}


@app.get('/api/state', response_model=StateResponse)
def state():
    with engine.lock:
        return {**engine.snapshot(), 'ai': coordinator.status()}


@app.get('/api/analytics', response_model=AnalyticsResponse)
def analytics():
    with engine.lock:
        return {**engine.snapshot()['analytics'], 'battery': round(engine.battery, 1)}


@app.post('/api/deliveries', response_model=StateResponse)
def delivery(body: Delivery):
    with engine.lock:
        engine.transaction(lambda: engine.add(body.station, body.priority), f'Delivery {body.station} added')
        return state()


@app.post('/api/mission/sample', response_model=StateResponse)
def sample():
    with engine.lock:
        if engine.deliveries:
            raise PlanningError('Reset the current mission before loading a sample.')
        engine.transaction(lambda: [engine.add(s) for s in ['C', 'A', 'D', 'B', 'E']], 'Sample mission loaded')
        return state()


@app.post('/api/optimize', response_model=StateResponse)
def optimize():
    with engine.lock:
        engine.replan()
        return state()


@app.post('/api/simulation/start', response_model=StateResponse)
def start():
    with engine.lock:
        engine.start()
        return state()


@app.post('/api/simulation/pause', response_model=StateResponse)
def pause():
    with engine.lock:
        if engine.status != 'running':
            raise PlanningError('Only a moving robot can be paused.')
        engine.status = 'paused'
        engine.event('Robot paused', 'Position and remaining route preserved.')
        return state()


@app.post('/api/simulation/reset', response_model=StateResponse)
def reset():
    with engine.lock:
        engine.reset()
        return state()


@app.post('/api/obstacles', response_model=StateResponse)
def obstacle(body: Obstacle):
    with engine.lock:
        engine.transaction(lambda: engine.obstacle(body.cell, body.blocked), 'Corridor blocked' if body.blocked else 'Corridor reopened')
        return state()


@app.post('/api/corridors', response_model=StateResponse)
def corridor(body: Corridor):
    with engine.lock:
        engine.transaction(lambda: [engine.obstacle(c, body.blocked) for c in CORRIDORS[body.corridor]],
                           f'Corridor {body.corridor} '+('blocked' if body.blocked else 'reopened'))
        return state()


@app.post('/api/events/urgent', response_model=StateResponse)
def urgent(body: Delivery):
    with engine.lock:
        engine.transaction(lambda: engine.priority(body.station, 'urgent'), f'Urgent delivery {body.station} prioritized')
        return state()


@app.post('/api/events/low-battery', response_model=StateResponse)
def low_battery():
    with engine.lock:
        engine.transaction(lambda: setattr(engine, 'battery', 15.0), 'Low battery event')
        return state()


@app.post('/api/ai/chat', response_model=ChatResponse)
def chat(body: Chat):
    if not coordinator.available:
        return ChatResponse(available=False, message=coordinator.reason, model=coordinator.model)
    with engine.lock:
        snapshot = engine.snapshot()
    try:
        instructions = coordinator.ask(body.message, snapshot)
    except Exception:
        return ChatResponse(available=False, message='Gemma request failed or returned invalid instructions. No changes applied. Manual controls remain available.', model=coordinator.model)
    changed = bool(instructions.deliveries or instructions.obstacles or instructions.corridors or instructions.precedence)
    with engine.lock:
        def apply():
            for d in instructions.deliveries:
                engine.priority(d.station, d.priority)
            for o in instructions.obstacles:
                engine.obstacle(o.cell, o.blocked)
            for c in instructions.corridors:
                for cell in CORRIDORS[c.corridor]:
                    engine.obstacle(cell, c.blocked)
            for order in instructions.precedence:
                pending = {d['station'] for d in engine.pending()}
                if order.before not in pending or order.after not in pending:
                    raise PlanningError('Ordering requires two pending delivery stations.')
                engine.precedence.append((order.before, order.after))
        if changed:
            engine.transaction(apply, 'Gemma instructions validated · route recalculated')
        detail = ''
        if changed:
            detail = f" Backend applied changes: {engine.snapshot()['analytics']['remaining']} m remaining; status {engine.status}."
        return ChatResponse(available=True, message=instructions.explanation+detail, applied=changed, model=coordinator.model)


# Optional single-server demo after `npm run build`.
dist = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
if dist.is_dir():
    app.mount('/', StaticFiles(directory=dist, html=True), name='dashboard')
