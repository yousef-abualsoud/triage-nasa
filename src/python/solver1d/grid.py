"""Cell-centered 1D spherical radial grid and frame painting."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class RadialGrid:
    r_min: float
    r_max: float
    n_cells: int

    def __post_init__(self) -> None:
        if self.n_cells < 1:
            raise ValueError("n_cells must be >= 1")
        if self.r_max <= self.r_min:
            raise ValueError("r_max must be > r_min")
        self.dr = (self.r_max - self.r_min) / self.n_cells
        self.r_faces = np.linspace(self.r_min, self.r_max, self.n_cells + 1)
        self.r_centers = self.r_min + (np.arange(self.n_cells) + 0.5) * self.dr
        # Spherical face areas and shell volumes.
        self.face_area = 4.0 * np.pi * self.r_faces**2
        self.cell_volume = (4.0 * np.pi / 3.0) * (
            self.r_faces[1:] ** 3 - self.r_faces[:-1] ** 3
        )
        if np.any(self.cell_volume <= 0.0):
            raise ValueError("non-positive radial cell volume")

    # -- geometry helpers --------------------------------------------------
    def face_average(self, cell_values: np.ndarray) -> np.ndarray:
        """Arithmetic average of a cell-centered field onto the faces."""
        arr = np.asarray(cell_values, dtype=np.float64)
        shape = (self.n_cells + 1,) + arr.shape[1:]
        faces = np.empty(shape, dtype=np.float64)
        faces[0] = arr[0]
        faces[-1] = arr[-1]
        faces[1:-1] = 0.5 * (arr[:-1] + arr[1:])
        return faces

    def gradient(self, cell_values: np.ndarray) -> np.ndarray:
        """Second-order central gradient at cell centers (one-sided at ends)."""
        arr = np.asarray(cell_values, dtype=np.float64)
        grad = np.empty_like(arr)
        if self.n_cells == 1:
            grad[...] = 0.0
            return grad
        grad[1:-1] = (arr[2:] - arr[:-2]) / (2.0 * self.dr)
        grad[0] = (arr[1] - arr[0]) / self.dr
        grad[-1] = (arr[-1] - arr[-2]) / self.dr
        return grad

    def face_gradient(self, cell_values: np.ndarray) -> np.ndarray:
        """Gradient at interior faces; boundary faces use one-sided differences."""
        arr = np.asarray(cell_values, dtype=np.float64)
        shape = (self.n_cells + 1,) + arr.shape[1:]
        faces = np.empty(shape, dtype=np.float64)
        faces[1:-1] = (arr[1:] - arr[:-1]) / self.dr
        faces[0] = (arr[0] - arr[1]) / self.dr
        faces[-1] = (arr[-1] - arr[-2]) / self.dr
        return faces

    def divergence(self, face_flux: np.ndarray) -> np.ndarray:
        """(1/V_i) * (A_{i+1/2} F_{i+1/2} - A_{i-1/2} F_{i-1/2})."""
        flux = np.asarray(face_flux, dtype=np.float64)
        if flux.ndim == 1:
            return (self.face_area[1:] * flux[1:] - self.face_area[:-1] * flux[:-1]) / self.cell_volume
        area = self.face_area[:, np.newaxis]
        return (area[1:] * flux[1:] - area[:-1] * flux[:-1]) / self.cell_volume[:, np.newaxis]

    # -- frame painting ----------------------------------------------------
    def paint_temperature(
        self,
        temperature: np.ndarray,
        nx: int,
        ny: int,
        inner_temperature: float,
        outer_temperature: float,
    ) -> list[list[float]]:
        """Paint the 1D radial T field onto a centered [ny][nx] display grid.

        The display square spans [-r_max, +r_max] in both axes. Cells inside
        r_min use the inner boundary temperature; cells outside r_max use the
        outer/ambient temperature. A centered radial field revolved by the
        existing 3D shader therefore becomes a true spherical field.
        """
        length = 2.0 * self.r_max
        x = -length / 2.0 + (np.arange(nx) + 0.5) * (length / nx)
        y = -length / 2.0 + (np.arange(ny) + 0.5) * (length / ny)
        xx, yy = np.meshgrid(x, y)  # [ny][nx]
        rr = np.hypot(xx, yy)
        flat = np.interp(
            rr.ravel(),
            self.r_centers,
            np.asarray(temperature, dtype=np.float64),
            left=float(temperature[0]),
            right=float(temperature[-1]),
        ).reshape(rr.shape)
        flat = np.where(rr <= self.r_min, inner_temperature, flat)
        flat = np.where(rr >= self.r_max, outer_temperature, flat)
        return np.round(flat, 1).astype(np.float32).tolist()
