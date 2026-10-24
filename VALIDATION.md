# Validation record — October 24, 2026 (city map + onboard agents)

- Fetched Le Marais, Paris from OpenStreetMap: 397 intersections, 547 street segments, 33 km, 8 pickup and
  12 drop-off places. Saved as `backend/data/city.json`.
- **22 backend tests passed**, run repeatedly (Python 3.13.7, locked dependencies).
- Randomised stress run: 12 missions of 9 orders each, with random obstacles (some permanent city notices),
  a low-battery event and a mid-mission urgent change. 10 completed; the other 2 waited only for an order
  that permanent closures fully cut off. That is correct: the order stays queued and the reason is logged.
  This run found and fixed three bugs: waiting orders that were never retried, stale private notes that
  stranded a robot, and endless re-checks of a permanent closure (repeat reports are now trusted longer).
- **TypeScript check and Vite production build passed.**
- Ran the FastAPI server and dashboard on port 8000. Loaded the sample mission. OR-Tools plan 11.40 km vs
  greedy 12.29 km (−7 %); last delivery after 3.88 km vs 5.28 km (−26 %); three robots used, one in reserve.
- Placed hidden obstacles through the API during a live run:
  - **Roadworks:** the robot saw them at 30–35 m, stopped, detoured (+34 to +171 m depending on position)
    and shared them; the server re-routed another robot from that report.
  - **Small obstacle:** the robot passed slowly ("passed safely").
  - **City-notice closure:** robots re-routed without seeing it.
- Checked the asynchronous AI path with a slow scripted model (1.2 s per call). The robot stayed in
  "thinking" in a background thread while the other robots kept moving; the decision was applied with
  its latency.
- Checked the dashboard in headless Chrome at desktop width and at a 390 px phone viewport: no
  horizontal overflow, and the page starts at the top.

**Not tested:** live Gemma generation, because no API key was available. Without a key, every decision is
labelled "Reflex rules" and the copilot reports that the AI is unavailable.

Limitations: one in-memory mission, one backend process, simulated sensors/battery/speed, heuristic
OR-Tools search, no physical robot.
