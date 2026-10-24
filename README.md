# RouteMind AI

A working, local warehouse delivery simulator: React/TypeScript dashboard, FastAPI simulation clock, NetworkX A* paths, Google OR-Tools sequencing, and an optional Gemma 4 coordination assistant.

## Start on Windows (PowerShell)

Requirements: Python 3.11+ and Node.js 20.19+ (or Node 22). Tested here on Python 3.13. Use a **single backend worker**: mission state is shared in memory and resets on restart.

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
Copy-Item .env.example .env
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. FastAPI serves the built dashboard and API together. Keep the terminal running; Ctrl+C stops it. No API key is required for manual simulation. `requirements.txt` contains compatible dependency ranges; `requirements-lock.txt` captures the tested resolved versions. The npm lockfile is committed as a project artifact.

For frontend hot reload, keep FastAPI running and use a second terminal:

```powershell
cd frontend
npm.cmd run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to port 8000. After changing Python code, restart FastAPI or add `--reload` for local development. Do not use multiple workers.

macOS/Linux equivalent: `python3 -m venv .venv`, `.venv/bin/python -m pip install -r backend/requirements-lock.txt`, `cp .env.example .env`, then the same npm commands (without `.cmd`) and `.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`.

## Jury demonstration

1. Click **Load sample mission** in the delivery queue. Arrival order is C → A → D → B → E. Five stations are visible initially. Add Delivery can activate F–J for up to ten stations.
2. Click **Optimize route**. On the untouched sample grid, the baseline is **122 m** and the heuristic result is **62 m**, a **49.2%** reduction. Both include return to the dock. Tied visit orders can differ.
3. Click **Start robot**. The server advances one actual grid edge every 0.6 seconds. The map animates the server's traversed coordinate history; it does not invent motion.
4. Click **Edit obstacles** and block an unoccupied cell on the dashed route ahead of the robot. This reliably demonstrates a detour. Alternatively, **Block corridor A–C** closes the explicitly marked cross-aisle (x=9..15, y=8). A corridor outside the current path can leave distance unchanged; the UI reports actual values.
5. Click **Urgent delivery** (D if outstanding, otherwise the first pending request), or click a station's Normal priority badge. The robot retains its current cell and completed deliveries while the remaining route changes. Try **Pause robot**, **Resume robot**, and **Low battery** too.
6. If Gemma is configured, enter **“Deliver medical equipment to station D immediately. Station B can wait, and corridor A-C is blocked.”** while D and B are still pending. For an AI demonstration with enough time, pause the robot before typing. Without an API key, chat explicitly reports unavailability; use the manual controls.
7. Wait for all deliveries and the return to dock. Inspect analytics and click **Export mission** to download a JSON report. Reset clears the mission and restores the dock/battery/map.

When adding a new task during movement, use a station not already requested. Completed deliveries cannot be overwritten; there is one delivery per station per mission.

## Gemma configuration and verification

Edit `.env` locally (never commit it):

```dotenv
GEMINI_API_KEY=your_key_here
GEMMA_MODEL=gemma-4-26b-a4b-it
```

Restart the backend. Google's official documentation lists `gemma-4-26b-a4b-it` and `gemma-4-31b-it`: https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api (checked October 24, 2026). The backend calls `client.models.list()` and enables AI only if the configured Gemma 4 identifier is available to that API account. A documented model name is not proof of account access.

The assistant receives current simulation state plus the current user message. It produces a constrained JSON schema using the Google GenAI SDK. For deployments rejecting structured output, it falls back to JSON prompting; **both paths undergo identical Pydantic validation**. Only validated station requests, priorities, explicit ordering constraints, and obstacle changes can be applied. Updates are atomic, using the latest robot position when the model returns. Commands conflicting with completed tasks, occupied cells, or precedence are rejected. Invalid JSON or service failures cause no state changes. Questions and hypotheticals are instructed to return explanations with empty action arrays. Chat is stateless between requests, but every request receives fresh mission state.

**No real API key was provided during development. Live Gemma generation has not been tested.** The unavailable-state behavior and validated command application are covered by tests with controlled model outputs. No responses are presented as Gemma output when AI is unavailable.

## Routing and simulation design

- Deterministic 25 × 17 grid with static racks, boundary walls, ten known station positions, and a dock. A–E are displayed by default; requested F–J appear on the map.
- NetworkX A* uses Manhattan distance over four-neighbor walkable cells. Every route matrix entry is the length of an actual A* path, not straight-line distance.
- OR-Tools uses a single vehicle, fixed current start, and mandatory dock return. A visit-rank dimension enforces urgent-before-normal and explicit before/after constraints. Cycles are rejected. Local search has a 180 ms budget; **global optimality is not guaranteed**.
- Traversing a station is not a delivery unless it is the scheduled stop. This preserves priority/precedence semantics even when a path passes another station.
- Unreachable tasks remain pending, are identified by name, and are excluded from both distances in the comparison. Reachable tasks can proceed. An unreachable urgent task cannot be served first; the event timeline explains this. If the dock is disconnected, the robot stops safely at its current cell.
- All mutations and ticks use one engine lock. Replanning happens at the current grid cell; paused missions remain paused. Invalid commands roll back completely. Valid disconnecting obstacles are accepted and trigger a safety stop.
- Battery is a **simulation model**: 0.18 percentage points per edge. Below 20%, or when a planned trip lacks a 5-point reserve, the robot returns to the dock. It charges 5 points per tick and automatically replans outstanding tasks at 100%. Insufficient energy to reach the dock triggers a stop rather than teleportation.
- Distances are simulated metres (1 m/cell); travel ETA is remaining edges × 0.6 seconds, excluding charging and inaccessible tasks. Latest-plan baseline/optimized metrics compare the same reachable outstanding stops from the same start and current map. The before/after card compares old remaining distance with the newly computed remaining distance; priorities and obstacles can increase it. Mission distance counts all traveled edges, including recharge trips.
- Frontend polls the authoritative backend; the simulation continues if the browser is closed. No authentication, durable storage, physical robot integration, Docker, or external deployment is included.

## Tests and build

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm.cmd run build
```

Tests cover shortest A* paths, detours, unreachable destinations, route traversal and distance consistency, comparison with an exact oracle for the five-stop fixture, urgent/order constraints, ten stations, dynamic replanning without teleportation or delivery loss, paused/charging state retention, battery recovery, dock disconnection, recorded movement history, API validation, AI unavailability, and atomic AI command rejection.

If a Windows sandbox hangs at asyncio initialization, run the test/server commands in a normal local terminal; the test client needs an internal loopback socket.

## API and files

Interactive API schemas: **http://127.0.0.1:8000/docs**.

| Endpoint | Purpose |
|---|---|
| GET `/api/map`, `/api/state`, `/api/analytics` | Warehouse definition, authoritative state, measured simulation metrics |
| POST `/api/mission/sample` | Load the built-in mission into an empty queue |
| POST `/api/deliveries` | `{ "station": "C", "priority": "normal" }` |
| POST `/api/optimize` | Recalculate outstanding tasks |
| POST `/api/simulation/start`, `/pause`, `/reset` | Start/resume, pause, or reset |
| POST `/api/obstacles` | `{ "cell": [12, 8], "blocked": true }` |
| POST `/api/corridors` | `{ "corridor": "A-C", "blocked": true }` |
| POST `/api/events/urgent` | `{ "station": "D" }` |
| POST `/api/events/low-battery` | Simulate 15% charge |
| POST `/api/ai/chat` | `{ "message": "Prioritize delivery C." }` |

`backend/planner.py` owns A* and OR-Tools; `engine.py` owns missions and movement; `ai.py` owns the Google SDK; `models.py` owns validation; `main.py` owns HTTP and the clock. `frontend/src/App.tsx` and `style.css` implement the responsive dashboard and SVG map.
