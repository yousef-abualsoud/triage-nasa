"""1D spherical transport kernels: Thomas solve, implicit diffusion, upwind advection, diffusive fluxes."""

from __future__ import annotations

import numpy as np

from .grid import RadialGrid


def thomas(lower: np.ndarray, diag: np.ndarray, upper: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    """Solve a tridiagonal system A x = rhs.

    lower[0] and upper[-1] are ignored. The arrays are not modified.
    """
    n = diag.size
    if n == 0:
        return np.empty(0)
    if n == 1:
        return np.array([rhs[0] / diag[0]], dtype=np.float64)
    c = np.array(upper, dtype=np.float64, copy=True)
    d = np.array(rhs, dtype=np.float64, copy=True)
    b = np.array(diag, dtype=np.float64, copy=True)
    a = np.array(lower, dtype=np.float64, copy=True)
    c[0] = c[0] / b[0]
    d[0] = d[0] / b[0]
    for i in range(1, n):
        denom = b[i] - a[i] * c[i - 1]
        if abs(denom) < 1e-30:
            denom = 1e-30 if denom >= 0.0 else -1e-30
        c[i] = c[i] / denom if i < n - 1 else 0.0
        d[i] = (d[i] - a[i] * d[i - 1]) / denom
    x = np.empty(n, dtype=np.float64)
    x[-1] = d[-1]
    for i in range(n - 2, -1, -1):
        x[i] = d[i] - c[i] * x[i + 1]
    return x


def implicit_diffusion_1d(
    values: np.ndarray,
    dt: float,
    grid: RadialGrid,
    face_coefficient: np.ndarray,
    cell_scale: np.ndarray,
    ghost_inner: float,
    ghost_outer: float,
    bc_inner: str,
    bc_outer: str,
) -> np.ndarray:
    """Implicit spherical diffusion for one scalar field.

    The discretized term is

        F_i^{n+1} = F_i^n + dt/(ρ_i V_i) *
            [ A_{i+1/2} κ_{i+1/2} (F_{i+1}-F_i)/dr
            - A_{i-1/2} κ_{i-1/2} (F_i-F_{i-1})/dr ]

    where `face_coefficient` = A κ / dr and `cell_scale` = dt/(ρ_i V_i).
    For the energy equation κ = λ and the caller divides by cp in
    `cell_scale`; for species κ = ρ D.
    """
    f = np.asarray(values, dtype=np.float64)
    coef = np.array(face_coefficient, dtype=np.float64, copy=True)
    scale = np.asarray(cell_scale, dtype=np.float64)
    n = f.size

    if bc_inner != "fixed":
        coef[0] = 0.0
    if bc_outer != "fixed":
        coef[-1] = 0.0

    lower = np.zeros(n, dtype=np.float64)
    diag = np.ones(n, dtype=np.float64)
    upper = np.zeros(n, dtype=np.float64)
    rhs = f.copy()

    if n > 1:
        lower[1:] = -scale[1:] * coef[1:-1]
        upper[:-1] = -scale[:-1] * coef[1:-1]
    diag[:] = 1.0 + scale * (coef[:-1] + coef[1:])

    if bc_inner == "fixed":
        rhs[0] += scale[0] * coef[0] * float(ghost_inner)
    if bc_outer == "fixed":
        rhs[-1] += scale[-1] * coef[-1] * float(ghost_outer)

    return thomas(lower, diag, upper, rhs)


def implicit_diffusion_species(
    Y: np.ndarray,
    dt: float,
    grid: RadialGrid,
    rho: np.ndarray,
    D_face: np.ndarray,
    Y_inner: np.ndarray,
    Y_outer: np.ndarray,
    bc_inner: str,
    bc_outer: str,
) -> np.ndarray:
    """Implicit species diffusion with ρ at faces (uncorrected Fickian part)."""
    n_cells, n_species = Y.shape
    rho_face = grid.face_average(rho)
    out = np.empty_like(Y)
    for k in range(n_species):
        face_coef = grid.face_area * rho_face * D_face[:, k] / grid.dr
        scale = dt / (np.maximum(rho, 1e-30) * grid.cell_volume)
        out[:, k] = implicit_diffusion_1d(
            Y[:, k],
            dt,
            grid,
            face_coef,
            scale,
            float(Y_inner[k]),
            float(Y_outer[k]),
            bc_inner,
            bc_outer,
        )
    return out


def implicit_diffusion_temperature(
    T: np.ndarray,
    dt: float,
    grid: RadialGrid,
    rho: np.ndarray,
    cp: np.ndarray,
    lambda_face: np.ndarray,
    T_inner: float,
    T_outer: float,
    bc_inner: str,
    bc_outer: str,
) -> np.ndarray:
    """Implicit conduction for T with the doc's (1/(ρ r²))∂(r² λ ∂T/∂r) term."""
    face_coef = grid.face_area * lambda_face / grid.dr
    scale = dt / (np.maximum(rho, 1e-30) * np.maximum(cp, 1.0) * grid.cell_volume)
    return implicit_diffusion_1d(
        T, dt, grid, face_coef, scale, T_inner, T_outer, bc_inner, bc_outer
    )


def upwind_advection(
    F: np.ndarray,
    u: np.ndarray,
    dt: float,
    grid: RadialGrid,
    ghost_inner: np.ndarray | float,
    ghost_outer: np.ndarray | float,
    bc_inner: str,
    bc_outer: str,
) -> np.ndarray:
    """Explicit first-order upwind update of -u ∂F/∂r for a scalar or species matrix."""
    arr = np.asarray(F, dtype=np.float64)
    vel = np.asarray(u, dtype=np.float64)
    scalar = arr.ndim == 1
    if scalar:
        arr = arr[:, None]
    ghost_in = np.asarray(ghost_inner, dtype=np.float64)
    ghost_out = np.asarray(ghost_outer, dtype=np.float64)
    if ghost_in.ndim == 0:
        ghost_in = np.full(arr.shape[1], float(ghost_in))
    if ghost_out.ndim == 0:
        ghost_out = np.full(arr.shape[1], float(ghost_out))

    # Build the left/right neighbor arrays with ghost values.
    left = np.empty_like(arr)
    right = np.empty_like(arr)
    left[0] = ghost_in if bc_inner == "fixed" else arr[0]
    left[1:] = arr[:-1]
    right[-1] = ghost_out if bc_outer == "fixed" else arr[-1]
    right[:-1] = arr[1:]

    grad = np.empty_like(arr)
    pos = vel >= 0.0
    grad[pos] = (arr[pos] - left[pos]) / grid.dr
    grad[~pos] = (right[~pos] - arr[~pos]) / grid.dr
    out = arr - dt * vel[:, None] * grad
    return out[:, 0] if scalar else out


def face_gradients(
    F: np.ndarray,
    grid: RadialGrid,
    ghost_inner: np.ndarray,
    ghost_outer: np.ndarray,
    bc_inner: str,
    bc_outer: str,
) -> np.ndarray:
    """Gradient at radial faces, shape (Nr+1, n_species)."""
    arr = np.asarray(F, dtype=np.float64)
    scalar = arr.ndim == 1
    if scalar:
        arr = arr[:, None]
    gi = np.asarray(ghost_inner, dtype=np.float64)
    go = np.asarray(ghost_outer, dtype=np.float64)
    if gi.ndim == 0:
        gi = np.full(arr.shape[1], float(gi))
    if go.ndim == 0:
        go = np.full(arr.shape[1], float(go))
    grad = np.empty((grid.n_cells + 1, arr.shape[1]), dtype=np.float64)
    grad[1:-1] = (arr[1:] - arr[:-1]) / grid.dr
    grad[0] = (arr[0] - gi) / grid.dr if bc_inner == "fixed" else 0.0
    grad[-1] = (go - arr[-1]) / grid.dr if bc_outer == "fixed" else 0.0
    return grad[:, 0] if scalar else grad


def diffusive_fluxes(
    Y: np.ndarray,
    grid: RadialGrid,
    rho: np.ndarray,
    D_face: np.ndarray,
    Y_inner: np.ndarray,
    Y_outer: np.ndarray,
    bc_inner: str,
    bc_outer: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (Fickian j_faces, correction velocity, Y_face).

    j = -ρ D ∂Y/∂r, and the correction velocity V_c = Σ D ∂Y/∂r makes the
    corrected flux j_i + ρ Y_i V_c sum to zero across species.
    """
    grad = face_gradients(Y, grid, Y_inner, Y_outer, bc_inner, bc_outer)
    rho_face = grid.face_average(rho)
    j_faces = -rho_face[:, None] * D_face * grad
    v_corr = np.sum(D_face * grad, axis=1)
    Y_face = grid.face_average(Y)
    return j_faces, v_corr, Y_face


def species_enthalpy_flux(
    hs_species: np.ndarray,
    j_faces: np.ndarray,
    grid: RadialGrid,
) -> np.ndarray:
    """Σ_i h_s,i j_i at faces, W/m²."""
    hs_face = grid.face_average(hs_species)  # (Nr+1, n_species)
    return np.sum(hs_face * j_faces, axis=1)
