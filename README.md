# T.R.I.A.G.E. — Thermal Reaction Inference & Anomaly Grading Engine

**2026 NASA Space Apps Challenge — "Flame in Free-Fall"**

An interactive, AI-powered Digital Twin dashboard that summarizes, ranks, and
interprets historical NASA microgravity combustion experiments (ACME s-Flame /
Coflow, Saffire) alongside a custom high-speed physics simulation engine —
delivering fire-safety insights for Moon and Mars missions.

> **AI disclosure (per NASA Space Apps rules):** This project was built with
> AI-assisted code generation and data curation (architecture, C++/Python/
> JavaScript scaffolding, documentation). All AI-generated content is
> acknowledged in this README and in the repository metadata. No AI-generated
> imagery or audio is used in the core deliverable; any demo-video voice-over
> (if produced) uses Azure Speech Neural TTS and is disclosed as such.

---

## Quick Start (judges — 3 steps)

```bash
# 1. Backend (Python 3.12+): WebSocket server + simulation + AI pipeline
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/python/server.py          # ws://0.0.0.0:8765

# 2. Frontend (Node 20+)
cd src/frontend && npm install && npm run dev  # http://localhost:5173

# 3. (Optional) Real C++ solver — falls back to the NumPy reference mock
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
```

Or one command with Docker: `docker compose up --build` (serves everything).

## The walkthrough (three tabs)

The dashboard is organized in three tabs (the page background is a hexagon
mesh in the same accent color as the sliders):

1. **Tab 1 · Run & Calculations.** Pick a fuel preset (CH4/C2H4/C3H8/H2 —
   thermochemistry auto-populates from `src/shared/species_db.json`) or create
   your own **custom preset**: it persists on the backend
   (`data/custom_fuels.json`) and edits the same database variables (A, Ea,
   LHV, cp, k, D, reaction orders, soot tendency, …). Set O2%, ambient
   pressure, gravity mode (Zero-G / ISS Micro-G / Earth 1G / Mars / Moon) — or
   **custom gravity** with your own g magnitude and jitter — ignition energy,
   and the **iteration count**. The solver step Δt runs from 0.001 s up to
   1 s; run length = iterations x Δt (end time is gone). Every slider also
   accepts a directly typed value: click the number and type. Press **Run
   simulation** and watch the **Iteration Graph** and **Active Calculations**
   trace fill with per-step scalars as the solver computes.

2. **Tab 2 · Fire Visuals & Analysis.** The flame renders in a compact left
   rail as a **3D volumetric view** (three.js raymarched emission-absorption
   shader; drag to orbit, wheel to zoom) with a flat 2D heatmap toggle, time
   scrubber and final-run stats. Directly beneath it, the small **Jev
   Experiment Comparison** panel scores the run against the nearest NASA
   ground truth with field-level agreement percentages (peak T, flame radius,
   O2, pressure) and a dense tier-1 verdict grid — all visible without
   scrolling. The center and right of the tab belong to the big **Tier 2
   report** panel (Azure AI Foundry, gated to top-1% anomalies or an explicit
   user click), which produces a Markdown fire-safety diagnostic grounded in
   the 2015 *ISS Combustion Science Researcher's Guide* and the Apollo 1 /
   Apollo 13 / Mir 1997 incident history, with Moon/Mars ECLSS
   recommendations.

3. **Tab 3 · More Graphs.** Burn curves vs NASA PSI flight telemetry, soot
   index & mean temperature, fuel burned fraction, buoyancy kinetic energy,
   the angle-averaged radial temperature profile of the current frame, and
   rule-based **suggestions** read off the run's own numbers.

## Architecture

```
src/
├── cpp/          # 2D laminar reaction-diffusion-advection solver (ADI + Thomas)
│                 #   → compiled to triage_core.so via pybind11 (slot-in point)
├── python/       # WebSocket server, NASA PSI S3 ingest, two-tier AI pipeline
├── frontend/    # React + D3 digital-twin dashboard (Vite)
└── shared/      # species_db.json + constants.json (single source of truth)
```

**3D view disclosure:** the solver field is strictly 2D (`[ny][nx]` K grid);
the 3D view revolves it about the flame axis (axisymmetric assumption) and
raymarches the resulting volume. It is a visualization transform, not a 3D
physics solver — disclosed on-screen via the "axisymmetric revolve" chip.

**Solver seam contract** — every consumer speaks `SimConfig`/`SimResult`
(`src/python/schema.py`), never the .so directly. If `import triage_core`
fails, `sim_bridge.py` falls back to a NumPy reference mock with identical
outputs, so the entire pipeline (ingest → triage → UI) is testable offline.
The real ADI/Thomas C++ solver slots in without touching any other layer.

**Key physics modes**

| Mode | Physics |
|------|---------|
| Zero-G | Diffusion-dominated spherical flame (ISS-like) |
| ISS Micro-G | g-jitter 1e-6…1e-3 g — slight asymmetry |
| Earth 1G | Buoyant teardrop plume |
| Saffire | Forced ventilation airflow U_in (fan-driven spread) |

## Compliance & data sources

- **NASA PSI Data Repository** (Combustion): anonymous S3 ingest, lightweight
  telemetry only (`.csv`/`.dat`/`.txt`); multi-TB video archives skipped.
  Scoped to gaseous-fuel experiments (ACME s-Flame/Coflow, Saffire airflow).
- **Wolf Amendment**: zero calls to any Chinese API endpoints; all external
  inference routes through US-hosted infrastructure (NanoGPT, Azure US
  regions) or local fallbacks.
- **Single-step Arrhenius kinetics** are a reduced approximation — documented
  in-app and here. A predictive simulator would use fuel-specific mechanisms.

## Environment variables (`.env`, see `.env.example`)

- `NANOGPT_API_KEY` — Tier 1 bulk triage (typesafe/jev-latest)
- `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` / deployment — Tier 2
  synthesis (gated; trial TPM quota protected)
- All optional: every AI path has a deterministic local fallback so the demo
  never depends on network availability.

## Repository status

This scaffold was produced inside the competition window; the C++ ADI/Thomas
solver is the primary remaining engineering task (see `PLAN.md`). All other
layers — WebSocket backend, S3 ingest, two-tier AI pipeline, React/D3
dashboard — are functional end-to-end against the mock solver.