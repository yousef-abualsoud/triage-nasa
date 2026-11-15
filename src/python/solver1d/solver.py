"""1D spherical reference solver: nine-stage time loop from the architecture spec.

This implementation follows the solver specification literally:

  §5.1  u = mdot / (4 pi r^2 rho)
  §5.2  rho = p0 W_mix / (Ru T)
  §5.3  momentum residual R = u du/dr - g_r (diagnostic only)
  §5.4  non-conservative species transport with (Y_i/rho) drho/dt
  §5.5  xi_dot = A T^beta exp(-Ea/(Ru T)) prod C_i^alpha_i
  §5.6  q_dot = -sum hf_i omega_i
  §5.7  non-conservative sensible-enthalpy transport with (h_s/rho) drho/dt

Numerical choices (documented as R15 in the internal revision tracker):
  * cell-centered finite volume on the radial grid
  * implicit spherical diffusion via Thomas; explicit first-order upwind advection
  * local chemistry with reactant-extent and temperature-rise limiting
  * adaptive substepping inside each user outer step
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from mechanism import Mechanism, mechanism_summary
from .chemistry import integrate_chemistry
from .grid import RadialGrid
from .properties import (
    apply_ignition,
    boundary_compositions,
    boundary_mass_flux,
    continuity_velocity,
    estimate_adiabatic_flame_temp,
    flame_radius,
    initial_composition,
    momentum_residual,
    premixed_composition,
    stability_score,
    total_enthalpy,
    total_mass,
    volume_fraction,
)
from .transport import (
    diffusive_fluxes,
    implicit_diffusion_species,
    implicit_diffusion_temperature,
    species_enthalpy_flux,
    upwind_advection,
)

MAX_SUBSTEPS_PER_OUTER = 400
COARSE_RADIAL_POINTS = 64


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _load_fuel_preset(fuel: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parent.parent.parent.parent
    try:
        with open(root / "src" / "shared" / "species_db.json", encoding="utf-8") as fh:
            builtins = json.load(fh).get("fuels", {})
        if fuel in builtins:
            return builtins[fuel]
    except (OSError, json.JSONDecodeError):
        pass
    try:
        with open(root / "data" / "custom_fuels.json", encoding="utf-8") as fh:
            custom = json.load(fh)
        if fuel in custom:
            return custom[fuel]
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _normalise_y(Y: np.ndarray, n2_index: int | None) -> np.ndarray:
    y = np.asarray(Y, dtype=np.float64)
    y = np.where(np.isfinite(y), y, 0.0)
    y = np.maximum(y, 0.0)
    sums = np.sum(y, axis=1, keepdims=True)
    good = sums[:, 0] > 1e-12
    y[good] = y[good] / sums[good]
    if np.any(~good):
        y[~good] = 0.0
        if n2_index is not None:
            y[~good, n2_index] = 1.0
    return y


def _state_metrics(
    mech: Mechanism,
    cfg: Any,
    grid: RadialGrid,
    t: float,
    iteration: int,
    T: np.ndarray,
    Y: np.ndarray,
    rho: np.ndarray,
    u: np.ndarray,
    g_r: float,
    fuel_index: int,
    initial_fuel_mass: float,
) -> dict[str, Any]:
    ambient = float(cfg.ambient_temperature_k)
    flame_mask = T > ambient + 200.0
    radius = flame_radius(T, grid, ambient)
    flame_frac = volume_fraction(flame_mask, grid)
    fuel_mass = float(np.sum(rho * Y[:, fuel_index] * grid.cell_volume))
    burned = 0.0 if initial_fuel_mass <= 0.0 else float(np.clip(1.0 - fuel_mass / initial_fuel_mass, 0.0, 1.0))
    mean_t = float(np.sum(T * grid.cell_volume) / max(np.sum(grid.cell_volume), 1e-30))
    preset = _load_fuel_preset(cfg.fuel)
    soot_tendency = float(preset.get("soot_tendency_index", 0.1))
    soot = float(
        soot_tendency
        * flame_frac
        * np.sqrt(max(float(cfg.ambient_pressure_bar), 1e-6))
        * (1.0 - min(float(cfg.oxygen_pct) / 100.0, 0.95))
        * 10.0
    )
    c = mech.concentrations(rho, Y)
    xi = mech.rate_of_progress(T, c)
    qdot = mech.heat_release(T, rho, Y)
    return {
        "t_s": round(float(t), 6),
        "iteration": int(iteration),
        "max_flame_radius_m": round(float(radius), 6),
        "peak_temp_k": round(float(np.max(T)), 1),
        "mean_temp_k": round(mean_t, 1),
        "fuel_burned_fraction": round(burned, 4),
        "soot_index": round(soot, 4),
        "buoyancy_ke": round(abs(float(g_r)) * float(radius), 6),
        "reaction_rate_max": round(float(np.max(xi)) if xi.size else 0.0, 4),
        "heat_release_max_w_m3": round(float(np.max(qdot)) if qdot.size else 0.0, 3),
        "momentum_residual_max": round(
            float(np.max(np.abs(momentum_residual(u, grid, g_r)[0]))), 6
        ),
        "flame_speed_m_per_s": 0.0,  # filled by the caller with the previous radius/time
    }


def _coarse_radial(
    mech: Mechanism,
    grid: RadialGrid,
    t: float,
    T: np.ndarray,
    Y: np.ndarray,
    rho: np.ndarray,
    u: np.ndarray,
) -> dict[str, Any]:
    n = min(COARSE_RADIAL_POINTS, grid.n_cells)
    idx = np.unique(np.linspace(0, grid.n_cells - 1, n).astype(int))
    fuel = mech.fuel_index
    o2 = mech.key_to_index.get("O2")
    qdot = mech.heat_release(T, rho, Y)
    xi = mech.rate_of_progress(T, mech.concentrations(rho, Y))
    return {
        "t_s": round(float(t), 6),
        "r_m": np.round(grid.r_centers[idx], 7).tolist(),
        "temperature_k": np.round(T[idx], 2).tolist(),
        "density_kg_m3": np.round(rho[idx], 6).tolist(),
        "velocity_ms": np.round(u[idx], 7).tolist(),
        "fuel_mass_fraction": np.round(Y[idx, fuel], 6).tolist(),
        "oxygen_mass_fraction": (
            np.round(Y[idx, o2], 6).tolist() if o2 is not None else []
        ),
        "reaction_rate_mol_m3_s": np.round(xi[idx], 5).tolist(),
        "heat_release_w_m3": np.round(qdot[idx], 3).tolist(),
    }


def _full_radial(
    mech: Mechanism,
    grid: RadialGrid,
    T: np.ndarray,
    Y: np.ndarray,
    rho: np.ndarray,
    u: np.ndarray,
    hs: np.ndarray,
) -> dict[str, Any]:
    c = mech.concentrations(rho, Y)
    omega = mech.production_rates(T, rho, Y)
    xi = mech.rate_of_progress(T, c)
    qdot = mech.heat_release(T, rho, Y)
    wmix = mech.molecular_weight(Y)
    return {
        "r_m": np.round(grid.r_centers, 8).tolist(),
        "temperature_k": np.round(T, 3).tolist(),
        "density_kg_m3": np.round(rho, 8).tolist(),
        "velocity_ms": np.round(u, 9).tolist(),
        "sensible_enthalpy_j_per_kg": np.round(hs, 3).tolist(),
        "mass_fractions": {
            k: np.round(Y[:, i], 8).tolist() for i, k in enumerate(mech.species_keys)
        },
        "molar_concentrations_mol_m3": {
            k: np.round(c[:, i], 8).tolist() for i, k in enumerate(mech.species_keys)
        },
        "reaction_rate_mol_m3_s": np.round(xi, 6).tolist(),
        "production_rates_kg_m3_s": {
            k: np.round(omega[:, i], 6).tolist() for i, k in enumerate(mech.species_keys)
        },
        "heat_release_w_m3": np.round(qdot, 3).tolist(),
        "molecular_weight_kg_mol": np.round(wmix, 8).tolist(),
    }


# ---------------------------------------------------------------------------
# One substep
# ---------------------------------------------------------------------------


def _advance_substep(
    cfg: Any,
    mech: Mechanism,
    grid: RadialGrid,
    T: np.ndarray,
    Y: np.ndarray,
    rho: np.ndarray,
    u: np.ndarray,
    p0: float,
    g_r: float,
    Y_inner: np.ndarray,
    Y_outer: np.ndarray,
    T_inner: float,
    T_outer: float,
    dt: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    bc_in, bc_out = cfg.inner_bc, cfg.outer_bc
    cp = np.maximum(mech.cp_mix(T, Y), 1.0)
    lam = mech.lambda_mix(T, Y)
    D = mech.diffusivity(T, p0)
    D_face = grid.face_average(D)
    rho_face = grid.face_average(rho)
    lam_face = grid.face_average(lam)

    # 1) Implicit spherical diffusion (species Fickian + energy conduction).
    Y_new = implicit_diffusion_species(
        Y, dt, grid, rho, D_face, Y_inner, Y_outer, bc_in, bc_out
    )
    T_new = implicit_diffusion_temperature(
        T, dt, grid, rho, cp, lam_face, T_inner, T_outer, bc_in, bc_out
    )

    # 2) Explicit upwind advection with the doc's continuity velocity.
    Y_new = upwind_advection(Y_new, u, dt, grid, Y_inner, Y_outer, bc_in, bc_out)
    T_new = upwind_advection(T_new, u, dt, grid, T_inner, T_outer, bc_in, bc_out)
    Y_new = _normalise_y(Y_new, mech.n2_index)
    T_new = np.clip(T_new, 200.0, 6000.0)

    # 3) Mixture-averaged correction velocity (sum j_i = 0) and the
    #    diffusion-enthalpy flux in the energy equation.
    j_fick, v_corr, Y_face = diffusive_fluxes(
        Y_new, grid, rho, D_face, Y_inner, Y_outer, bc_in, bc_out
    )
    j_corr = rho_face[:, None] * Y_face * v_corr[:, None]
    j_total = j_fick + j_corr
    Y_new = Y_new - dt * grid.divergence(j_corr) / np.maximum(rho, 1e-30)[:, None]
    Y_new = _normalise_y(Y_new, mech.n2_index)

    hs_species = np.stack([s.hs_mass(T_new) for s in mech.species], axis=-1)
    e_flux = species_enthalpy_flux(hs_species, j_total, grid)
    T_new = T_new - dt * grid.divergence(e_flux) / (
        np.maximum(rho, 1e-30) * np.maximum(cp, 1.0)
    )
    T_new = np.clip(T_new, 200.0, 6000.0)

    # 4) Chemistry (doc §5.5–5.6) with reactant/temperature limiting.
    T_new, Y_new, chem_diag = integrate_chemistry(mech, T_new, Y_new, rho, dt)
    Y_new = _normalise_y(Y_new, mech.n2_index)

    # 5) Equation of state and the doc's (Y_i/rho) drho/dt,
    #    (h_s/rho) drho/dt terms.
    rho_after = mech.density(T_new, p0, Y_new)
    drho = rho_after - rho
    Y_new = Y_new - Y_new * (drho / np.maximum(rho, 1e-30))[:, None]
    Y_new = _normalise_y(Y_new, mech.n2_index)
    hs_now = mech.hs_mix(T_new, Y_new)
    T_new = T_new - (hs_now / (np.maximum(rho, 1e-30) * np.maximum(cp, 1.0))) * drho
    T_new = np.clip(T_new, 200.0, 6000.0)

    # 6) Update properties and the continuity velocity.
    Y_new = _normalise_y(Y_new, mech.n2_index)
    rho_new = mech.density(T_new, p0, Y_new)
    u_new = continuity_velocity(rho_new, float(cfg.mass_flow_kg_s), grid)
    hs_new = mech.hs_mix(T_new, Y_new)

    return T_new, Y_new, rho_new, u_new, hs_new, {
        "chem": chem_diag,
        "drho_max_over_rho": float(np.max(np.abs(drho) / np.maximum(rho, 1e-30))),
    }


def _choose_dt(
    grid: RadialGrid,
    u: np.ndarray,
    dt_remaining: float,
    max_substeps: int,
) -> tuple[float, bool]:
    max_u = float(np.max(np.abs(u))) if u.size else 0.0
    dt_cfl = 0.4 * grid.dr / max(max_u, 1e-12)
    dt_sub = min(float(dt_remaining), float(dt_cfl))
    min_dt = float(dt_remaining) / max(1, max_substeps)
    capped = False
    if dt_sub < min_dt:
        dt_sub = min_dt
        capped = True
    if dt_sub <= 0.0:
        dt_sub = float(dt_remaining)
    return dt_sub, capped


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(cfg: Any) -> dict[str, Any]:
    """Run one 1D spherical simulation and return the seam payload."""
    mech = cfg.resolved_mechanism()
    grid = RadialGrid(float(cfg.r_min_m), float(cfg.r_max_m), int(cfg.Nr))
    p0 = float(cfg.ambient_pressure_bar) * 1.0e5
    t0 = float(cfg.ambient_temperature_k)
    g_r = float(cfg.radial_gravity())

    Y = initial_composition(cfg, mech, grid)
    T = np.full(grid.n_cells, t0, dtype=np.float64)
    T, ignition_diag = apply_ignition(cfg, mech, grid, T, Y)
    Y = _normalise_y(Y, mech.n2_index)
    rho = mech.density(T, p0, Y)
    u = continuity_velocity(rho, float(cfg.mass_flow_kg_s), grid)
    hs = mech.hs_mix(T, Y)

    Y_inner, Y_outer, T_inner, T_outer = boundary_compositions(cfg, mech)
    fuel_index = mech.fuel_index
    initial_fuel_mass = float(np.sum(rho * Y[:, fuel_index] * grid.cell_volume))
    mass_initial = total_mass(rho, grid)
    enthalpy_initial = total_enthalpy(mech, T, Y, rho, grid)

    frames: list[list[list[float]]] = []
    times: list[float] = []
    history: list[dict[str, Any]] = []
    radial_frames: list[dict[str, Any]] = []

    t = 0.0
    peak_t = float(np.max(T))
    quenched = False
    quench_t: float | None = None
    total_substeps = 0
    substep_capped = False
    last_radius = 0.0
    last_save_t = 0.0
    last_diag: dict[str, Any] = {}

    # Save the pre-ignition state so every streamed series starts at t = 0 /
    # iteration 0 instead of the first output-interval step (4 by default).
    initial_entry = _state_metrics(
        mech,
        cfg,
        grid,
        0.0,
        0,
        T,
        Y,
        rho,
        u,
        g_r,
        fuel_index,
        initial_fuel_mass,
    )
    history.append(initial_entry)
    times.append(0.0)
    frames.append(
        grid.paint_temperature(T, int(cfg.nx), int(cfg.ny), T_inner, T_outer)
    )
    radial_frames.append(_coarse_radial(mech, grid, 0.0, T, Y, rho, u))
    last_radius = float(initial_entry["max_flame_radius_m"])

    n_outer = int(cfg.iteration_count)
    for step in range(1, n_outer + 1):
        dt_remaining = float(cfg.dt_s)
        sub = 0
        while dt_remaining > 1e-15:
            dt_sub, capped = _choose_dt(
                grid, u, dt_remaining, MAX_SUBSTEPS_PER_OUTER
            )
            substep_capped = substep_capped or capped
            T, Y, rho, u, hs, last_diag = _advance_substep(
                cfg,
                mech,
                grid,
                T,
                Y,
                rho,
                u,
                p0,
                g_r,
                Y_inner,
                Y_outer,
                T_inner,
                T_outer,
                dt_sub,
            )
            dt_remaining -= dt_sub
            t += dt_sub
            sub += 1
            total_substeps += 1
            peak_t = max(peak_t, float(np.max(T)))
            if sub >= MAX_SUBSTEPS_PER_OUTER and dt_remaining > 1e-15:
                # Numerically capped: finish the outer step with the remaining
                # time in one last advance rather than dropping time.
                T, Y, rho, u, hs, last_diag = _advance_substep(
                    cfg,
                    mech,
                    grid,
                    T,
                    Y,
                    rho,
                    u,
                    p0,
                    g_r,
                    Y_inner,
                    Y_outer,
                    T_inner,
                    T_outer,
                    dt_remaining,
                )
                t += dt_remaining
                dt_remaining = 0.0
                total_substeps += 1
                substep_capped = True

        if step > 1 and not quenched and float(np.max(T)) < t0 + 150.0:
            quenched = True
            quench_t = float(t)

        should_save = (step % int(cfg.output_interval_steps) == 0) or (step == n_outer)
        if should_save:
            entry = _state_metrics(
                mech, cfg, grid, t, step, T, Y, rho, u, g_r, fuel_index, initial_fuel_mass
            )
            if entry["t_s"] > last_save_t:
                entry["flame_speed_m_per_s"] = round(
                    (entry["max_flame_radius_m"] - last_radius)
                    / max(entry["t_s"] - last_save_t, 1e-30),
                    6,
                )
            last_radius = float(entry["max_flame_radius_m"])
            last_save_t = float(entry["t_s"])
            history.append(entry)
            times.append(float(entry["t_s"]))
            frames.append(
                grid.paint_temperature(T, int(cfg.nx), int(cfg.ny), T_inner, T_outer)
            )
            radial_frames.append(_coarse_radial(mech, grid, t, T, Y, rho, u))

    final = {
        "quenched": bool(quenched),
        "quench_time_s": quench_t,
        "peak_temp_k": round(float(peak_t), 1),
        "max_flame_radius_m": round(
            float(flame_radius(T, grid, t0)), 6
        ),
        "soot_volume_fraction": round(
            _state_metrics(
                mech, cfg, grid, t, n_outer, T, Y, rho, u, g_r, fuel_index, initial_fuel_mass
            )["soot_index"]
            * 1.0e-3,
            8,
        ),
        "stability": stability_score(quenched, history),
        "radial": _full_radial(mech, grid, T, Y, rho, u, hs),
        "diagnostics": {
            "momentum_residual_max": round(
                float(np.max(np.abs(momentum_residual(u, grid, g_r)[0]))), 6
            ),
            "mass_relative_error": round(
                float(
                    (total_mass(rho, grid) - mass_initial - float(cfg.mass_flow_kg_s) * t)
                    / max(abs(mass_initial), 1e-30)
                ),
                8,
            ),
            "enthalpy_relative_change": round(
                float(
                    (total_enthalpy(mech, T, Y, rho, grid) - enthalpy_initial)
                    / max(abs(enthalpy_initial), 1e-30)
                ),
                8,
            ),
            "substeps_total": int(total_substeps),
            "substeps_capped": bool(substep_capped),
            "max_drho_over_rho": round(float(last_diag.get("drho_max_over_rho", 0.0)), 6),
            "chem_last": last_diag.get("chem", {}),
            "ignition": ignition_diag,
            "mechanism": mechanism_summary(mech),
            "geometry": {
                "type": "spherical_1d",
                "r_min_m": float(cfg.r_min_m),
                "r_max_m": float(cfg.r_max_m),
                "Nr": int(cfg.Nr),
                "nx_display": int(cfg.nx),
                "ny_display": int(cfg.ny),
            },
            "run_end_time_s": round(float(t), 6),
            "radial_gravity_m_per_s2": float(g_r),
            "boundary_mass_flux_kg_s": round(
                boundary_mass_flux(rho, u, grid, float(cfg.mass_flow_kg_s)), 10
            ),
        },
    }

    return {
        "frames": frames,
        "times": times,
        "history": history,
        "final": final,
        "radial_frames": radial_frames,
    }
