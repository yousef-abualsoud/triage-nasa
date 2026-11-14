# PLAN — Master Engineering Plan

## Status (48h sprint, Block 0 complete)

- [x] Repo scaffold, .gitignore, requirements, Vite/React config
- [x] `src/shared/species_db.json` — 4 validated fuel presets + transport ref
- [x] `src/shared/constants.json` — physical constants, 5 gravity modes, defaults
- [x] `src/python/schema.py` — SimConfig / UnifiedPayload / JevVerdict / SimResult
      + solver-seam contract docstring
- [x] `src/python/sim_bridge.py` — seam + NumPy reference mock (runs ~2s/0.5s
      sim @128x128; zero-G sphere wider than 1G teardrop; quench at low O2)
- [x] `src/python/s3_ingest.py` — anonymous PSI listing/download w/ alias-based
      CSV parsing + deterministic synthetic ground truth (72 runs)
- [x] `src/python/jev_client.py` — Tier 1 concurrent triage + local heuristic
- [x] `src/python/azure_frontier_client.py` — Tier 2 synthesis + fallback report
- [x] `src/python/server.py` — full-duplex WebSocket, sweeps, run cache,
      fuel preset CRUD (`fuel_list` / `fuel_save` / `fuel_delete`), triage
      replies carry the nearest PSI ground truth
- [x] Frontend: three-tab dashboard (Run & Calculations / Fire Visuals &
      Analysis / More Graphs) with sticky tab nav and a hexagon-mesh
      background in the slider accent color. ControlPanel (custom fuel preset
      editor with persisted DB variables, custom gravity, iteration count,
      click-to-edit slider values, wall condition removed), IterationGraph,
      CalculationLog (live per-step trace), FlameField3D (three.js raymarched
      axisymmetric volumetric view, 3D/2D toggle), JevComparison (field-level
      agreement % vs nearest PSI run, compact rail under the visualizer),
      full-height Tier 2 report panel dominating Tab 2, MoreGraphs
      (burn curves vs PSI telemetry, soot/mean-T, burned fraction, buoyancy
      KE, radial profile) + Suggestions. O₂ sweep graph removed per spec. E2E
      verified in-browser (all tabs render; custom fuel create/select/run/
      delete persists; custom gravity run; triage %s; Tier 2 local fallback;
      3D canvas luminance probe centroid 0.517 at g=3.7)
- [x] README (judge quick start + AI disclosure + 3D axisymmetry disclosure)

## Solver seam contract (binding)

`triage_core.run_simulation(config_dict) -> dict`
- input: `SimConfig.model_dump()` (fuel = species_db key)
- output keys: `frames` ([ny][nx] K), `times` (s), `history`
  (list of {t_s, max_flame_radius_m, peak_temp_k, mean_temp_k,
  fuel_burned_fraction, soot_index, buoyancy_ke}), `final`
  ({quenched, quench_time_s, peak_temp_k, max_flame_radius_m,
  soot_volume_fraction, stability})
- Constraints: C++20, `-O3 -ffast-math -march=native`, zero heap allocs in
  the ADI loop, contiguous `std::vector` buffers, pybind11 `triage_core` module.
- Files landing in `src/cpp/`: `physics_solver.cpp`, `adi_solver.cpp`,
  `thomas_algorithm.cpp`, `thomas_algorithm.hpp`, `bindings.cpp`.
- Physics: Fick + Fourier + single-step Arrhenius (reduced), buoyancy source
  (rho_inf - rho), forced-flow advection for Saffire mode, adiabatic walls
  (wall-mode UI removed). Strictly 2D (no L_z / z fields).
- Run length is `iteration_count x dt_s` (no end_time_s); dt_s may be up to
  1 s per step. Custom gravity arrives as `gravity_mode == "custom"` with
  `custom_gravity_m_per_s2` / `custom_g_jitter_m_per_s2`; custom fuels are
  resolved from `data/custom_fuels.json` (merged onto species_db presets).

## Remaining blocks

1. **C++ ADI + Thomas solver** (`src/cpp/`), wire `sim_bridge._available_solver`
   to prefer `triage_core`. Validate: zero-G sphere vs 1G teardrop vs Saffire
   tilt; quench at low O2; ~ms-scale steps at 1282.
2. **PSI metadata join** — map real ACME/Saffire experiment IDs to fuel/
   gravity/BC fields (currently synthetic ground truth stands in).
3. **Docker** — Dockerfile multi-stage (C++ build → Python → node build),
   compose wiring; verify `docker compose up --build` end-to-end.
4. **Demo video + pitch deck**; final README polish; tag `v1.0-submission`.

## Non-negotiable rules

- Wolf Amendment: zero Chinese API endpoints anywhere.
- Azure trial TPM: Tier 2 gated to top-1% anomalies or explicit click.
- NanoGPT token budget: ~10-12M of 52M projected — keep context-isolated
  (one language domain per harness prompt).
- No commits with solver code before the window opens (rules: Git commit
  timestamps must fall inside the 48h window).
- Units: SI everywhere; internal conversions only at ingest boundaries.