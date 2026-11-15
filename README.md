# T.R.I.A.G.E. — Thermal Reaction Inference & Anomaly Grading Engine

**2026 NASA Space Apps Challenge — "Flame in Free-Fall"**

An interactive, AI-powered Digital Twin dashboard that summarizes, ranks, and
interprets historical NASA microgravity combustion experiments (ACME s-Flame,
ACME Coflow, Saffire, FLEX) alongside a custom **1D spherical finite-volume
combustion solver** — delivering fire-safety insights for Moon and Mars
missions. Ground truth comes from the live NASA PSI repository API: the full
Combustion Science catalogue (24 investigations) plus per-test-point ACME
s-Flame telemetry reduced into `data/psi/`.

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

Or one command with Docker: `docker compose up --build`. This builds the
React SPA inside `Dockerfile.frontend`, serves it from nginx on
`http://localhost:8080`, and runs the Python/C++ backend on
`ws://localhost:8765`. No local `npm run build` is required. The `./data`
directory is mounted into the backend so curated PSI ground truth and custom
presets persist.

Refresh or inspect the PSI data (network, ~100 MB raw cache; reduced output is
small and shipped):

```bash
.venv/bin/python src/python/psi_repo.py status   # catalogue + s-Flame coverage
.venv/bin/python src/python/psi_repo.py all      # re-fetch catalogue + telemetry
```

## Data sources: what we use and why

| Resource | Use in T.R.I.A.G.E. | Status |
|----------|---------------------|--------|
| **PSI Data Repository — Combustion Science** | Primary empirical ground truth. Public API gives 24 investigations; PSI-23 (ACME s-Flame) has 286 test points with conditions and raw telemetry, reduced to 20 representative runs (CH4/C2H4/H2; 21%/30% O2; N2/He dilution; stable + extinguished). | **Essential — wired** |
| **A Researcher's Guide to ISS Combustion Science (2015)** | Physics grounding for the Tier-2 diagnostic (diffusion-limited flames, radiative quenching, soot, ventilation effects). | **Used** (prompt grounding) |
| **Apollo 1 / Apollo 13 / Mir 1997** | Fire-safety incident context for the Tier-2 recommendations (O2 enrichment, pressure transients, ventilation-driven spread). | **Used** (prompt grounding) |
| **NASA Combustion Science web pages** | Narrative background; PSI records already carry objectives, approach, hardware, and dates. | Optional |
| **ScienceCasts: Power of Studying Combustion on the ISS** | Public explainer video; no telemetry. | Not needed |
| **Fireman's Air Tanks / Fire Detector / Fire Attire spinoffs** | NASA technology-spinoff stories; unrelated to microgravity flame physics or the solver. | Not needed |

The repository ships a reduced, auditable s-Flame set in `data/psi/`
(`catalog.json`, `sflame_runs.json`); raw CSVs stay in the gitignored
`data/psi_cache/`. Fields that the tabular telemetry does not contain — flame
radius and calibrated flame temperature — are left **null**, never synthesized.

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
   Experiment Comparison** panel scores the run against the nearest real PSI
   flight test point (e.g. *ACME s-Flame · 19304A2 · 45% CH4 with N2*) with
   field-level agreement for oxygen, pressure, burn duration, and — when the
   source actually measured them — peak temperature and flame radius. A
   **"why this test point"** line shows the normalized distance breakdown,
   runner-up, real-versus-surrogate pool, and an explicit no-match state. It
   also shows the measured NASA outcome (stable vs extinguished, PMT peak) and a
   dense tier-1 verdict grid — all visible without scrolling. The center and right of the tab belong to the big **Tier 2
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
├── python/       # WebSocket server, NASA PSI repository client + s-Flame
│                 #   ground-truth builder, two-tier AI pipeline, solver1d/
│                 #   NumPy reference (grid/properties/chemistry/transport)
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

- **NASA PSI Data Repository** (Combustion): public repository API
  (`psi.nasa.gov/geode-py/ws/repo`). The catalogue covers all 24 Combustion
  Science investigations (ACME, Saffire, FLEX, BASS, SLICE, SPICE, SAME, …).
  Per-test-point numeric ground truth comes from ACME s-Flame (PSI-23, 286 test
  points, 18 test days): conditions from the experimental table, ignition and
  extinction from TP logs, chamber pressure from PTA3 per the ACME non-imaging
  data description, and ion current / PMT / radiometer peaks from the raw CSVs.
  Multi-TB video archives are intentionally not downloaded; flame radius and
  calibrated flame temperature are therefore left null rather than estimated.
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

The backend auto-loads the repo-root `.env` at startup; existing shell or
container variables take precedence. Docker Compose also reads `.env` for
substitution and forwards the keys defined in `docker-compose.yml`.

- `NANOGPT_API_KEY` — Tier 1 triage (`typesafe/jev-latest`, native
  Decisions API). Jev is a decision model, so the backend asks typed
  `choice`/`score`/`noul` questions and maps the answers onto the verdict
  schema. Without a key — or when the account has paid/decision models
  disabled — the verdict is the deterministic local heuristic and the panel
  shows `local` plus the actual fallback reason.
- `JEV_CONCURRENCY` — max concurrent triage calls in a parameter sweep
  (default 12).
- `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` / deployment — Tier 2
  synthesis (gated; trial TPM quota protected)
- All optional: every AI path has a deterministic local fallback so the demo
  never depends on network availability.

## Repository status

The 1D spherical solver now exists in both forms — the NumPy reference
(`src/python/solver1d/`) and the pybind11 C++ module (`src/cpp/`, built into
`build/triage_core*.so`). The WebSocket backend, S3 ingest, two-tier AI
pipeline (Jev/Azure when configured, explicit local fallback otherwise),
React/D3 dashboard, parameter sweeps, custom fuels, Jev comparison,
and Tier-2 report are functional end-to-end against it. `pytest` covers
thermochemistry, grid/transport, solver behaviour, C++/Python parity, and the
AI fallback/`.env` wiring.

The PSI metadata join is complete: the 24-investigation catalogue and the
per-test-point s-Flame ground truth are generated from the public repository
API and shipped under `data/psi/`. Remaining release work (see `PLAN.md`):
Docker end-to-end verification, demo video/pitch deck, custom
species/reaction editors, and the revision items in the internal revision
tracker (intentionally deferred, not silently fixed).
