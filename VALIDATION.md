# Validation record — October 24, 2026

## Automated
- **27 backend tests pass** (Python 3.13, locked dependencies). They cover:
  - the street graph, routing and click snapping;
  - dispatcher constraints (pickup before drop-off, capacity, parcels on board, urgent first, unreachable orders);
  - robot behaviour (hidden obstacles, stopping to think, waiting, slow pass, bumper, city notices, low battery, safety reflex);
  - the AI path with a scripted model: decisions applied and shared, invalid or failed answers falling back, no ground-truth fields in the prompt, memory across decisions;
  - the backup-model chain, operator routes, custom points, and API validation.
- **TypeScript check and Vite production build pass.**
- **Randomised stress run:** 12 missions of 9 orders each, with random obstacles (some permanent city notices), a low-battery event and a mid-mission urgent change. 10 completed; the other 2 waited only for orders that permanent closures had made unreachable. This run found three bugs, all fixed:
  - waiting orders that were never retried;
  - stale private notes that stranded a robot;
  - endless re-checks of a permanent closure (a repeated report is now trusted longer).

## Live AI (Google GenAI API)
- **Gemma 4 26B** (`gemma-4-26b-a4b-it`) made correct live decisions in about 4 s each:
  - detour around a van misclassified as "person";
  - slow pass of a scooter with a 1.16 m gap;
  - return to hub on low battery, releasing its unpicked orders.
- Three robots asking at once: no rate-limit errors, and the other robots kept driving.
- During a period when Google returned 500 and 503 errors and timeouts for Gemma, the **backup chain** answered instead: Gemini 3.1 Flash Lite and Gemini 3 Flash. Decisions stayed correct, and each was labelled with the model that answered.
- Models sometimes added stray tokens around their JSON; the tolerant parser handles this (covered by a test).
- Dispatcher copilot: correct explanations from the robots' own reasoning. Single commands work: urgent order, street closure, new order. Instructions that combine several changes can contain an invented place; validation rejects the whole message.

## Browser (headless Chrome)
- Dashboard at desktop width and at a 390 px phone viewport: no horizontal overflow, and the page starts at the top.
- 3D city view (MapLibre + OpenFreeMap): buildings, robot labels and the follow camera render with no console errors.
- Click-throughs with no console errors:
  - **Route:** select robot → New route → points → rename and reorder → Save → Start.
  - **Points:** add, edit, protected delete, Clear all.

## Live mission (sample, 6 orders, 4 robots, Le Marais)
- OR-Tools plan 11.40 km vs greedy 12.29 km (−7 %); last delivery after 3.88 km vs 5.28 km (−26 %).
- Hidden roadworks: seen at 30–35 m, the robot stopped, detoured and shared them, and the server re-routed another robot from that report.

## Not covered
- No physical robot or real camera images: robots, sensors, battery and speed are simulated.
- One in-memory mission, one backend process; OR-Tools search is time-bounded.
