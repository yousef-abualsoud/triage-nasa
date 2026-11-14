"""
NASA PSI ingestion -> UnifiedPayload ground truth.

Primary path : anonymous boto3 listing/download from s3://nasa-psi (PSI combustion,
ACME s-Flame / Coflow + Saffire telemetry). CSV/DAT/TXT only; .mp4/.tif skipped.
Fallback path : deterministic synthetic telemetry in data/synthetic so the whole
pipeline works offline (venue Wi-Fi drop, PSI restructure, rate limits).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import math
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import UnifiedPayload  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = REPO_ROOT / "data" / "psi_cache"
SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"

PSI_BUCKET = "nasa-psi"
# Gaseous combustion projects in PSI; anything else is out of scope.
SCOPED_PROJECTS = ("ACME", "Saffire")
IN_SCOPE_EXTS = (".csv", ".dat", ".txt")
SKIP_EXTS = (".mp4", ".tif", ".tiff", ".hdf", ".h5", ".zip", ".mov", ".avi")

# Column aliases: PSI files vary wildly between runs; never hardcode indexes.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "time": ("time", "t", "elapsed_time", "time_s", "time (s)"),
    "flame_radius": (
        "flame_radius", "radius", "flame_radius_mm", "radius_mm",
        "r_flame", "flame front radius", "sflame_radius",
    ),
    "temperature": (
        "temperature", "temp", "t_gas", "gas_temp", "temperature_k",
        "flame_temperature", "tc_temperature", "max_temp", "peak_temp",
    ),
    "o2": ("o2", "oxygen", "o2_pct", "o2_percent", "o2_mole_fraction", "o2 (%)"),
    "pressure": ("pressure", "p", "chamber_pressure", "pressure_bar", "pressure (bar)"),
    "inlet_velocity": ("inlet_velocity", "u_in", "flow_velocity", "u_inlet", "coflow_velocity"),
}


def _find(columns: list[str], key: str) -> int | None:
    """Case-insensitive, whitespace-tolerant alias lookup. Returns column index."""
    lowered = [c.strip().lower() for c in columns]
    for alias in COLUMN_ALIASES[key]:
        if alias.lower() in lowered:
            return lowered.index(alias.lower())
    # Prefix match as a last resort (e.g. 'flame_radius_run3').
    for alias in COLUMN_ALIASES[key]:
        for i, col in enumerate(lowered):
            if col.startswith(alias.lower()):
                return i
    return None


def parse_psi_csv(raw: str) -> list[dict[str, Any]] | None:
    """Best-effort parse of a PSI telemetry CSV/DAT into row dicts."""
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None
    # Find the header row: first line where most cells are non-numeric.
    header_idx = 0
    for i, ln in enumerate(lines[: min(10, len(lines))]):
        cells = [c.strip() for c in ln.replace(";", ",").split(",")]
        numeric = sum(
            1
            for c in cells
            if c and (c.replace(".", "").replace("-", "").replace("e", "").isdigit())
        )
        if numeric < len(cells) / 2:
            header_idx = i
            break
    header = [c.strip() for c in lines[header_idx].replace(";", ",").split(",")]
    if len(header) < 2:
        return None
    rows: list[dict[str, Any]] = []
    for ln in lines[header_idx + 1:]:
        cells = [c.strip() for c in ln.replace(";", ",").split(",")]
        if len(cells) != len(header):
            continue
        row: dict[str, Any] = {}
        for name, cell in zip(header, cells):
            try:
                row[name] = float(cell)
            except ValueError:
                row[name] = cell
        if any(isinstance(v, float) for v in row.values()):
            rows.append(row)
    return rows or None


def rows_to_payload(
    rows: list[dict[str, Any]],
    fuel: str,
    gravity_mode: str,
    experiment_id: str,
    inlet_velocity_ms: float = 0.0,
) -> UnifiedPayload:
    """Reduce raw telemetry rows to the compact UnifiedPayload shape."""
    columns = list(rows[0].keys())
    t_idx = _find(columns, "time")
    r_idx = _find(columns, "flame_radius")
    temp_idx = _find(columns, "temperature")
    o2_idx = _find(columns, "o2")
    p_idx = _find(columns, "pressure")
    u_idx = _find(columns, "inlet_velocity")

    def col(idx: int | None) -> list[float]:
        if idx is None:
            return []
        vals = []
        for row in rows:
            v = row.get(columns[idx])
            if isinstance(v, float) and math.isfinite(v):
                vals.append(v)
        return vals

    times = col(t_idx)
    temps = col(temp_idx)
    radii = col(r_idx)
    o2 = col(o2_idx)
    pressures = col(p_idx)
    u_in = col(u_idx)

    peak_temp = max(temps) if temps else None
    mean_o2 = sum(o2) / len(o2) if o2 else None
    mean_p = (sum(pressures) / len(pressures)) / 1e5 if pressures else None

    # Quench time: first time after which no reading exceeds ignition+200 K.
    quench = None
    if times and temps and peak_temp:
        for t, temp in zip(times, temps):
            if temp < (temps[0] + 50.0):
                quench = t
                break

    def downsample(vals: list[float], n: int = 24) -> list[float]:
        if len(vals) <= n:
            return [round(v, 3) for v in vals]
        step = (len(vals) - 1) / (n - 1)
        return [round(vals[int(i * step)], 3) for i in range(n)]

    return UnifiedPayload(
        source="psi",
        fuel=fuel,
        oxygen_pct=mean_o2 if mean_o2 is not None else 21.0,
        ambient_pressure_bar=mean_p if mean_p is not None else 1.0,
        gravity_mode=gravity_mode,  # type: ignore[arg-type]
        inlet_velocity_ms=(sum(u_in) / len(u_in)) if u_in else inlet_velocity_ms,
        max_radius_mm=(max(radii) if radii else None),
        quench_time_s=quench,
        peak_temp_k=peak_temp,
        soot_yield_index=None,
        stability=None,
        profile_r=downsample(radii),
        profile_t=downsample(temps),
    )


# ---------------------------------------------------------------------------
# Synthetic ground truth (offline fallback, ALSO used for local demo data)
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
                    "experiment_id": f"{exp_name}_{i:02d}",
                    "payload": UnifiedPayload(
                        source="psi",
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
# S3 access
# ---------------------------------------------------------------------------

def _anonymous_s3():
    from botocore import UNSIGNED
    from botocore.config import Config
    import boto3

    return boto3.client(
        "s3",
        config=Config(signature_version=UNSIGN, retries={"max_attempts": 3}),
    )


async def list_in_scope_keys(prefix: str = "Combustion/") -> list[str]:
    """Anonymous list of in-scope lightweight telemetry keys under the prefix."""
    def _list() -> list[str]:
        s3 = _anonymous_s3()
        keys: list[str] = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=PSI_BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.lower().endswith(IN_SCOPE_EXTS):
                    continue
                if key.lower().endswith(SKIP_EXTS):
                    continue
                if not any(proj.lower() in key for proj in SCOPED_PROJECTS):
                    continue
                if "simulation" in key.lower() or "pi_run" in key.lower():
                    continue  # legacy PI simulations excluded; flight data is ground truth
                if obj.get("Size", 0) > 20 * 1024 * 1024:
                    continue  # 20 MB telemetry ceiling
                keys.append(key)
        return keys

    return await asyncio.to_thread(_list)


async def download_key(key: str) -> str:
    """Download one telemetry key into the cache; returns local text."""
    cache_path = CACHE_DIR / key.replace("/", "__")
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="replace")

    def _download() -> str:
        s3 = _anonymous_s3()
        body = s3.get_object(Bucket=PSI_BUCKET, Key=key)["Body"].read()
        text = body.decode("utf-8", errors="replace")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")
        return text

    return await asyncio.to_thread(_download)


async def ingest_psi(limit: int = 60) -> list[dict[str, Any]]:
    """Pull in-scope PSI telemetry and reduce to payload dicts."""
    runs: list[dict[str, Any]] = []
    try:
        keys = await list_in_scope_keys()
    except Exception as exc:  # noqa: BLE001 - network/S3 failures fall back below
        print(f"[s3_ingest] PSI listing failed ({exc}); using synthetic fallback")
        return []
    for key in keys[:limit]:
        try:
            raw = await download_key(key)
            rows = parse_psi_csv(raw)
            if not rows:
                continue
            fuel = "CH4"  # TODO: PSI metadata join for fuel/grav per experiment
            grav = "zero_g"
            payload = rows_to_payload(rows, fuel, grav, experiment_id=key)
            runs.append(
                {
                    "experiment_id": key,
                    "payload": payload.model_dump(),
                }
            )
        except Exception:  # noqa: BLE001
            continue
    return runs


def load_ground_truth() -> list[dict[str, Any]]:
    """Load cached/synthetic ground truth from disk (never network)."""
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)
    out = SYNTHETIC_DIR / "psi_runs.json"
    if not out.exists():
        out.write_text(json.dumps(generate_synthetic_runs(), indent=1), encoding="utf-8")
    return json.loads(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    # Regenerate the synthetic set and print a summary.
    data = load_ground_truth()
    fuels = {d["payload"]["fuel"] for d in data}
    quench = sum(1 for d in data if d["payload"]["quench_time_s"])
    print(f"{len(data)} synthetic runs; fuels={sorted(fuels)}; quenched={quench}")