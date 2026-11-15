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
- [x] `src/python/psi_repo.py` — public PSI repository API client: 24-investigation
      Combustion Science catalogue, PSI-23 s-Flame file index, experimental
      table / TP-log / telemetry parsers, curated ground-truth builder
- [x] `data/psi/` — shipped catalogue + real s-Flame test-point summaries
      (conditions, pressure, burn duration, ion current/PMT/radiometer,
      stability); raw CSVs cached in gitignored `data/psi_cache/`
- [x] `src/python/s3_ingest.py` — curated real data first, explicit synthetic
      surrogate fallback (`source="synthetic"`)
- [x] `src/python/jev_client.py` — tier-1 triage via the native Jev Decisions
      API (typed choice/score/noul questions) + 1D-spherical-aware local
      fallback; real PSI accession/test-point identity, measured-field scoring
- [x] Tier-1 engine wiring — repo-root `.env` auto-load (shell/container env
      wins), explicit `engine` field (`jev`/`local`), honest no-key vs
      call-failure fallback notes, bounded-concurrent sweep triage
- [x] `src/python/azure_frontier_client.py` — tier-2 synthesis + fallback report
- [x] Frontend: three-tab dashboard; ControlPanel with spherical inputs
      (mass flow, mixing mode, φ, oxidizer, r_min/r_max/Nr, BCs); painted
      2D/3D flame; Jev comparison; dominant Tier-2 panel; Tab-3 radial
      T/q̇/species profiles and T(r,t) heatmap; solver diagnostics in Suggestions
- [x] Tests: 52 passed — thermochemistry/stoichiometry, grid/Thomas/transport,
      solver end-to-end, C++/Python parity, PSI parsers and real-metadata
      reduction, match-rationale/no-match states, `.env` loading, Jev
      decision-answer mapping, fallback/sweep engine wiring
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

## Remaining work (ordered)

### Handoff snapshot (survives context compaction)

- **Branch:** `main` is merged and pushed at `35bd347` (live Jev 1.14);
  `feat/solver-1d-spherical` matches it exactly. No PR was needed (fast-forward).
- **Solver:** NumPy reference + C++ `triage_core`; 52 tests pass; production
  frontend build is clean.
- **Data:** 24 PSI Combustion Science investigations catalogued; ACME s-Flame
  (PSI-23) has 286 test points across 18 days, reduced to 20 curated runs
  (CH₄ 4, C₂H₄ 7, H₂ 9; 4 stable, 16 extinguished; 21%/30% O₂; N₂/He
  dilution). 72 synthetic surrogates remain as labelled fallback.
- **Triage:** exact fuel + gravity-class gates (`zero_g` ≡ `iss_micro_g`);
  distance `|ΔO₂|/40 + |ΔP|/2 + |Δu|/2`, plus `0.15` if stable/extinguished
  differs; real PSI beats synthetic; no match returns `None`.
- **AI engines:** Tier 1 uses `typesafe/jev-1.14` (`JEV_MODEL`) via NanoGPT's
  native `POST /decisions` API with typed choice/score/noul questions; the repo
  `.env` is auto-loaded (shell/container values win), sweeps use
  bounded-concurrent `triage_sweep`, and every verdict carries
  `engine="jev"|"local"` (shown as a chip). A local key now returns live Jev
  verdicts end-to-end; without a key or decisions access the same path falls
  back to local with the API reason. Tier 2 likewise falls back without Azure
  credentials.
- **Docker:** packaging fixed (`Dockerfile.frontend` builds the SPA; compose no
  longer mounts `dist/`; `.dockerignore` excludes docs/raw cache), but
  `docker compose up --build` is still unverified — Docker is not installed in
  this environment.
- **Docs:** `docs/` is local-only and gitignored. Never add it to the repo,
  Docker context, or a commit.

### Blocking submission

1. **Docker end-to-end verification**
   - Why: the README advertises `docker compose up --build` as the one-command
     judge path; the packaging was fixed but never executed.
   - Scope: build both images, start the stack, confirm the SPA at
     `http://localhost:8080` and backend at `ws://localhost:8765`; run one
     default simulation and one triage; inspect backend logs; confirm no
     `docs/` or `data/psi_cache/` in the build context/image.
   - Files: `Dockerfile`, `Dockerfile.frontend`, `docker-compose.yml`,
     `.dockerignore`.
   - Done when: `docker compose build` and `docker compose up` succeed from a
     clean checkout, the Jev panel resolves a real PSI test point, and the
     PLAN item is checked.

2. **Demo video + pitch deck**
   - Why: primary submission deliverable; the app alone is not a presentation.
   - Scope: 3–5 minute screen-recorded walkthrough — problem framing, 1D
     spherical solver, real PSI s-Flame matching, Jev comparison, Tier-2
     report, Moon/Mars ECLSS recommendations. Deck: architecture diagram,
     solver equations, data provenance, validation numbers, limitations,
     team/AI disclosure.
   - Files: new `demo/` or external artifacts; no solver changes required.
   - Done when: video exported and deck exported as PDF/PPTX, with AI-assisted
     content disclosed.

3. **Final README + submission tag**
   - Why: judges need a reliable clean-clone path and an honest limitations
     section.
   - Scope: verify the quick start from a fresh clone; add screenshots,
     architecture/data-flow summary, AI disclosure, known limitations (1D
     spherical vs teardrop, no calibrated flame radius/temperature in PSI
     tabular data); tag the submission commit.
   - Files: `README.md`, `PLAN.md`.
   - Done when: README commands work from a clean checkout and
     `v1.0-submission` points at the final commit.

4. **Merge branch to main — DONE**
   - Why: `origin/main` was still at `da3358c`; the solver, real PSI data, Jev
     integration, and Docker fixes lived only on the feature branch.
   - Done: fast-forwarded `main` `da3358c..35bd347` and pushed; re-ran `pytest`
     (52 passed) and the production frontend build on `main`; remote `main`
     contains no `.env` or `docs/`. `feat/solver-1d-spherical` is identical to
     `main` and can be deleted whenever convenient.

5. **Final QA sweep**
   - Why: last check before tagging; catches regressions from UI/data changes.
   - Scope: `pytest` (52), `npm run build`, default run, CH₄/C₂H₄/C₃H₈/H₂
     presets, one sweep, custom-fuel save/delete, triage, Tier-2 fallback,
     desktop + narrow viewport, browser console free of errors.
   - Files: `tests/`, frontend components, `src/python/server.py`.
   - Done when: all checks pass or remaining issues are documented in PLAN.

### Recommended product polish

6. **Match-transparency panel — DONE**
   - Why: the Jev panel shows the selected PSI test point but not why;
     “triangulation” is the first question a judge will ask.
   - Implemented: `_nearest_ground_truth` returns a `GroundTruthMatch`
     (`payload` + rationale). The triage reply carries `match` with the
     selected identity, normalized distance components (O₂/40, P/2, u/2) plus
     the 0.15 outcome penalty, raw deltas, runner-up, real/surrogate pool
     counts, and a no-match reason. `JevComparison` renders a compact
     “Why: … → d …” line, a runner-up/pool line, and a red no-match state.
   - Files: `src/python/server.py`,
     `src/frontend/components/JevComparison.jsx`, `src/frontend/styles.css`,
     `src/frontend/hooks.js` (new runs clear the previous verdict/report so a
     stale match cannot be shown against new conditions),
     `tests/test_psi_repo.py`. `jev_client.py` did not need changes: the
     rationale is presentation metadata, not part of the verdict prompt.
   - Verified: 52 tests pass; live browser run shows real PSI
     (`19304A2`, d 0.175, runner-up `20136G2`) and the C₃H₈/Mars no-match
     state; production build clean.
   - Done when: the panel shows selected accession/test point, distance
     breakdown, runner-up, and “no match” state without fabricating scores.

7. **Catalogue browser**
   - Why: all 24 PSI investigations are in `data/psi/catalog.json` but invisible
     in the product; the app looks s-Flame-only.
   - Scope: serve the catalogue over the existing WebSocket or a small HTTP
     endpoint; add a compact panel listing accession, acronym, platform, dates,
     objective, and PSI link; keep s-Flame as the numeric ground truth.
   - Files: `src/python/psi_repo.py` (`load_catalog` already exists),
     `src/python/server.py`, `src/frontend/components/` and `hooks.js`.
   - Done when: a judge can browse all 24 investigations in-app without new
     network calls.

8. **Matcher refinement / expanded ground truth**
   - Why: the current distance ignores blend fraction and burn duration, and
     only 20 of 286 s-Flame test points are curated.
   - Scope (choose one or both): add blend-fraction and burn-duration proximity
     terms with documented weights; or curate more/all 286 test points into
     `data/psi/sflame_runs.json` (larger file, cached downloads).
   - Files: `src/python/psi_repo.py`, `src/python/server.py`, `data/psi/`,
     `tests/test_psi_repo.py`.
   - Done when: rankings are deterministic, tests cover tie-breaks, and the
     chosen weights are documented in the plan/README.

### Deliberately deferred

9. **Revision tracker R1–R20**
   - Why: the solver is implemented as written; its open physical/mathematical
     issues are intentionally not resolved.
   - Scope: future block — continuity/momentum coupling (R1/R2), low-Mach
     energy (R3), side-inlet geometry (R4), heat-release units (R5), Arrhenius
     calibration (R6/R20), r=0 (R7), transport data (R8), conservation (R14),
     etc. `docs/SOLVER_REVISIONS.md` is local-only and must stay out of git.
   - Done when: a future revision block is explicitly opened; not part of this
     submission.

10. **Custom species/reaction CRUD**
    - Why: data model and loaders exist, but the editor UI/API is deferred
      (R16).
    - Scope: species/reaction editors, validation, import/export, custom
      oxidizers, and persistence in `data/custom_species.json` /
      `data/custom_reactions.json`.
    - Files: `src/python/mechanism.py`, `src/python/fuel_db.py`,
      `src/python/server.py`, `src/frontend/components/ControlPanel.jsx`.
    - Done when: a future block adds API + UI + tests; not blocking submission.

## Non-negotiable rules

- Wolf Amendment: zero Chinese API endpoints anywhere.
- Azure trial TPM: Tier 2 gated to top-1% anomalies or explicit click.
- NanoGPT token budget: ~10-12M of 52M projected — keep context-isolated
  (one language domain per harness prompt).
- No commits with solver code before the window opens (rules: Git commit
  timestamps must fall inside the 48h window).
- Units: SI everywhere; internal conversions only at ingest boundaries.
