"""
Solver seam. Tries the compiled pybind11 module (triage_core) first; falls back to
the NumPy reference mock so the entire pipeline is testable before src/cpp lands.

Contract (must match schema.py docstring):
    run_simulation(config: dict) -> dict with keys: frames, times, history, final
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import CONSTANTS, SimConfig, SimResult  # noqa: E402

R_UNIV = CONSTANTS["physical_constants"]["universal_gas_constant_j_per_molK"]


def _available_solver() -> str:
    try:
        import triage_core  # noqa: F401  (compiled pybind11 module)

        return "triage_core"
    except ImportError:
        return "mock"


def run(config: SimConfig) -> SimResult:
    """Run one simulation through the seam. Returns a normalized SimResult."""
    solver = _available_solver()
    if solver == "triage_core":
        import triage_core

        raw = triage_core.run_simulation(config.model_dump())
    else:
        raw = _mock_run(config)
    return SimResult(config=config, solver=solver, **raw)


# ----------------------------------------------------------------------------
# NumPy reference mock: 2D reaction-diffusion with phenomenological buoyancy.
# Not intended as final physics -- a stand-in so ingestion/triage/UI can be
# built and demoed before the C++ ADI/Thomas solver is slotted in.
# ----------------------------------------------------------------------------

MOCK_RHO = 1.16  # kg/m3, air-like at 300 K


def _o2_mass_fraction(oxygen_pct: float) -> float:
    """Mole-fraction O2 -> mass fraction (balance N2)."""
    x = min(oxygen_pct / 100.0, 1.0)
    return (x * 32.0) / (x * 32.0 + (1.0 - x) * 28.0)


def _mock_run(cfg: SimConfig) -> dict[str, Any]:
    chem = cfg.resolved_chemistry()
    g_mag, _g_jit = cfg.gravity()
    n_steps = int(cfg.end_time_s / cfg.dt_s)

    x = np.linspace(-cfg.domain_length_m / 2.0, cfg.domain_length_m / 2.0, cfg.nx)
    y = np.linspace(-cfg.domain_height_m / 2.0, cfg.domain_height_m / 2.0, cfg.ny)
    X, Y = np.meshgrid(x, y)  # row-major [ny][nx]
    R = np.hypot(X, Y)

    T = np.full((cfg.ny, cfg.nx), cfg.ambient_temperature_k, dtype=np.float64)
    ignited = R <= cfg.ignition_region_m
    # Ignition cap: a spark cannot exceed a plausible hot-source temperature.
    t_ig_cap = min(
        chem.get("adiabatic_flame_temp_k", 2400.0) + 300.0, 3000.0
    )
    if cfg.ignition_method == "energy_deposition":
        T[ignited] += min(cfg.ignition_energy_j * 4.0e3, t_ig_cap - cfg.ambient_temperature_k)
    else:  # hot_spot
        T[ignited] = min(cfg.ambient_temperature_k + 1800.0, t_ig_cap)

    Y_F = np.zeros((cfg.ny, cfg.nx))
    Y_F[ignited] = 0.08
    Y_O2 = np.full((cfg.ny, cfg.nx), _o2_mass_fraction(cfg.oxygen_pct))

    D = chem["species_diffusivity_m2_per_s"]
    alpha = chem["thermal_conductivity_w_per_mK"] / (
        chem["specific_heat_j_per_kgK"] * MOCK_RHO
    )
    Ea_over_R = chem["activation_energy_j_per_mol"] / R_UNIV
    A = chem["pre_exponential_factor"]
    nu_f = chem.get("reaction_order_fuel", 0.5)
    nu_o = chem.get("reaction_order_oxygen", 1.0)
    stoich_o2 = 0.5  # kg O2 per kg fuel (approx for hydrocarbons)

    dx = cfg.domain_length_m / cfg.nx
    dy = cfg.domain_height_m / cfg.ny
    dx2, dy2 = dx * dx, dy * dy

    frames: list[list[list[float]]] = []
    times: list[float] = []
    history: list[dict[str, Any]] = []

    peak_T = float(T.max())
    quenched = False
    quench_t = None

    for step in range(1, n_steps + 1):
        t = step * cfg.dt_s

        # Buoyant advection: upward drift proportional to g and local heat.
        if g_mag > 0.1:
            v_buoy = g_mag * 2.0e-3 * (T / cfg.ambient_temperature_k - 1.0)
            T = _upwind_shift(T, v_buoy, cfg.dt_s, dy)
            Y_F = _upwind_shift(Y_F, v_buoy, cfg.dt_s, dy)
            Y_O2 = _upwind_shift(Y_O2, v_buoy, cfg.dt_s, dy)

        # Inlet advection (Saffire mode): right-to-left drift.
        if cfg.inlet_velocity_ms > 0:
            cfl = min(cfg.inlet_velocity_ms * cfg.dt_s / dx, 0.4)
            for F in (T, Y_F, Y_O2):
                F[1:-1, 1:-1] += cfl * (F[1:-1, 1:-1] - F[1:-1, 2:])

        # Diffusion (Fick / Fourier), explicit kernel.
        T = _diffuse(T, alpha, cfg.dt_s, dx2, dy2)
        Y_F = _diffuse(Y_F, D, cfg.dt_s, dx2, dy2)
        Y_O2 = _diffuse(Y_O2, D, cfg.dt_s, dx2, dy2)

        # Arrhenius source (single-step, reduced approximation).
        omega = (
            A
            * np.exp(-Ea_over_R / np.maximum(T, 300.0))
            * np.maximum(Y_F, 0.0) ** nu_f
            * np.maximum(Y_O2, 0.0) ** nu_o
        )
        dY = np.minimum(omega * cfg.dt_s, np.minimum(Y_F, Y_O2 / stoich_o2))
        release = dY * chem["lower_heating_value_j_per_kg"]
        T += release / (chem["specific_heat_j_per_kgK"] * MOCK_RHO)
        Y_F = np.clip(Y_F - dY, 0.0, 1.0)
        Y_O2 = np.clip(Y_O2 - dY * stoich_o2, 0.0, 1.0)
        # Cap at a physically motivated ceiling: adiabatic flame temp + margin.
        t_cap = chem.get("adiabatic_flame_temp_k", 2400.0) * cfg.ambient_pressure_bar ** 0.1
        T = np.clip(T, cfg.ambient_temperature_k, min(t_cap + 300.0, 3500.0))

        # Quenching: flame dies when peak temp collapses toward ambient.
        if not quenched and float(T.max()) < cfg.ambient_temperature_k + 150.0:
            quenched = True
            quench_t = t

        if step % cfg.output_interval_steps == 0:
            flame = T > cfg.ambient_temperature_k + 200.0
            area = float(np.count_nonzero(flame)) * dx * dy
            radius = np.sqrt(max(area / np.pi, 0.0))
            frames.append(T.astype(np.float32).round(1).tolist())
            times.append(round(t, 4))
            history.append(
                {
                    "t_s": round(t, 4),
                    "max_flame_radius_m": round(float(radius), 5),
                    "peak_temp_k": round(float(T.max()), 1),
                    "mean_temp_k": round(float(T.mean()), 1),
                    "fuel_burned_fraction": round(
                        float(1.0 - Y_F.mean() / 0.08), 4
                    ),
                    "soot_index": round(_soot_index(cfg, chem, float(flame.mean())), 4),
                    "buoyancy_ke": round(g_mag * float(radius), 5),
                }
            )

        peak_T = max(peak_T, float(T.max()))

    final_flame = T > cfg.ambient_temperature_k + 200.0
    final_area = float(np.count_nonzero(final_flame)) * dx * dy
    max_radius = np.sqrt(max(final_area / np.pi, 0.0))
    soot_vf = _soot_index(cfg, chem, float(final_flame.mean())) * 1e-3

    return {
        "frames": frames,
        "times": times,
        "history": history,
        "final": {
            "quenched": bool(quenched),
            "quench_time_s": quench_t,
            "peak_temp_k": round(peak_T, 1),
            "max_flame_radius_m": round(float(max_radius), 5),
            "soot_volume_fraction": round(float(soot_vf), 5),
            "stability": _stability_score(quenched, history),
        },
    }


def _soot_index(cfg: SimConfig, chem: dict, flame_frac: float) -> float:
    """Phenomenological soot yield score from fuel tendency, pressure, O2, gravity."""
    tend = chem.get("soot_tendency_index", 0.1)
    return float(
        tend
        * flame_frac
        * np.sqrt(cfg.ambient_pressure_bar)
        * (1.0 - min(cfg.oxygen_pct / 100.0, 0.95))
        * 10.0
    )


def _diffuse(F: np.ndarray, coeff: float, dt: float, dx2: float, dy2: float) -> np.ndarray:
    lap_y = (np.roll(F, 1, axis=0) + np.roll(F, -1, axis=0) - 2.0 * F) / dy2
    lap_x = (np.roll(F, 1, axis=1) + np.roll(F, -1, axis=1) - 2.0 * F) / dx2
    return F + coeff * dt * (lap_x + lap_y)


def _upwind_shift(F: np.ndarray, v: np.ndarray, dt: float, dy: float) -> np.ndarray:
    """Upwind vertical advection with a per-cell velocity field (y grows downward)."""
    shift = np.clip(v * dt / dy, -0.4, 0.4)
    below = np.roll(F, 1, axis=0)
    above = np.roll(F, -1, axis=0)
    pos = np.clip(shift, 0.0, None)
    neg = np.clip(-shift, 0.0, None)
    return F * (1.0 - pos - neg) + below * pos + above * neg


def _stability_score(quenched: bool, history: list[dict]) -> float:
    """Heuristic flame-stability score, 0-100. Placeholder until C++ solver lands."""
    if quenched:
        return 8.0
    if not history:
        return 0.0
    peaks = [h["peak_temp_k"] for h in history]
    growth = max(peaks[-1] - peaks[0], 0.0)
    recent = peaks[-8:] if len(peaks) >= 8 else peaks
    drift = float(np.std(recent)) if recent else 0.0
    base = 60.0 + min(growth, 400.0) * 0.05
    # Gentle drift penalty; only severe oscillation tanks the score.
    return round(float(np.clip(base - drift * 0.02, 5.0, 99.0)), 1)