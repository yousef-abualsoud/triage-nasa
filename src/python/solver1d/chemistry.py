"""Reaction-rate and chemical-heat-release integration (doc §5.5–5.6)."""

from __future__ import annotations

from typing import Any

import numpy as np

from mechanism import Mechanism


def integrate_chemistry(
    mech: Mechanism,
    temperature: np.ndarray,
    Y: np.ndarray,
    rho: np.ndarray,
    dt: float,
    max_delta_t: float = 200.0,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Advance the local single-reaction chemistry over `dt`.

    The rate is evaluated exactly from the document:

        xi_dot = A T^beta exp(-Ea/(Ru T)) prod_i C_i^alpha_i
        omega_i = W_i nu_i xi_dot
        q_dot   = -sum_i hf_i omega_i

    The update is limited by the available reactants and by a maximum
    temperature rise per substep. The latter is a numerical safeguard for the
    stiff inherited A values (R6/R17); it does not modify the rate expression.
    """
    t = np.asarray(temperature, dtype=np.float64)
    y = np.asarray(Y, dtype=np.float64)
    r = np.asarray(rho, dtype=np.float64)
    n_cells, n_species = y.shape

    c = mech.concentrations(r, y)
    xi_dot = mech.rate_of_progress(t, c)  # mol/(m^3 s)

    # Extent available from each reactant (nu_i < 0).
    xi_limit = np.full(n_cells, np.inf, dtype=np.float64)
    for k in range(n_species):
        nu = mech.nu[k]
        if nu < 0.0:
            available = r * np.maximum(y[:, k], 0.0) / (mech.W[k] * (-nu))
            xi_limit = np.minimum(xi_limit, available)
    xi_limit = np.where(np.isfinite(xi_limit), np.maximum(xi_limit, 0.0), 0.0)

    cp = np.maximum(mech.cp_mix(t, y), 1.0)
    d_h = float(mech.heat_of_reaction_j_per_mol_fuel)
    if d_h > 1e-30:
        xi_limit_t = max_delta_t * r * cp / d_h
        xi_limit = np.minimum(xi_limit, xi_limit_t)

    dxi = np.minimum(xi_dot * float(dt), xi_limit)
    dxi = np.maximum(dxi, 0.0)
    active = dxi > 0.0

    if not np.any(active):
        return t, y, {
            "xi_dot_max": float(np.max(xi_dot)) if xi_dot.size else 0.0,
            "xi_actual_max": 0.0,
            "heat_release_max_w_m3": 0.0,
            "reacted_extent_mol_m3": 0.0,
        }

    hs_old = mech.hs_mix(t, y)
    y_new = y + (mech.nu[None, :] * mech.W[None, :] / np.maximum(r, 1e-30)[:, None]) * dxi[:, None]
    y_new = np.maximum(y_new, 0.0)
    sums = np.sum(y_new, axis=1, keepdims=True)
    safe = sums[:, 0] > 1e-12
    y_new[safe] = y_new[safe] / sums[safe]
    y_new[~safe] = y[~safe]

    hs_new = hs_old + d_h * dxi / np.maximum(r, 1e-30)
    t_new = mech.temperature_from_hs(hs_new, y_new, t)
    t_new = np.clip(t_new, 200.0, 6000.0)

    q_dot = d_h * dxi / max(float(dt), 1e-30)
    return t_new, y_new, {
        "xi_dot_max": float(np.max(xi_dot)) if xi_dot.size else 0.0,
        "xi_actual_max": float(np.max(dxi / max(float(dt), 1e-30))),
        "heat_release_max_w_m3": float(np.max(q_dot)) if q_dot.size else 0.0,
        "reacted_extent_mol_m3": float(np.sum(dxi)),
    }
