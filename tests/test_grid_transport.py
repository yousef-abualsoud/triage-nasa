"""Radial grid, Thomas solver, and transport fidelity tests (doc §5.4, §5.7)."""

from __future__ import annotations

import numpy as np
import pytest

from solver1d.grid import RadialGrid
from solver1d.transport import (
    diffusive_fluxes,
    implicit_diffusion_1d,
    thomas,
    upwind_advection,
)


def test_spherical_geometry_matches_analytic_volume_and_area():
    grid = RadialGrid(0.0, 0.05, 200)
    assert np.sum(grid.cell_volume) == pytest.approx(4.0 / 3.0 * np.pi * 0.05**3, rel=1e-12)
    assert grid.face_area[0] == pytest.approx(0.0)
    assert grid.face_area[-1] == pytest.approx(4.0 * np.pi * 0.05**2, rel=1e-12)
    assert np.all(np.diff(grid.r_centers) > 0.0)


def test_thomas_solves_known_system():
    lower = np.array([0.0, -1.0, -1.0])
    diag = np.array([2.0, 2.0, 2.0])
    upper = np.array([-1.0, -1.0, 0.0])
    rhs = np.array([1.0, 0.0, 1.0])
    x = thomas(lower, diag, upper, rhs)
    assert np.allclose(x, np.ones(3))
    residual = np.r_[0.0, x[:-1]] * lower + diag * x + np.r_[x[1:], 0.0] * upper - rhs
    assert np.max(np.abs(residual)) < 1e-12


def test_implicit_diffusion_preserves_constant_field():
    grid = RadialGrid(0.0, 0.05, 100)
    field = np.full(grid.n_cells, 7.5)
    coef = grid.face_area * 1.0 / grid.dr
    scale = 1e-5 / grid.cell_volume
    out = implicit_diffusion_1d(
        field, 1e-5, grid, coef, scale, 7.5, 7.5, "fixed", "fixed"
    )
    assert np.allclose(out, 7.5, atol=1e-12)


def test_implicit_diffusion_decays_to_volume_weighted_mean():
    grid = RadialGrid(0.0, 0.05, 120)
    field = np.cos(np.pi * grid.r_centers / 0.05)
    coef = grid.face_area * 1.0 / grid.dr
    scale = 2e-4 / grid.cell_volume
    out = field
    for _ in range(80):
        out = implicit_diffusion_1d(
            out, 2e-4, grid, coef, scale, 0.0, 0.0, "zero_gradient", "zero_gradient"
        )
    weighted = np.sum(field * grid.cell_volume) / np.sum(grid.cell_volume)
    assert np.max(out) - np.min(out) < 1e-6
    assert out[0] == pytest.approx(weighted, rel=1e-6)


def test_upwind_advection_transports_a_profile():
    grid = RadialGrid(0.0, 0.05, 100)
    field = np.exp(-((grid.r_centers - 0.02) / 0.003) ** 2)
    u = np.full(grid.n_cells, 0.1)
    out = upwind_advection(field, u, 1e-4, grid, 0.0, 0.0, "zero_gradient", "zero_gradient")
    assert np.all(np.isfinite(out))
    assert out.shape == field.shape


def test_correction_velocity_makes_species_fluxes_sum_to_zero():
    grid = RadialGrid(0.0, 0.04, 80)
    rng = np.random.default_rng(3)
    Y = rng.random((grid.n_cells, 4))
    Y /= Y.sum(axis=1, keepdims=True)
    rho = np.full(grid.n_cells, 1.0)
    D_face = np.full((grid.n_cells + 1, 4), 2e-5)
    j_fick, v_corr, Y_face = diffusive_fluxes(
        Y, grid, rho, D_face, np.array([0.25, 0.25, 0.25, 0.25]),
        np.array([0.25, 0.25, 0.25, 0.25]), "fixed", "fixed"
    )
    j_total = j_fick + rho_face_for(grid)[:, None] * Y_face * v_corr[:, None]
    assert np.max(np.abs(np.sum(j_total, axis=1))) < 1e-10


def rho_face_for(grid: RadialGrid) -> np.ndarray:
    return grid.face_average(np.full(grid.n_cells, 1.0))
