"""End-to-end 1D spherical solver tests (doc §6–§7)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from schema import SimConfig
from solver1d import run


SMALL = dict(Nr=64, nx=32, ny=32, iteration_count=20, dt_s=1e-3, output_interval_steps=10)


def test_run_returns_the_seam_contract_and_finite_fields():
    cfg = SimConfig(**SMALL)
    result = run(cfg)
    assert set(result) >= {"frames", "times", "history", "final", "radial_frames"}
    assert len(result["frames"]) == len(result["times"]) == len(result["history"])
    assert len(result["frames"]) > 0
    frame = np.asarray(result["frames"][-1])
    assert frame.shape == (cfg.ny, cfg.nx)
    assert np.all(np.isfinite(frame))
    assert frame.min() >= 200.0 and frame.max() <= 6000.0

    radial = result["final"]["radial"]
    for key in (
        "r_m",
        "temperature_k",
        "density_kg_m3",
        "velocity_ms",
        "mass_fractions",
        "molar_concentrations_mol_m3",
        "reaction_rate_mol_m3_s",
        "production_rates_kg_m3_s",
        "heat_release_w_m3",
        "molecular_weight_kg_mol",
    ):
        assert key in radial
    assert len(radial["r_m"]) == cfg.Nr
    for key in result["final"]["diagnostics"]["mechanism"]["species"]:
        assert key in radial["mass_fractions"]


def test_history_starts_at_the_run_origin():
    cfg = SimConfig(**{**SMALL, "iteration_count": 20})
    result = run(cfg)
    # The dashboard graphs anchor every x axis at 0, so the streamed series
    # must include the pre-run state rather than starting at step 10.
    assert result["times"][0] == 0.0
    assert result["history"][0]["t_s"] == 0.0
    assert result["history"][0]["iteration"] == 0
    assert all("iteration" in row for row in result["history"])
    assert result["history"][-1]["iteration"] == cfg.iteration_count


def test_species_mass_fractions_are_nonnegative_and_normalized():
    cfg = SimConfig(**SMALL)
    result = run(cfg)
    radial = result["final"]["radial"]
    Y = np.stack([np.asarray(v) for v in radial["mass_fractions"].values()], axis=1)
    assert np.all(Y >= -1e-10)
    assert np.allclose(Y.sum(axis=1), 1.0, atol=1e-8)


def test_eos_and_continuity_diagnostics_are_consistent():
    cfg = SimConfig(**SMALL)
    result = run(cfg)
    rad = result["final"]["radial"]
    T = np.asarray(rad["temperature_k"])
    Y = np.stack([np.asarray(v) for v in rad["mass_fractions"].values()], axis=1)
    rho = np.asarray(rad["density_kg_m3"])
    mech = cfg.resolved_mechanism()
    # final radial arrays are rounded for JSON transport; compare at 1e-6.
    assert np.allclose(rho, mech.density(T, cfg.ambient_pressure_bar * 1e5, Y), rtol=1e-5, atol=1e-8)
    # Zero mass flow => zero continuity velocity.
    assert np.max(np.abs(np.asarray(rad["velocity_ms"]))) < 1e-12


def test_continuity_velocity_matches_documented_formula_for_mass_flow():
    cfg = SimConfig(**{**SMALL, "mass_flow_kg_s": 1e-6, "iteration_count": 5})
    result = run(cfg)
    rad = result["final"]["radial"]
    r = np.asarray(rad["r_m"])
    rho = np.asarray(rad["density_kg_m3"])
    u = np.asarray(rad["velocity_ms"])
    expected = cfg.mass_flow_kg_s / (4.0 * math.pi * r**2 * rho)
    assert np.allclose(u, expected, rtol=1e-5, atol=1e-10)
    assert result["final"]["diagnostics"]["momentum_residual_max"] > 0.0


def test_premixed_ch4_air_flame_grows_and_paints_a_centered_sphere():
    cfg = SimConfig(**{**SMALL, "iteration_count": 40})
    result = run(cfg)
    assert result["final"]["peak_temp_k"] > 1000.0
    assert result["final"]["max_flame_radius_m"] > 0.0
    frame = np.asarray(result["frames"][-1])
    cy, cx = frame.shape[0] // 2, frame.shape[1] // 2
    assert frame[cy, cx] > frame[0, 0]
    assert frame[0, 0] == pytest.approx(cfg.ambient_temperature_k, abs=1.0)


def test_nonpremixed_hot_spot_ignites():
    cfg = SimConfig(
        **{
            **SMALL,
            "mixing_mode": "nonpremixed",
            "ignition_method": "hot_spot",
            "iteration_count": 40,
        }
    )
    result = run(cfg)
    assert result["final"]["peak_temp_k"] > 1000.0
    assert result["final"]["quenched"] is False


def test_all_fuels_run():
    for fuel in ("CH4", "C2H4", "C3H8", "H2"):
        cfg = SimConfig(**{**SMALL, "fuel": fuel, "iteration_count": 10})
        result = run(cfg)
        assert np.isfinite(result["final"]["peak_temp_k"])
        assert result["final"]["peak_temp_k"] > cfg.ambient_temperature_k


def test_t_end_is_authoritative_and_updates_iteration_count():
    cfg = SimConfig(dt_s=1e-3, t_end_s=0.25)
    assert cfg.iteration_count == 250
    assert cfg.run_end_time_s() == pytest.approx(0.25)


def test_invalid_spherical_domain_is_rejected():
    with pytest.raises(Exception):
        SimConfig(r_min_m=0.05, r_max_m=0.01)
    with pytest.raises(Exception):
        SimConfig(r_min_m=0.0, mass_flow_kg_s=1e-6)
