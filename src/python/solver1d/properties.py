"""Initial/boundary composition, flow diagnostics, and budget helpers (doc §1, §3, §5.1–5.3)."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from mechanism import Mechanism, R_UNIV
from .grid import RadialGrid


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def oxygen_stream_composition(mech: Mechanism, oxygen_pct: float, oxidizer: str) -> np.ndarray:
    """Mass fractions of the oxidizer stream (O2/N2), length n_species."""
    W = mech.W
    o2 = mech.key_to_index.get("O2")
    n2 = mech.key_to_index.get("N2")
    if o2 is None or n2 is None:
        raise ValueError("mechanism must include O2 and N2 for an air/O2 oxidizer stream")
    x_o2 = 1.0 if oxidizer == "O2" else min(max(oxygen_pct / 100.0, 1e-6), 1.0)
    y_o2 = x_o2 * W[o2] / (x_o2 * W[o2] + (1.0 - x_o2) * W[n2])
    y = np.zeros(len(W), dtype=np.float64)
    y[o2] = y_o2
    y[n2] = 1.0 - y_o2
    return y


def premixed_composition(
    mech: Mechanism,
    equivalence_ratio: float,
    oxygen_pct: float,
    oxidizer: str,
) -> np.ndarray:
    """Stoichiometric/off-stoichiometric premixed fuel+oxidizer mass fractions.

    For phi = (F/O) / (F/O)_stoich, one mole of fuel is paired with
    nu_O2/phi moles of O2; N2 is carried with the oxidizer stream.
    """
    W = mech.W
    fuel = mech.fuel_index
    o2 = mech.key_to_index.get("O2")
    n2 = mech.key_to_index.get("N2")
    if o2 is None:
        raise ValueError("mechanism has no O2 species")
    nu_o2 = float(mech.reaction.reactants.get("O2", 0.0))
    if nu_o2 <= 0.0:
        raise ValueError("reaction has no O2 reactant")
    phi = max(float(equivalence_ratio), 1e-6)
    x_o2 = 1.0 if oxidizer == "O2" else min(max(oxygen_pct / 100.0, 1e-6), 1.0)
    y_o2_stream = x_o2 * W[o2] / (x_o2 * W[o2] + (1.0 - x_o2) * W[n2]) if n2 is not None else 1.0
    y_n2_stream = 1.0 - y_o2_stream

    n_o2 = nu_o2 / phi
    mass_fuel = W[fuel]
    mass_o2 = n_o2 * W[o2]
    mass_n2 = mass_o2 * (y_n2_stream / y_o2_stream) if y_o2_stream > 1e-12 else 0.0
    total = mass_fuel + mass_o2 + mass_n2
    y = np.zeros(len(W), dtype=np.float64)
    y[fuel] = mass_fuel / total
    y[o2] = mass_o2 / total
    if n2 is not None:
        y[n2] = mass_n2 / total
    return y


def composition_from_dict(mech: Mechanism, mapping: dict[str, float]) -> np.ndarray:
    """Map a species-key -> mass-fraction dict onto the mechanism's species vector."""
    y = np.zeros(len(mech.W), dtype=np.float64)
    for key, value in mapping.items():
        if key in mech.key_to_index:
            y[mech.key_to_index[key]] = max(float(value), 0.0)
    total = float(y.sum())
    if total > 1.0 + 1e-9:
        y /= total
        total = 1.0
    n2 = mech.key_to_index.get("N2")
    if n2 is not None and total < 1.0:
        y[n2] += 1.0 - total
    return y


def boundary_compositions(
    cfg: Any,
    mech: Mechanism,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Return (Y_inner, Y_outer, T_inner, T_outer) for the radial boundaries."""
    t_in = float(cfg.inlet_temperature_k) if cfg.inlet_temperature_k is not None else float(cfg.ambient_temperature_k)
    t_out = float(cfg.ambient_temperature_k)

    if cfg.mixing_mode == "premixed":
        premixed = premixed_composition(mech, cfg.equivalence_ratio, cfg.oxygen_pct, cfg.oxidizer)
        y_inner = composition_from_dict(mech, cfg.fuel_inlet_composition) if cfg.fuel_inlet_composition else premixed
        y_outer = composition_from_dict(mech, cfg.oxidizer_inlet_composition) if cfg.oxidizer_inlet_composition else premixed
    else:
        if cfg.fuel_inlet_composition:
            y_inner = composition_from_dict(mech, cfg.fuel_inlet_composition)
        else:
            y_inner = np.zeros(len(mech.W), dtype=np.float64)
            y_inner[mech.fuel_index] = 1.0
        if cfg.oxidizer_inlet_composition:
            y_outer = composition_from_dict(mech, cfg.oxidizer_inlet_composition)
        else:
            y_outer = oxygen_stream_composition(mech, cfg.oxygen_pct, cfg.oxidizer)
    return y_inner, y_outer, t_in, t_out


def initial_composition(cfg: Any, mech: Mechanism, grid: RadialGrid) -> np.ndarray:
    """Initial species field, shape (Nr, n_species)."""
    y_inner, y_outer, _, _ = boundary_compositions(cfg, mech)
    if cfg.initial_species_mass_fractions:
        y0 = composition_from_dict(mech, cfg.initial_species_mass_fractions)
        return np.tile(y0, (grid.n_cells, 1))

    if cfg.mixing_mode == "premixed":
        premixed = premixed_composition(mech, cfg.equivalence_ratio, cfg.oxygen_pct, cfg.oxidizer)
        return np.tile(premixed, (grid.n_cells, 1))

    # Non-premixed literal 1D mapping: fuel-rich inner region, oxidizer outside.
    # A finite mixing layer is used so the 1D initialization has both reactants
    # present near the interface (the document does not prescribe a profile; R10).
    y = np.empty((grid.n_cells, len(mech.W)), dtype=np.float64)
    r_interface = 0.5 * (grid.r_min + grid.r_max)
    delta = max(float(cfg.ignition_region_m) * 0.5, 2.0 * grid.dr)
    weight = 0.5 * (1.0 + np.tanh((grid.r_centers - r_interface) / delta))
    y[:] = (1.0 - weight)[:, None] * y_inner[None, :] + weight[:, None] * y_outer[None, :]
    return y


# ---------------------------------------------------------------------------
# Ignition
# ---------------------------------------------------------------------------


def estimate_adiabatic_flame_temp(mech: Mechanism, t0: float, y_reactants: np.ndarray) -> float:
    """Constant-pressure adiabatic flame temperature from hf + sensible enthalpy."""
    fuel = mech.fuel_index
    o2 = mech.key_to_index.get("O2")
    if o2 is None:
        return 2500.0
    nu_f = -mech.nu[fuel]
    nu_o = -mech.nu[o2]
    if nu_f <= 0.0 or nu_o <= 0.0:
        return 2500.0
    dxi = min(y_reactants[fuel] / (mech.W[fuel] * nu_f), y_reactants[o2] / (mech.W[o2] * nu_o))
    y_prod = y_reactants + mech.nu * mech.W * dxi
    y_prod = np.maximum(y_prod, 0.0)
    if y_prod.sum() <= 0.0:
        return 2500.0
    y_prod /= y_prod.sum()
    h_react = float(np.dot(y_reactants, mech.hf_mass) + mech.hs_mix(t0, y_reactants))
    lo, hi = 200.0, 6000.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        h_prod = float(np.dot(y_prod, mech.hf_mass) + mech.hs_mix(mid, y_prod))
        if h_prod < h_react:
            lo = mid
        else:
            hi = mid
    return float(0.5 * (lo + hi))


def apply_ignition(
    cfg: Any,
    mech: Mechanism,
    grid: RadialGrid,
    temperature: np.ndarray,
    Y: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Hot kernel per the existing UI ignition controls."""
    t = np.array(temperature, dtype=np.float64, copy=True)
    if cfg.mixing_mode == "nonpremixed":
        centre = 0.5 * (grid.r_min + grid.r_max)
        mask = np.abs(grid.r_centers - centre) <= max(float(cfg.ignition_region_m), grid.dr)
    else:
        mask = grid.r_centers <= (grid.r_min + max(float(cfg.ignition_region_m), grid.dr))
    if not np.any(mask):
        mask[int(np.argmin(np.abs(grid.r_centers - (grid.r_min + grid.dr))))] = True

    y_kernel = Y[mask]
    rho_kernel = mech.density(t[mask], float(cfg.ambient_pressure_bar) * 1.0e5, y_kernel)
    cp_kernel = mech.cp_mix(t[mask], y_kernel)
    t_ad = estimate_adiabatic_flame_temp(mech, float(cfg.ambient_temperature_k), premixed_composition(
        mech, cfg.equivalence_ratio, cfg.oxygen_pct, cfg.oxidizer
    ) if cfg.mixing_mode == "premixed" else y_kernel.mean(axis=0))
    t_cap = min(t_ad + 300.0, 3500.0)

    if cfg.ignition_method == "energy_deposition":
        volume = float(np.sum(grid.cell_volume[mask]))
        mean_rho = float(np.mean(rho_kernel))
        mean_cp = float(np.mean(cp_kernel))
        delta_t = float(cfg.ignition_energy_j) / max(mean_rho * mean_cp * volume, 1e-30)
        t[mask] = np.minimum(t[mask] + delta_t, t_cap)
    else:
        t[mask] = np.minimum(float(cfg.ambient_temperature_k) + 1800.0, t_cap)

    return t, {
        "kernel_cells": int(np.count_nonzero(mask)),
        "kernel_radius_m": float(max(float(cfg.ignition_region_m), grid.dr)),
        "adiabatic_flame_temp_k_estimate": float(t_ad),
        "ignition_cap_k": float(t_cap),
    }


# ---------------------------------------------------------------------------
# Flow / budget diagnostics
# ---------------------------------------------------------------------------


def continuity_velocity(rho: np.ndarray, mass_flow_kg_s: float, grid: RadialGrid) -> np.ndarray:
    """Doc §5.1: u = mdot / (4π r² ρ)."""
    u = np.zeros(grid.n_cells, dtype=np.float64)
    if mass_flow_kg_s <= 0.0:
        return u
    valid = grid.r_centers > 0.0
    u[valid] = float(mass_flow_kg_s) / (
        4.0 * np.pi * grid.r_centers[valid] ** 2 * np.maximum(rho[valid], 1e-30)
    )
    return u


def momentum_residual(u: np.ndarray, grid: RadialGrid, g_r: float) -> tuple[np.ndarray, float]:
    """Doc §5.3: R_momentum = u du/dr - g_r (diagnostic only)."""
    dudr = grid.gradient(u)
    residual = np.asarray(u) * dudr - float(g_r)
    return residual, float(np.max(np.abs(residual))) if residual.size else 0.0


def total_mass(rho: np.ndarray, grid: RadialGrid) -> float:
    return float(np.sum(np.asarray(rho) * grid.cell_volume))


def total_enthalpy(mech: Mechanism, temperature: np.ndarray, Y: np.ndarray, rho: np.ndarray, grid: RadialGrid) -> float:
    sensible = mech.hs_mix(temperature, Y)
    formation = np.sum(Y * mech.hf_mass, axis=1)
    return float(np.sum(rho * (sensible + formation) * grid.cell_volume))


def boundary_mass_flux(rho: np.ndarray, u: np.ndarray, grid: RadialGrid, mass_flow_kg_s: float) -> float:
    """Net mass flux leaving through the outer boundary (inner inflow is mdot)."""
    if grid.n_cells == 0:
        return 0.0
    outflow = float(rho[-1]) * float(u[-1]) * float(grid.face_area[-1])
    return outflow


def flame_radius(temperature: np.ndarray, grid: RadialGrid, ambient_temperature: float) -> float:
    mask = np.asarray(temperature) > ambient_temperature + 200.0
    if not np.any(mask):
        return 0.0
    return float(np.max(grid.r_centers[mask]))


def volume_fraction(mask: np.ndarray, grid: RadialGrid) -> float:
    total = float(np.sum(grid.cell_volume))
    return float(np.sum(grid.cell_volume[np.asarray(mask, dtype=bool)])) / max(total, 1e-30)


def stability_score(quenched: bool, history: list[dict[str, Any]]) -> float:
    """Heuristic flame-stability score, 0-100 (existing UI contract)."""
    if quenched:
        return 8.0
    if not history:
        return 0.0
    peaks = [h["peak_temp_k"] for h in history]
    growth = max(peaks[-1] - peaks[0], 0.0)
    recent = peaks[-8:] if len(peaks) >= 8 else peaks
    drift = float(np.std(recent)) if recent else 0.0
    base = 60.0 + min(growth, 400.0) * 0.05
    return round(float(np.clip(base - drift * 0.02, 5.0, 99.0)), 1)
