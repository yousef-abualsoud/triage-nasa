"""C++ triage_core vs NumPy reference parity tests (document architecture)."""

from __future__ import annotations

import numpy as np
import pytest

from mechanism import mechanism_payload
from schema import SimConfig
import solver1d

try:
    import triage_core  # type: ignore
except ImportError:  # pragma: no cover - build not present
    triage_core = None


pytestmark = pytest.mark.skipif(
    triage_core is None,
    reason="triage_core C++ module not built (run cmake -B build ...)",
)


def test_cpp_matches_reference_on_short_run():
    cfg = SimConfig(
        Nr=64, nx=32, ny=32, iteration_count=10, dt_s=1e-3, output_interval_steps=5
    )
    ref = solver1d.run(cfg)
    raw = triage_core.run_simulation(
        cfg.model_dump(), mechanism_payload(cfg.resolved_mechanism())
    )
    assert len(raw["frames"]) == len(ref["frames"])
    assert raw["final"]["peak_temp_k"] == pytest.approx(ref["final"]["peak_temp_k"], abs=0.2)
    assert raw["final"]["max_flame_radius_m"] == pytest.approx(
        ref["final"]["max_flame_radius_m"], abs=1e-5
    )
    assert raw["final"]["stability"] == pytest.approx(ref["final"]["stability"], abs=0.2)
    assert raw["final"]["diagnostics"]["mass_relative_error"] == pytest.approx(
        ref["final"]["diagnostics"]["mass_relative_error"], abs=1e-4
    )

    frame_diff = np.max(
        np.abs(np.asarray(raw["frames"][-1]) - np.asarray(ref["frames"][-1]))
    )
    assert frame_diff < 1.0
    t_diff = np.max(
        np.abs(
            np.asarray(raw["final"]["radial"]["temperature_k"])
            - np.asarray(ref["final"]["radial"]["temperature_k"])
        )
    )
    assert t_diff < 1.0
    for key in raw["final"]["radial"]["mass_fractions"]:
        y_diff = np.max(
            np.abs(
                np.asarray(raw["final"]["radial"]["mass_fractions"][key])
                - np.asarray(ref["final"]["radial"]["mass_fractions"][key])
            )
        )
        assert y_diff < 5e-3


def test_cpp_matches_reference_for_mass_flow_case():
    cfg = SimConfig(
        Nr=64,
        nx=32,
        ny=32,
        iteration_count=6,
        dt_s=1e-3,
        output_interval_steps=3,
        mass_flow_kg_s=1e-6,
    )
    ref = solver1d.run(cfg)
    raw = triage_core.run_simulation(
        cfg.model_dump(), mechanism_payload(cfg.resolved_mechanism())
    )
    assert raw["final"]["peak_temp_k"] == pytest.approx(ref["final"]["peak_temp_k"], abs=0.5)
    assert raw["final"]["diagnostics"]["momentum_residual_max"] == pytest.approx(
        ref["final"]["diagnostics"]["momentum_residual_max"], abs=1e-3
    )
