# Star Battles Vector Prototype

A minimalist, vector-rendered space combat sandbox inspired by arcade space dogfighters. Built with Python 3.10+, Pygame, and deterministic fixed-step simulation suitable for future expansion.

## Features (Milestone 1)

- Fixed 60 Hz simulation loop decoupled from rendering.
- Scene router with title screen and sandbox skirmish.
- Data-driven ship, weapon, and item definitions (JSON under `game/assets/data`).
- Interceptor vs. assault target demo: throttle, boost, strafe, roll, and chase camera with FOV scaling.
- Hitscan cannons, missile launcher with lock-on, soft target selection, PD interception.
- DRADIS radar widget, HUD target panel, power/boost meters, debug overlay (F3).
- Sector map overlay with light-year ranges, Tylium costs, and FTL charging/cooldowns.
- Mining nodes with scan-to-reveal, beam stability mini-game, and Tylium/Titanium/Water payouts.
- Unit tests for combat formulas, FTL cost/charge helpers, and mining yield math.

## Quickstart

```bash
python -m venv .venv
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

If Pygame requests additional system packages (SDL dependencies), install them via your platform package manager.

## Controls

- **Mouse**: Pitch/Yaw
- **W/S**: Forward throttle up/down
- **A/D**: Horizontal strafe
- **Q/E**: Vertical strafe
- **Z/C**: Roll
- **Space**: Boost (drains power)
- **Ctrl**: Brake
- **Left Mouse**: Primary cannons
- **Right Mouse**: Missile launcher (requires lock)
- **F**: Hold to freelook the camera without steering the ship
- **T**: Target nearest hostile
- **R**: Cycle targets
- **G**: Toggle PD (auto in this milestone)
- **F3**: Debug overlay
- **V**: Hold to scan for nearby mining nodes
- **B**: Toggle mining beam when near a discovered node
- **Shift**: Stabilize mining beam (prevents instability, boosts yield)
- **Esc**: Return to title

Distances are displayed in metres (km for large ranges); velocities in metres per second. DRADIS rings label metre/km scales.

## Testing

Unit tests use `pytest`:

```bash
pytest
```

## Performance tips

- Adjust `maxFps` and resolution in `settings.json`.
- Disable physics/weapon channel logging via the same file to reduce console noise.
- Toggle the debug overlay (F3) only when diagnosing performance—it incurs minimal cost but reduces clutter.

## JSON Structure Overview

- `game/assets/data/ships/*.json`: Frame stats, slots, and hardpoints.
- `game/assets/data/weapons/*.json`: Weapon class, damage, accuracy, gimbals.
- `game/assets/data/items/*.json`: Module definitions (PD, Jammer, ECCM).
- `game/assets/config/gameplay.json`: Tunables such as armor floor and lock rates (read for balancing).

## Next Steps (Milestone 2 Goals)

- Implement Escort/Line ship roster, expanded AI behaviours.
- Add sector FTL map (5–7 systems) with range checks and charging rules.
- Introduce mining loop with nodes, stability mini-game, and resource handling.
- Build fitting UI for module management and stat inspection.

