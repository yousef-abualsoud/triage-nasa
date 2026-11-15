# PLAN — Master Engineering Plan

## Status (48h sprint, solver block complete)

- [x] Repo scaffold, .gitignore, requirements, Vite/React config
- [x] `src/shared/species_db.json` — 4 validated fuel presets + species table
      (NASA-7 thermo, transport correlations) + transport reference
- [x] `src/shared/reactions.json` — one global reaction per built-in fuel
      (reactants/products/ν/A/β/Ea/orders/rate units) + elemental/mass validation
- [x] `src/shared/constants.json` — physical constants, 5 gravity modes, defaults
- [x] `src/python/schema.py` — SimConfig / UnifiedPayload / JevVerdict / SimResult
      + spherical fields (`r_min`, `r_max`, `Nr`, `mass_flow`, mixing mode, φ,
      oxidizer, BCs) + solver-seam contract docstring
- [x] `src/python/mechanism.py` — species/reaction loading, formula parsing,
      stoichiometry, mixture properties, C++ payload
- [x] `src/python/solver1d/` — NumPy reference implementation of the document:
      grid, properties, chemistry, transport (Thomas + upwind + correction
      velocity), nine-stage time loop, painted frames, radial outputs
- [x] `src/python/sim_bridge.py` — prefers `triage_core`, falls back to the
      reference; auto-loads `build/`
- [x] `src/cpp/` — C++20 pybind11 module (`thomas.cpp`, `solver_core.cpp`,
      `bindings.cpp`); same equations; C++/Python parity ≤0.73 K on the default
      256-cell run; ~6.7× faster
- [x] `src/python/server.py` — WebSocket server, sweeps, run cache, fuel CRUD,
      frame/time/history/radial alignment, triage + Tier-2 replies
- [x] `src/python/s3_ingest.py` — anonymous PSI listing/download + synthetic GT
- [x] `src/python/jev_client.py` — tier-1 triage + 1D-spherical-aware heuristic;
      PSI experiment id forwarded for profile matching
- [x] `src/python/azure_frontier_client.py` — tier-2 synthesis + fallback report
- [x] Frontend: three-tab dashboard; ControlPanel with spherical inputs
      (mass flow, mixing mode, φ, oxidizer, r_min/r_max/Nr, BCs); painted
      2D/3D flame; Jev comparison; dominant Tier-2 panel; Tab-3 radial
      T/q̇/species profiles and T(r,t) heatmap; solver diagnostics in Suggestions
- [x] Tests: 31 passed — thermochemistry/stoichiometry, grid/Thomas/transport,
      solver end-to-end, C++/Python parity
- [x] Internal as-built solver notes and the deferred revision tracker
      (kept out of the distributed repository)
- [x] README (judge quick start + AI disclosure + 1D-spherical 3D disclosure)

## Solver seam contract (binding)

`triage_core.run_simulation(config_dict, mechanism_dict) -> dict`
- `config_dict`: `SimConfig.model_dump()` (fuel = species_db/custom key).
- `mechanism_dict`: `mechanism.mechanism_payload()` (species order, W, hf,
  NASA-7/constant cp, transport coefficients, ν, orders, A/β/Ea, constants).
- Output keys: `frames` (painted T `[ny][nx]`, K), `times` (s),
  `history` (per-saved-step scalars), `final` (existing scalars + `radial` and
  `diagnostics`), `radial_frames` (coarse radial snapshots).
- Geometry: **1D spherical radial** `r_min_m..r_max_m`, `Nr` cell-centered
  cells; display grid `nx × ny` is independent.
- Equations: the document's literal forms — continuity `u = ṁ/(4πr²ρ)`, EOS,
  momentum residual, non-conservative species/energy with `(Y/ρ)∂ρ/∂t` and
  `(h_s/ρ)∂ρ/∂t`, Arrhenius rate, `q̇ = −Σ h_f ω̇`. Open issues are **not**
  resolved; see the internal revision tracker.
- Numerical choices: cell-centered FV, implicit Thomas diffusion, explicit
  first-order upwind advection, chemistry substepping, 400-substep cap.
- Constraints: C++20, `-O3 -march=native` (no `-ffast-math`), `std::vector`
  buffers, pybind11 module. Files: `thomas.cpp`, `solver_core.cpp`,
  `bindings.cpp`.
- Run length is `iteration_count × dt_s`; `t_end_s`, when supplied, derives
  `iteration_count`.
- Custom fuels resolve from `data/custom_fuels.json`; C/H/O formulas generate
  a pseudo-species + global reaction; unparseable formulas use the lumped preset.

## Remaining blocks

1. **PSI metadata join** — map real ACME/Saffire experiment IDs to fuel/
   gravity/BC fields (currently synthetic ground truth stands in).
2. **Docker** — verify `docker compose up --build` end-to-end; the Dockerfile
   now passes `pybind11_DIR`, builds the 1D sources, and no longer masks build
   failures.
3. **Revision tracker items** — deliberately deferred: continuity/momentum
   coupling (R1/R2), low-Mach energy (R3), side-inlet geometry (R4), heat-release
   units (R5), Arrhenius calibration (R6/R20), r=0 (R7), full transport data
   (R8), conservation (R14), etc. Address in a future block, not during the
   as-written implementation.
4. **Custom species/reaction CRUD UI** — data model/loading exists; the editor
   UI and arbitrary mechanism import/export are deferred (R16).
5. **Demo video + pitch deck**; final README polish; tag `v1.0-submission`.

## Non-negotiable rules

- Wolf Amendment: zero Chinese API endpoints anywhere.
- Azure trial TPM: Tier 2 gated to top-1% anomalies or explicit click.
- NanoGPT token budget: ~10-12M of 52M projected — keep context-isolated
  (one language domain per harness prompt).
- No commits with solver code before the window opens (rules: Git commit
  timestamps must fall inside the 48h window).
- Units: SI everywhere; internal conversions only at ingest boundaries.
