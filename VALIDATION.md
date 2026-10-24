# Validation record — October 24, 2026

- Installed Python and frontend dependencies; saved tested Python versions and the npm lockfile.
- **14 backend tests passed.** FastAPI's Windows test client required running outside the restricted sandbox because its internal asyncio loopback socket was blocked inside it.
- **TypeScript check and Vite production build passed.**
- Started FastAPI and Vite. Verified the single-server production URL on port 8000 responds HTTP 200.
- Browser-tested the sample mission: **122 m baseline, 62 m optimized, 49.2% reduction**.
- Started the robot, observed real position updates and delivery completion, and applied a named corridor closure.
- Blocked cell **(20, 13)** ahead of the active robot: remaining route changed **45 m → 47 m**. Earlier completed deliveries remained completed; the robot subsequently completed station D.
- Verified pause/resume, manual urgent priority D, and low-battery return to the dock. Observed charging and automatic mission resumption; all five deliveries completed.
- Verified chat shows **SYSTEM · AI UNAVAILABLE** with no fabricated model response when the API key is absent.
- Tested ten-station support, impossible paths, conflicting priorities, atomic rejected commands, and coordinate-by-coordinate traversal in automated tests.

Gemma's model identifier was checked against Google's official documentation, but **live Gemma generation was not tested with a real key**. AI application tests use controlled model results. A configured account is checked via model discovery at startup.

Limitations: one in-memory mission, one backend process, simulated battery/speed/distance, and heuristic OR-Tools search. These are not physical robot measurements. Browser actions were verified in the in-app browser at its available viewport; no separate mobile-device test was performed.
