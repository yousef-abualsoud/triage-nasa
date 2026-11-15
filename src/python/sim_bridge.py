"""
Solver seam. Tries the compiled pybind11 module (triage_core) first; falls back
to the NumPy 1D spherical reference implementation in solver1d/.

Contract (matches schema.py):
    run_simulation(config: dict, mechanism: dict) -> dict with keys
    frames, times, history, final (radial_frames optional)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from schema import SimConfig, SimResult

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUILD_DIR = REPO_ROOT / "build"
if BUILD_DIR.is_dir() and str(BUILD_DIR) not in sys.path:
    # A locally built triage_core .so lands in build/; make it importable
    # without requiring PYTHONPATH on every run.
    sys.path.insert(0, str(BUILD_DIR))


def _available_solver() -> str:
    try:
        import triage_core  # noqa: F401  (compiled pybind11 module)

        return "triage_core"
    except ImportError:
        return "reference"


def run(config: SimConfig) -> SimResult:
    """Run one simulation through the seam. Returns a normalized SimResult."""
    solver = _available_solver()
    if solver == "triage_core":
        import triage_core

        from mechanism import mechanism_payload

        raw = triage_core.run_simulation(
            config.model_dump(), mechanism_payload(config.resolved_mechanism())
        )
    else:
        from solver1d import run as run_reference

        raw = run_reference(config)
    return SimResult(config=config, solver=solver, **raw)


def _mock_run(config: SimConfig) -> dict[str, Any]:
    """Backwards-compatible alias for the pre-1D seam name."""
    from solver1d import run as run_reference

    return run_reference(config)
