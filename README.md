# T.R.I.A.G.E. — Thermal Reaction Inference & Anomaly Grading Engine

**2026 NASA Space Apps Challenge — "Flame in Free-Fall"**

An interactive, AI-powered Digital Twin dashboard built around a custom **1D
spherical finite-volume combustion solver**. It compares each run with NASA's
ACME s-Flame microgravity experiments and turns that comparison into
fire-safety guidance for Moon and Mars missions. Ground truth is sourced from
the live NASA PSI repository API and shipped as a reduced, auditable dataset in
`data/psi/`; the package also includes the full 24-investigation Combustion
Science catalogue for reference.

The solver implements five coupled equations — continuity, equation of state,
momentum consistency, species transport (with the correction velocity), and
sensible-enthalpy energy transport — plus the Arrhenius reaction-rate and
chemical-heat-release calculators. A NumPy reference implementation and a
pybind11 C++ module (`triage_core`) share the same seam; the dashboard shows
which one is active.
Open issues in the source document are implemented literally and tracked in
the internal revision tracker (kept outside the distributed repository); the
as-built notes are in the internal solver notes.

> **AI disclosure (per NASA Space Apps rules):** This project was built with
> AI-assisted code generation and data curation (architecture, C++/Python/
> JavaScript scaffolding, documentation). All AI-generated content is
> acknowledged in this README. No AI-generated
> imagery or audio is used in the core deliverable; any demo-video voice-over
> (if produced) uses Azure Speech Neural TTS and is disclosed as such.

---

## Quick Start

### Prerequisites

Both options require Git to clone the repository. Option 1 otherwise needs
only Docker; Option 2 also needs Python and Node.js. The C++ solver toolchain
is optional. No GPU or external AI key is required for the core demo.

| Tool | Needed for | Get it |
|------|------------|--------|
| Git | Both options (cloning the repository) | [git-scm.com downloads](https://git-scm.com/downloads) |
| Docker with Compose v2 | Option 1 (recommended) | [Docker Desktop](https://www.docker.com/products/docker-desktop/) · [Docker Engine + Compose](https://docs.docker.com/engine/install/) |
| Python 3.12+ | Option 2 backend and tests | [python.org downloads](https://www.python.org/downloads/) |
| Node.js 22+ | Option 2 frontend | [nodejs.org downloads](https://nodejs.org/en/download) |
| CMake 3.24+ | Optional C++ solver | [cmake.org downloads](https://cmake.org/download/) |
| GCC or Clang with C++20 support | Optional C++ solver | [GCC install](https://gcc.gnu.org/install/) · [Clang install](https://clang.llvm.org/get_started.html) |

Check versions with `git --version`, `docker --version`,
`docker compose version`, `python3 --version`, `node --version`, and
`cmake --version`.

### Option 1 — Docker (one command)

Start Docker Desktop and wait until it reports **Engine running**
(`docker info` should succeed). If Docker returns an
`npipe:////./pipe/docker_engine` error, the daemon has not started yet. Run the
clone from your home directory or another empty parent directory, not from
inside an existing checkout. Then:

```bash
git clone https://github.com/yousef-abualsoud/triage-nasa.git
cd triage-nasa

# Optional: enable live Jev/DeepSeek calls. Skip this and the app still runs
# with deterministic local fallbacks.
cp .env.example .env
# edit .env and set NANOGPT_API_KEY (and optional Azure keys)

docker compose up --build
```

**Windows:** the block above uses bash syntax. In CMD, use
`copy .env.example .env`; in PowerShell, use
`Copy-Item .env.example .env`. The `#` lines are comments and must not be
pasted into CMD.

Open `http://localhost:8080`; the backend WebSocket is on
`ws://localhost:8765`. Ports 8080 and 8765 must be free. The first build takes a
few minutes while Docker pulls images, builds the C++ solver, and runs
`npm ci`. Leave the command running; stop it with `Ctrl+C`, or run
`docker compose down` from another terminal.

The SPA is built inside `Dockerfile.frontend` and served by nginx; the backend
image builds the C++ `triage_core` module. `./data` is mounted into the backend
so curated PSI ground truth and custom presets persist. No local
`npm run build` is required.

### Option 2 — Local development

Clone the repository, then run the setup commands from its root. The commands
assume a Unix shell. On Windows, use WSL 2 for the local path; the C++ build
flags target GCC/Clang.

```bash
# 0. From your home directory, clone and enter (skip the clone if already there)
cd ~
git clone https://github.com/yousef-abualsoud/triage-nasa.git
cd triage-nasa

# 1. Preflight: confirm the repository root
pwd && ls requirements.txt CMakeLists.txt

# 2. Python environment and dependencies (Python 3.12+)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. Optional C++ solver (otherwise the NumPy reference is used)
cmake -B build -DCMAKE_BUILD_TYPE=Release \
  -Dpybind11_DIR="$(.venv/bin/python -m pybind11 --cmakedir)"
cmake --build build -j

# 4. Backend — terminal 1
.venv/bin/python src/python/server.py          # ws://0.0.0.0:8765
```

```bash
# 5. Frontend — terminal 2 (Node 22+)
cd src/frontend
npm ci
npm run dev                                    # http://localhost:5173
```

`sim_bridge.py` auto-loads `build/triage_core*.so` when present. The C++ build
is optional; without it the NumPy reference implements the same solver seam.

> **Ports:** Docker serves the dashboard at `http://localhost:8080`. Local
> development serves it at `http://localhost:5173`; port 8080 is not used in
> that path. Both connect to the backend WebSocket on `ws://localhost:8765`.

Refresh or inspect the PSI data (requires network; the reduced output is
shipped, while raw CSVs stay in the gitignored cache):

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
`data/psi_cache/`. For real PSI records, fields that the tabular telemetry does
not contain — flame radius and calibrated flame temperature — are left
**null**, never estimated. Offline surrogate fallback rows are explicitly
labelled `source="synthetic"` and are never presented as NASA measurements.

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
   **Iteration Graph** (ΔT between successive saved iterations) and **Active
   Calculations** trace fill with per-step scalars as the solver computes.

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
   dense tier-1 verdict grid in the left rail. The right side of the tab is the
   big **Tier 2 report** panel (**DeepSeek v4.1 Flash** on NanoGPT, with an
   optional Azure AI Foundry fallback; generated only on an explicit user click,
   so no automatic frontier requests are made), which produces a Markdown
   fire-safety diagnostic grounded in the 2015
   *ISS Combustion Science Researcher's Guide* and the Apollo 1 /
   Apollo 13 / Mir 1997 incident history, with Moon/Mars ECLSS
   recommendations. The panel chip names the engine that actually answered;
   a failed or unconfigured call is labeled `local fallback` with the reason.
   While a report is generating, an indeterminate progress bar shows elapsed
   seconds (triage + synthesis typically take 20–40 s).

3. **Tab 3 · More Graphs.** A responsive diagnostics dashboard: burn curves
   (with a NASA PSI overlay when the matched record includes a comparable
   profile), soot index & mean temperature, fuel burned fraction, the iteration
   ΔT graph, the angle-averaged radial temperature profile of the current frame,
   the solver's **radial T/q̇** and **species** profiles, and a **T(r,t)**
   heatmap from the saved radial snapshots, plus
   rule-based **suggestions** read off the run's own numbers (including honest
   solver diagnostics such as mass-budget drift, which is tracked in the
   internal revision tracker). Charts measure their container and render at CSS
   pixel size, axis titles live in dedicated gutters, and every x axis starts
   at 0: time series begin at t = 0 / iteration 0 (the solvers emit the
   pre-run state as the first sample), and radial curves hold the innermost
   solver value out to r = 0 with the actual `r_min` boundary marked. Hover any
   chart for a cursor readout with exact sampled values, including both sides
   of a dual axis or all series in a history plot.

### Report export

The **Export PDF** button at the far right of the tab strip unlocks once the
current run has both a tier-1 verdict and a tier-2 report. It downloads an A4
portrait report with the centered **T.R.I.A.G.E.** wordmark, run configuration
and outcome tables, the tier-1 verdict and Jev/NASA PSI comparison, the
tier-2 fire-safety synthesis and ECLSS recommendations, all Tab 3 charts,
rule-based suggestions, and solver diagnostics. Charts are captured from the
same D3 renderer at high resolution and keep the dashboard's dark palette.

## Architecture

```
src/
├── cpp/          # 1D spherical finite-volume solver (thomas.cpp, solver_core.cpp,
│                 #   bindings.cpp) → triage_core.so via pybind11
├── python/       # WebSocket server, NASA PSI repository client + s-Flame
│                 #   ground-truth builder, two-tier AI pipeline, solver1d/
│                 #   NumPy reference (grid/properties/chemistry/transport)
├── frontend/     # React + D3 dashboard, chart tooltips, A4 PDF report (Vite)
└── shared/       # species_db.json + reactions.json + constants.json
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
covered by `tests/test_parity.py` across short and mass-flow runs, where final
frame and radial temperature differences stay below 1 K.

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
- **Species/reaction data**: The NASA-7 thermodynamic coefficients in
  `src/shared/species_db.json` match
  [GRI-Mech 3.0](https://github.com/Cantera/cantera/blob/main/data/gri30.yaml).
  Fuel-level transport, kinetic, and flame-speed presets are reduced
  engineering values for the global single-step model. C3H8 currently uses a
  constant `cp`; transport uses power-law correlations rather than full
  Chapman-Enskog (R8). The source document's open physical/mathematical issues
  are implemented as written and tracked in the internal revision tracker.
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

- `NANOGPT_API_KEY` — Tier 1 triage (`typesafe/jev-1.14`, native
  Decisions API) and Tier 2 synthesis. Jev is a decision model, so the backend
  asks typed `choice`/`score`/`noul` questions and maps the answers onto the
  verdict schema. Without a key — or when the account has paid/decision models
  disabled — the verdict is the deterministic local heuristic and the panel
  shows `local` plus the actual fallback reason.
- `JEV_MODEL` — decision model ID (default `typesafe/jev-1.14`).
- `JEV_CONCURRENCY` — max concurrent triage calls in a parameter sweep
  (default 12).
- `TIER2_MODEL` — Tier 2 chat model (default
  `deepseek/deepseek-v4.1-flash-1017:thinking`). It is served through
  NanoGPT's US-hosted OpenAI-compatible endpoint and reuses
  `NANOGPT_API_KEY`.
- `TIER2_MAX_TOKENS` / `TIER2_TIMEOUT_S` — generation cap and request timeout
  (defaults `8000` / `180`; the thinking model spends part of the cap on
  reasoning tokens).
- `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` /
  `AZURE_OPENAI_DEPLOYMENT` (plus optional `AZURE_OPENAI_API_VERSION`) —
  optional Tier 2 fallback, used only if NanoGPT is unset or the DeepSeek call
  fails (gated; trial TPM quota protected).
- All optional: every AI path has a deterministic local fallback so the demo
  never depends on network availability.

## Repository status

The 1D spherical solver now exists in both forms — the NumPy reference
(`src/python/solver1d/`) and the pybind11 C++ module (`src/cpp/`, built into
`build/triage_core*.so`). The WebSocket backend, PSI ground-truth loading,
two-tier AI pipeline (Jev/DeepSeek when configured, explicit local fallbacks
otherwise), React/D3 dashboard, parameter sweeps, custom fuels, Jev comparison,
Tier-2 report, interactive chart readouts, and A4 PDF export are functional
end-to-end against it. The test suite currently has 61 passing tests covering
thermochemistry, grid/transport, solver behaviour, C++/Python parity, and the
AI fallback/`.env` wiring.

The PSI metadata join is complete: the 24-investigation catalogue and the
per-test-point s-Flame ground truth are generated from the public repository
API and shipped under `data/psi/`. The local venv/Vite path is verified
end-to-end, Docker packaging is included for one-command deployment, and the
core demo runs without external AI keys because both tiers fall back
deterministically. Optional extensions and the internal revision items are
tracked in the internal project plan (not distributed).
