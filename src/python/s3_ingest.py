"""
PSI ground-truth entry point (legacy module name kept for imports).

Real data path
--------------
``psi_repo.py`` talks to the public NASA PSI repository API and ships a curated
ACME s-Flame (PSI-23) dataset in ``data/psi/sflame_runs.json``. This module
loads that dataset when present.

Offline fallback
----------------
If no curated dataset exists (fresh clone without network, or a stripped
deployment), deterministic surrogate telemetry is generated so the dashboard
and triage pipeline still work. Surrogates are labelled ``source="synthetic"``
and must never be presented as NASA measurements.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import UnifiedPayload  # noqa: E402
from psi_repo import build_sflame_runs, load_curated_ground_truth  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"


# ---------------------------------------------------------------------------
# Synthetic ground truth (explicit offline fallback)
# ---------------------------------------------------------------------------

def generate_synthetic_runs() -> list[dict[str, Any]]:
    """Deterministic surrogate telemetry approximating ACME/Saffire-style runs.

    Physics shape: spherical diffusion flames in micro-g scale with
    R ~ sqrt(D t) growth, faster convective burn + quench in airflow, O2 %
    below ~15% suppresses peak temperature, pressure broadens flames.
    """
    rng = _SeededRng(20261114)
    runs: list[dict[str, Any]] = []
    fuels = ("CH4", "C2H4", "C3H8", "H2")
    gravities = ("zero_g", "iss_micro_g", "earth_1g")
    experiments = (
        ("ACME_sflame", 0.0),
        ("ACME_coflow", 0.15),
        ("Saffire_vent", 0.55),
    )
    for exp_name, u_in in experiments:
        for i in range(24):
            fuel = fuels[int(rng.next() * len(fuels))]
            grav = gravities[int(rng.next() * len(gravities))]
            o2 = 12.0 + rng.next() * 30.0
            p_bar = 0.5 + rng.next() * 1.5
            # Flame radius growth in mm, diffusion-limited in micro-g.
            t_end = 1.5 + rng.next() * 2.5
            t = [round(0.05 * k * 4, 3) for k in range(int(t_end / 0.05) + 1)]
            d_eff = 2.0e-5 * (p_bar ** -0.5) * (1.0 + 0.4 * u_in)
            fuel_scale = {"CH4": 1.0, "C2H4": 1.15, "C3H8": 1.05, "H2": 0.8}[fuel]
            radii = [
                round(1000.0 * math.sqrt(d_eff * tt) * fuel_scale, 3) for tt in t
            ]
            t_adiabatic = {
                "CH4": 2226.0, "C2H4": 2370.0, "C3H8": 2267.0, "H2": 2380.0,
            }[fuel]
            o2_factor = max(0.0, (o2 - 11.0) / 21.0)
            peak = t_adiabatic * (0.55 + 0.45 * min(o2_factor, 1.2))
            grav_factor = 0.85 if grav == "earth_1g" else 1.0
            temps = [
                round(
                    300.0
                    + (peak - 300.0) * grav_factor
                    * (1.0 - math.exp(-tt / max(t_end / 4.0, 0.1)))
                    * (0.92 + 0.08 * rng.next()),
                    1,
                )
                for tt in t
            ]
            quenched = o2 < 14.5 or (u_in > 0.4 and rng.next() < 0.25)
            quench_t = round(t_end * (0.5 + rng.next() * 0.4), 2) if quenched else None
            if quenched:
                q_idx = int((quench_t or t_end) / 0.05)
                temps = [temp if k < q_idx else 300.0 for k, temp in enumerate(temps)]
                radii = [r if k < q_idx else 0.0 for k, r in enumerate(radii)]
            runs.append(
                {
                    "experiment_id": f"SURROGATE_{exp_name}_{i:02d}",
                    "payload": UnifiedPayload(
                        source="synthetic",
                        fuel=fuel,
                        oxygen_pct=round(o2, 1),
                        ambient_pressure_bar=round(p_bar, 2),
                        gravity_mode=grav,  # type: ignore[arg-type]
                        inlet_velocity_ms=u_in,
                        max_radius_mm=max(radii) if radii else None,
                        quench_time_s=quench_t,
                        peak_temp_k=max(temps) if temps else None,
                        soot_yield_index=round(
                            max(0.0, 0.5 * (o2 < 20.0) * rng.next()
                                * {"CH4": 0.3, "C2H4": 1.0, "C3H8": 0.7, "H2": 0.0}[fuel]),
                            3,
                        ),
                        stability=None,
                        burn_duration_s=t_end,
                        extinction=quenched,
                        profile_r=radii[-24:],
                        profile_t=temps[-24:],
                    ).model_dump(),
                }
            )
    return runs


class _SeededRng:
    """Tiny deterministic LCG so runs are reproducible across regenerations."""

    def __init__(self, seed: int) -> None:
        self._state = seed & 0xFFFFFFFF

    def next(self) -> float:
        self._state = (1103515245 * self._state + 12345) & 0x7FFFFFFF
        return self._state / 0x7FFFFFFF


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _synthetic_ground_truth() -> list[dict[str, Any]]:
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)
    out = SYNTHETIC_DIR / "psi_runs.json"
    if out.exists():
        try:
            cached = json.loads(out.read_text(encoding="utf-8"))
            if cached and all(
                entry.get("payload", {}).get("source") == "synthetic"
                for entry in cached
            ):
                return cached
        except (OSError, json.JSONDecodeError):
            pass
    data = generate_synthetic_runs()
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


_GROUND_TRUTH: list[dict[str, Any]] | None = None


def load_ground_truth() -> list[dict[str, Any]]:
    """Real PSI s-Flame runs first, plus clearly-labelled surrogates.

    Surrogates fill conditions the flight archive does not cover (C3H8,
    Earth/Mars gravity) and keep the dashboard usable offline. Callers must
    prefer ``payload.source == "psi"``; the triage layer does.
    """
    global _GROUND_TRUTH
    if _GROUND_TRUTH is None:
        _GROUND_TRUTH = load_curated_ground_truth() + _synthetic_ground_truth()
    return _GROUND_TRUTH


async def ingest_psi(
    limit: int = 60, *, per_day: int = 2, candidates_per_day: int = 6
) -> list[dict[str, Any]]:
    """Refresh the curated ACME s-Flame dataset from the PSI API.

    This is a build-time operation (network + ~100 MB of cached telemetry);
    the server itself only calls :func:`load_ground_truth`.
    """
    payload = await asyncio.to_thread(
        build_sflame_runs,
        per_day=per_day,
        candidates_per_day=candidates_per_day,
    )
    return list(payload.get("runs") or [])[:limit]


if __name__ == "__main__":
    data = load_ground_truth()
    real = sum(1 for d in data if d.get("payload", {}).get("source") == "psi")
    fuels = {d["payload"]["fuel"] for d in data}
    quench = sum(1 for d in data if d["payload"].get("quench_time_s"))
    print(
        f"{len(data)} runs ({real} real PSI, {len(data) - real} synthetic); "
        f"fuels={sorted(fuels)}; quenched={quench}"
    )
