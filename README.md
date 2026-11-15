# T.R.I.A.G.E. — Thermal Reaction Inference & Anomaly Grading Engine

**2026 NASA Space Apps Challenge — "Flame in Free-Fall"**

An interactive, AI-powered Digital Twin dashboard that summarizes, ranks, and
interprets historical NASA microgravity combustion experiments (ACME s-Flame /
Coflow, Saffire) alongside a custom **1D spherical finite-volume combustion
solver** — delivering fire-safety insights for Moon and Mars missions.

The solver implements the five coupled equations in the architecture
specification: continuity, equation of state, momentum consistency, species
transport (with the correction velocity), and sensible-enthalpy energy
transport, plus the Arrhenius reaction-rate and chemical-heat-release
calculators. A NumPy reference implementation and a pybind11 C++ module
(`triage_core`) share the same seam; the dashboard shows which one is active.
Open issues in the source document are implemented literally and tracked in
the internal revision tracker (kept outside the distributed repository); the
as-built notes are in the internal solver notes.

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

# 3. (Optional) C++ solver module — falls back to the NumPy reference
cmake -B build -DCMAKE_BUILD_TYPE=Release \
  -Dpybind11_DIR="$($PWD/.venv/bin/python -m pybind11 --cmakedir)"
cmake --build build -j
# sim_bridge.py auto-loads build/triage_core*.so when present.

# 4. Tests (fidelity + grid/transport + C++/Python parity)
PYTHONPATH=src/python .venv/bin/python -m pytest -q tests/
```

Or one command with Docker: `docker compose up --build` (serves everything).

## The walkthrough (three tabs)

The dashboard is organized in three tabs (the page background is a hexagon
mesh in the same accent color as the sliders):

1. **Tab 1 · Run & Calculations.** Pick a fuel preset (CH4/C2H4/C3H8/H2 —
   thermochemistry auto-populates from `src/shared/species_db.json` and
   `src/shared/reactions.json`) or create your own **custom preset**: it
   persists on the backend (`data/custom_fuels.json`) and edits the same
   database variables (A, Ea, LHV, cp, k, D, reaction orders, formula, soot
   tendency, …). Set O2%, ambient pressure, gravity mode (Zero-G / ISS Micro-G
   / Earth 1G / Mars / Moon) — or **custom gravity** — **mixing mode**
   (premixed vs fuel-core/oxidizer-shell), equivalence ratio, oxidizer,
   **mass flow rate**, ignition energy, and the **iteration count**. The
   spherical solver runs on `r_min … r_max` with `Nᵣ` radial cells; `nx × ny`
   is the display grid. The solver step Δt runs from 0.001 s up to 1 s; run
   length = iterations x Δt. Every slider also accepts a directly typed value:
   click the number and type. Press **Run simulation** and watch the
   **Iteration Graph** and **Active Calculations** trace fill with per-step
   scalars as the solver computes.

2. **Tab 2 · Fire Visuals & Analysis.** The 1D spherical `T(r)` field is
   painted onto a centered display grid and renders in a compact left rail as a
   **3D volumetric view** (three.js raymarched emission-absorption shader; drag
   to orbit, wheel to zoom) with a flat 2D heatmap toggle, time scrubber and
   run stats. Directly beneath it, the small **Jev
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
   the angle-averaged radial temperature profile of the current frame, the
   solver's **radial T/q̇** and **species** profiles, a **T(r,t)** heatmap from
   the saved radial snapshots, and rule-based **suggestions** read off the
   run's own numbers (including honest solver diagnostics such as mass-budget
   drift, which is tracked in the internal revision tracker).

## Architecture

```
src/
├── cpp/          # 1D spherical finite-volume solver (thomas.cpp, solver_core.cpp,
│                 #   bindings.cpp) → triage_core.so via pybind11
├── python/       # WebSocket server, NASA PSI S3 ingest, two-tier AI pipeline,
│                 #   solver1d/ NumPy reference (grid/properties/chemistry/transport)
├── frontend/    # React + D3 digital-twin dashboard (Vite)
└── shared/      # species_db.json + reactions.json + constants.json
```

`src/python/solver1d/` is the Python reference implementation of the same
equations. `sim_bridge.py` prefers `build/triage_core*.so` and falls back to the
reference, so the dashboard works with or without a compiler.

**3D view disclosure:** the solver field is strictly **1D spherical radial**
(`Nr` cells, `r_min … r_max`). `T(r)` is painted onto a centered `[ny][nx]`
display grid, and the 3D view revolves that centered field about the flame
axis. Because the painted field is radial, the revolve produces a true
spherical field; it is a visualization transform, not a 3D physics solver.
Disclosed on-screen via the "1D spherical revolve" chip.

**Solver seam contract** — every consumer speaks `SimConfig`/`SimResult`
(`src/python/schema.py`), never the .so directly. The C++ module exposes
`run_simulation(config: dict, mechanism: dict) -> dict`; `mechanism` is the
resolved species/reaction payload from `mechanism.mechanism_payload()`.
If `import triage_core` fails, `sim_bridge.py` runs the NumPy reference in
`src/python/solver1d/` with the same equations and output shape, so the entire
pipeline (ingest → triage → UI) is testable offline. C++/Python parity is
covered by `tests/test_parity.py` (≤0.73 K temperature difference on the default
256-cell run).

**Key physics modes**

| Mode | Physics |
|------|---------|
| Zero-G | Diffusion-dominated spherical flame; `u=0` when `ṁ=0` (continuity as written) |
| ISS Micro-G | g-jitter mapped to an effective radial `g_r` |
| Earth / Mars / Moon | Gravity enters only as an effective radial `g_r`; the 1D model cannot resolve a transverse buoyant teardrop (R12) |
| Mass-flow inlet | `u = ṁ/(4πr²ρ)` at the inner radial boundary |
| Mixing | Premixed fuel+oxidizer, or a fuel-core / oxidizer-shell non-premixed profile |

The legacy `inlet_velocity_ms` control is retained in the schema for the PSI
comparison payload but is not used by the spherical solver (R4).

## Compliance & data sources

- **NASA PSI Data Repository** (Combustion): anonymous S3 ingest, lightweight
  telemetry only (`.csv`/`.dat`/`.txt`); multi-TB video archives skipped.
  Scoped to gaseous-fuel experiments (ACME s-Flame/Coflow, Saffire airflow).
- **Species/reaction data**: NASA-7 thermochemistry and transport reference
  values are curated from US public sources (NASA Glenn, Burcat, NIST). C3H8
  currently uses a constant `cp`; transport uses power-law correlations rather
  than full Chapman-Enskog (R8). The source document's open physical/mathematical
  issues are implemented as written and tracked in the internal revision
  tracker.
- **Wolf Amendment**: zero calls to any Chinese API endpoints; all external
  inference routes through US-hosted infrastructure (NanoGPT, Azure US
  regions) or local fallbacks.
- **Single-step Arrhenius kinetics** are a reduced approximation — documented
  in-app and here. A predictive simulator would use fuel-specific mechanisms.
  The reaction-rate constant is not yet calibrated to the preset laminar flame
  speed (R6/R20).

## Environment variables (`.env`, see `.env.example`)

- `NANOGPT_API_KEY` — Tier 1 bulk triage (typesafe/jev-latest)
- `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` / deployment — Tier 2
  synthesis (gated; trial TPM quota protected)
- All optional: every AI path has a deterministic local fallback so the demo
  never depends on network availability.

## Repository status

The 1D spherical solver now exists in both forms — the NumPy reference
(`src/python/solver1d/`) and the pybind11 C++ module (`src/cpp/`, built into
`build/triage_core*.so`). The WebSocket backend, S3 ingest, two-tier AI
pipeline, React/D3 dashboard, parameter sweeps, custom fuels, Jev comparison,
and Tier-2 report are functional end-to-end against it. `pytest` covers
thermochemistry, grid/transport, solver behaviour, and C++/Python parity.

Remaining release work (see `PLAN.md`): PSI metadata join for real experiment
IDs, Docker end-to-end verification, demo video/pitch deck, and the revision
items in the internal revision tracker (which are intentionally deferred, not
silently fixed).