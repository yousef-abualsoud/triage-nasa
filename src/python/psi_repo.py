"""
NASA PSI repository client + real combustion ground-truth builder.

The PSI portal (https://psi.nasa.gov/physci/repo) exposes a public read API:

    GET /geode-py/ws/repo/search                     -> investigation catalogue
    GET /geode-py/ws/repo/investigations/{accession} -> full record + file index
    GET /geode-py/ws/studies/{accession}/download    -> one file (302 -> S3)

Combustion Science contains 24 microgravity/ground investigations. The only
one with per-test-point tabular telemetry in the repository is ACME s-Flame
(PSI-23): 286 test points across 18 test days, 2019-2020, with fuel blends,
oxygen atmospheres, chamber pressure, ion current, PMT and radiometer traces.

This module reduces that archive to compact, honest ground-truth summaries:

* conditions come from the s-Flame experimental table (test day -> atmosphere
  and fuel bottle) plus the per-test-point TP log (ignition / extinction),
* chamber pressure is converted from PTA3 per the ACME data-file description,
* burn duration and extinction come from the TP log,
* peak ion current / PMT / radiometer come from the raw telemetry,
* no flame radius or calibrated flame temperature is invented: the tabular
  telemetry does not contain them (they require the image archive).

Raw downloads are cached under ``data/psi_cache/`` (gitignored). The reduced
dataset is written to ``data/psi/`` and is small enough to ship.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import UnifiedPayload  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = REPO_ROOT / "data" / "psi_cache"
CURATED_DIR = REPO_ROOT / "data" / "psi"

PSI_BASE = "https://psi.nasa.gov"
REPO_API = f"{PSI_BASE}/geode-py/ws/repo"
STUDIES_API = f"{PSI_BASE}/geode-py/ws/studies"
RESEARCH_AREA = "combustion science"
PRIMARY_ACCESSION = "PSI-23"  # ACME s-Flame

_USER_AGENT = "TRIAGE/1.0 (NASA Space Apps; PSI public data client)"
_TP_RE = re.compile(
    r"_Raw Data_([0-9]{5}[A-Z][0-9]+)_(data\.csv|TP\.txt|mfcSetpoints\.csv)$"
)
_META_TIME_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s+\d+\s+(\d{2}:\d{2}:\d{2}:\d{3})"
)
_O2_RE = re.compile(r"~?\s*(\d+(?:\.\d+)?)\s*%[^,;]*?O2", re.IGNORECASE)


# ---------------------------------------------------------------------------
# HTTP + cache
# ---------------------------------------------------------------------------

def _request(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = 120.0,
    attempts: int = 8,
) -> httpx.Response:
    """GET with retries. The PSI download endpoint 302s to S3 and occasionally
    resets TLS mid-redirect; a fresh connection per attempt clears it."""
    last = "unknown"
    for attempt in range(attempts):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(timeout),
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                resp = client.get(path, params=params)
            if resp.status_code == 200:
                return resp
            last = f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001 - network retry surface
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(min(1.5 * (2**attempt), 12.0))
    raise RuntimeError(f"PSI request failed after {attempts} attempts: {path} ({last})")


def _cache_path(accession: str, filename: str) -> Path:
    safe = filename.replace("/", "__").replace("\\", "__")
    return CACHE_DIR / accession / safe


def download_file(accession: str, filename: str, *, force: bool = False) -> bytes:
    """Download one PSI study file (cached)."""
    path = _cache_path(accession, filename)
    if path.exists() and path.stat().st_size > 0 and not force:
        return path.read_bytes()
    resp = _request(
        f"{STUDIES_API}/{accession}/download",
        {"file": filename, "redirect": "False"},
        timeout=180.0,
        attempts=10,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return resp.content


def download_text(accession: str, filename: str, *, force: bool = False) -> str:
    return download_file(accession, filename, force=force).decode(
        "utf-8", errors="replace"
    )


def fetch_investigation(accession: str, *, force: bool = False) -> dict[str, Any]:
    """Full PSI record including the ``added`` file index."""
    cache = CACHE_DIR / f"{accession}.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text(encoding="utf-8"))
    data = _request(
        f"{REPO_API}/investigations/{accession}", timeout=240.0, attempts=6
    ).json()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values() if v)
    if isinstance(value, (list, tuple)):
        return " ".join(_text(v) for v in value if v)
    return re.sub(r"\s+", " ", str(value)).strip()


def _hardware(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("Name") or value.get("name") or value
    return _text(value)[:240]


def fetch_combustion_catalog() -> list[dict[str, Any]]:
    """All PSI Combustion Science investigations (24 as of 2025)."""
    resp = _request(
        f"{REPO_API}/search",
        {
            "source": "psi",
            "type": "investigation",
            "size": "100",
            "from": "0",
            "ffield": "Research Area",
            "fvalue": RESEARCH_AREA,
        },
        timeout=90.0,
    )
    hits = resp.json().get("hits", {}).get("hits", [])
    out: list[dict[str, Any]] = []
    for hit in hits:
        src = hit.get("_source", {})
        accession = _text(src.get("Accession"))
        thumb = _text(src.get("Thumbnail"))
        out.append(
            {
                "accession": accession,
                "acronym": _text(src.get("Acronym")),
                "title": _text(src.get("Title")),
                "project_type": _text(src.get("Project Type")),
                "flight_platform": _text(src.get("Flight Platform")),
                "sub_research_area": _text(src.get("SubResearch Area")),
                "related_investigations": _text(src.get("Related Investigations")),
                "start_date": _text(src.get("Investigation Start Date")),
                "end_date": _text(src.get("Investigation End Date")),
                "hardware": _hardware(src.get("Experiment Hardware")),
                "objectives": _text(src.get("Objectives")),
                "approach": _text(src.get("Approach")),
                "hypothesis": _text(src.get("Hypothesis")),
                "research_impacts": _text(src.get("Research Impacts/Earth Benefits")),
                "thumbnail_url": f"{PSI_BASE}{thumb}" if thumb.startswith("/") else thumb,
                "repository_url": f"{PSI_BASE}/physci/repo/data/investigations/{accession}",
            }
        )
    out.sort(key=lambda row: int(re.sub(r"\D", "", row["accession"]) or 0))
    return out


def build_catalog() -> dict[str, Any]:
    investigations = fetch_combustion_catalog()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z"),
        "source": {
            "repository": "NASA Physical Sciences Informatics (PSI)",
            "api": f"{REPO_API}/search",
            "research_area": "Combustion Science",
            "license": "NASA open data; individual records carry their own license",
        },
        "count": len(investigations),
        "investigations": investigations,
    }
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    (CURATED_DIR / "catalog.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8"
    )
    return payload


# ---------------------------------------------------------------------------
# ACME s-Flame: conditions, logs, telemetry
# ---------------------------------------------------------------------------

def parse_experimental_table(text: str) -> dict[str, dict[str, str]]:
    """Test day -> {atmosphere, fuel_bottle, test_type, flames_ignited, notes}."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {}
    header = [c.strip().lstrip("\ufeff") for c in rows[0]]
    lookup = {name.lower(): i for i, name in enumerate(header)}
    out: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        if len(row) < 7:
            continue
        day = row[lookup.get("test day*", 1)].strip()
        if not re.fullmatch(r"\d{5}", day):
            continue
        out[day] = {
            "test_type": row[lookup.get("test type", 0)].strip(),
            "atmosphere": row[lookup.get("atmosphere*", 5)].strip(),
            "fuel_bottle": row[lookup.get("fuel bottle", 6)].strip(),
            "flames_ignited": row[lookup.get("flames ignited*", 7)].strip()
            if len(row) > 7
            else "",
            "notes": " ".join(c.strip() for c in row[8:] if c.strip())
            if len(row) > 8
            else "",
        }
    return out


def parse_tp_log(text: str) -> dict[str, Any]:
    """Parse an ACME ``*_TP.txt`` event log."""
    events: dict[str, datetime] = {}
    failure_reason = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Reason:"):
            failure_reason = line.split(":", 1)[1].strip()
            continue
        if ": " not in line:
            continue
        label, value = line.split(": ", 1)
        label = label.strip().lower().replace(" ", "_")
        value = value.strip()
        if value == "***" or not value:
            continue
        try:
            events[label] = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    ignition = events.get("ignition_and_retraction")
    end = events.get("extinction_detected") or events.get("mfcs_off")
    burn = None
    if ignition and end:
        burn = max(0.0, (end - ignition).total_seconds())
    return {
        "script_start": events.get("script_start"),
        "ignition": ignition,
        "mfc_off": events.get("mfcs_off"),
        "extinction": events.get("extinction_detected"),
        "burn_duration_s": burn,
        "extinction_detected": events.get("extinction_detected") is not None,
        "aborted": "script_complete_after_abort" in events,
        "failure_reason": failure_reason or None,
    }


def _seconds_of_day(dt: datetime) -> float:
    return dt.hour * 3600.0 + dt.minute * 60.0 + dt.second + dt.microsecond / 1e6


def parse_sflame_data(text: str) -> dict[str, Any]:
    """Parse one s-Flame ``_data.csv`` into a column-oriented table."""
    lines = text.splitlines()
    if len(lines) < 3:
        raise ValueError("s-Flame CSV is empty")
    meta_match = _META_TIME_RE.search(lines[0])
    start_dt = None
    if meta_match:
        start_dt = datetime.strptime(
            f"{meta_match.group(1)} {meta_match.group(2)}", "%Y-%m-%d %H:%M:%S:%f"
        )
    header = next(csv.reader([lines[1]]))
    header = [h.strip() for h in header]
    time_idx = 0
    columns: dict[str, list[float]] = {name: [] for name in header[1:]}
    times: list[float] = []
    for row in csv.reader(lines[2:]):
        if not row or not row[0].strip():
            continue
        try:
            hh, mm, ss, ms = row[0].strip().split(":")
            t = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0
        except ValueError:
            continue
        times.append(t)
        for name, raw in zip(header[1:], row[1:]):
            try:
                columns[name].append(float(raw))
            except (TypeError, ValueError):
                columns[name].append(float("nan"))
    return {"start": start_dt, "times": times, "columns": columns}


def _median(values: Iterable[float], default: float = 0.0) -> float:
    clean = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    return statistics.fmean(clean) if clean else default


def _peak(values: Iterable[float]) -> float:
    clean = [abs(v) for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    return max(clean) if clean else 0.0


def fuel_from_blend(blend: str) -> str:
    """Map a PSI fuel-bottle description to the dominant solver preset.

    Blends are common in s-Flame (e.g. "66.7% H2 with CH4"). Pick the species
    with the largest stated percentage; fall back to the first recognised fuel
    when the table gives no percentages.
    """
    upper = blend.upper()
    pairs = re.findall(r"(\d+(?:\.\d+)?)\s*%\s*(C2H4|C3H8|CH4|H2)", upper)
    if pairs:
        priority = {"C2H4": 3, "C3H8": 2, "CH4": 1, "H2": 0}
        return max(pairs, key=lambda pair: (float(pair[0]), priority[pair[1]]))[1]
    for fuel in ("C2H4", "C3H8", "CH4"):
        if fuel in upper:
            return fuel
    if "H2" in upper or "HYDROGEN" in upper:
        return "H2"
    return "CH4"


def diluent_from_atmosphere(atmosphere: str) -> str:
    upper = atmosphere.upper()
    if "HE" in upper.replace("THE", " "):
        return "He"
    return "N2"


def oxygen_from_atmosphere(atmosphere: str) -> float:
    """First O2 percentage in the table string (e.g. '~30% and ~21% O2')."""
    match = _O2_RE.search(atmosphere)
    if match:
        return float(match.group(1))
    # Some rows only say "~21% O2"; the query above handles them, but keep a
    # plain percentage fallback for typo'd table cells.
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", atmosphere)
    return float(match.group(1)) if match else 21.0


def _test_point_index(detail: dict[str, Any]) -> dict[str, dict[str, Any]]:
    points: dict[str, dict[str, Any]] = {}
    for entry in detail.get("added", []) + (detail.get("experimentalTable") or []):
        name = str(entry.get("file_name", ""))
        match = _TP_RE.search(name)
        if not match:
            continue
        tp, kind = match.group(1), match.group(2)
        point = points.setdefault(tp, {"test_point": tp, "test_day": tp[:5]})
        if kind == "data.csv":
            point["data_file"] = name
            point["data_size"] = float(entry.get("file_size") or 0.0)
        elif kind == "TP.txt":
            point["tp_file"] = name
        else:
            point["mfc_file"] = name
    return points


def _conditions_for(day: str, table: dict[str, dict[str, str]]) -> dict[str, Any]:
    row = table.get(day, {})
    atmosphere = row.get("atmosphere", "~21% O2 with N2")
    blend = row.get("fuel_bottle", "CH4")
    return {
        "test_day": day,
        "test_type": row.get("test_type", ""),
        "atmosphere": atmosphere,
        "fuel_bottle": blend,
        "diluent": diluent_from_atmosphere(atmosphere),
        "oxygen_pct": oxygen_from_atmosphere(atmosphere),
        "flames_ignited": row.get("flames_ignited", ""),
        "notes": row.get("notes", ""),
    }


def summarize_test_point(
    point: dict[str, Any],
    conditions: dict[str, Any],
    telemetry: dict[str, Any],
    log: dict[str, Any],
) -> dict[str, Any]:
    """Reduce one test point to a UnifiedPayload + provenance block."""
    columns = telemetry["columns"]
    times = telemetry["times"]
    start = telemetry["start"]
    if not times:
        raise ValueError("no telemetry rows")

    # The data timestamp column starts when acquisition begins, which can be
    # tens of seconds after the metadata line's script start. Anchor both the
    # telemetry and the TP-log events to the metadata timestamp.
    t0 = _seconds_of_day(start) if start is not None else min(times)
    rel: list[float] = []
    for value in times:
        offset = value - t0
        if offset < -43200.0:  # acquisition crossed midnight
            offset += 86400.0
        rel.append(offset)

    def rel_event(dt: datetime | None, fallback: float) -> float:
        if dt is None:
            return fallback
        offset = _seconds_of_day(dt) - t0
        if offset < -43200.0:
            offset += 86400.0
        return offset

    ignition = log.get("ignition")
    end_event = log.get("extinction") or log.get("mfc_off")
    ig_rel = rel_event(ignition, rel[0])
    end_rel = rel_event(end_event, rel[-1])
    if end_rel <= ig_rel:
        end_rel = rel[-1]
    end_rel = min(end_rel, rel[-1])

    def window(name: str) -> list[float]:
        series = columns.get(name, [])
        return [
            value
            for value, t in zip(series, rel)
            if ig_rel <= t <= end_rel and math.isfinite(value)
        ]

    pressure_v = _median(window("PTA3"), default=float("nan"))
    pressure_bar = (
        (pressure_v - 0.5) * 14.5038 * 10.0 / 4.0 * 0.0689476
        if math.isfinite(pressure_v)
        else 1.0
    )
    pmt_peak = _peak(
        value
        for name in ("PMT1", "PMT2", "PMT3")
        for value in window(name)
    )
    ion_peak = _peak(window("IonCurrent"))
    radiometer_peak = _peak(window("RadiometerCenter"))
    fuel_flow = _median(window("MFCA3FuelFlow"))

    signal = [
        max(
            (columns.get("PMT1", [])[i] if i < len(columns.get("PMT1", [])) else float("nan")),
            (columns.get("PMT2", [])[i] if i < len(columns.get("PMT2", [])) else float("nan")),
            (columns.get("PMT3", [])[i] if i < len(columns.get("PMT3", [])) else float("nan")),
        )
        for i, t in enumerate(rel)
        if ig_rel <= t <= end_rel
    ]
    signal = [v for v in signal if math.isfinite(v)]
    mean_signal = statistics.fmean(signal) if signal else 0.0
    cv = (
        statistics.pstdev(signal) / abs(mean_signal)
        if len(signal) > 2 and abs(mean_signal) > 1e-9
        else 1.0
    )

    burn_duration = max(0.0, end_rel - ig_rel)
    extinction = bool(log.get("extinction_detected"))
    if extinction:
        stability = 30.0
    else:
        duration_score = min(burn_duration / 20.0, 1.0)
        steadiness = max(0.0, 1.0 - min(cv, 1.0))
        stability = round(100.0 * (0.6 * duration_score + 0.4 * steadiness), 1)

    fuel = fuel_from_blend(conditions["fuel_bottle"])
    payload = UnifiedPayload(
        source="psi",
        fuel=fuel,
        oxygen_pct=float(conditions["oxygen_pct"]),
        ambient_pressure_bar=round(float(pressure_bar), 3),
        gravity_mode="iss_micro_g",
        inlet_velocity_ms=0.0,
        experiment_id=f"PSI-23/{point['test_point']}",
        max_radius_mm=None,
        quench_time_s=round(burn_duration, 2) if extinction else None,
        peak_temp_k=None,
        soot_yield_index=None,
        stability=stability,
        investigation="ACME s-Flame",
        accession="PSI-23",
        test_point=point["test_point"],
        fuel_blend=conditions["fuel_bottle"],
        atmosphere=conditions["atmosphere"],
        facility="Combustion Integrated Rack (CIR), ACME",
        burn_duration_s=round(burn_duration, 2),
        peak_ion_current_ua=round(ion_peak, 4),
        peak_pmt_ua=round(pmt_peak, 4),
        peak_radiometer_v=round(radiometer_peak, 4),
        extinction=extinction,
    )
    provenance = {
        "test_day": conditions["test_day"],
        "test_type": conditions["test_type"],
        "atmosphere": conditions["atmosphere"],
        "fuel_bottle": conditions["fuel_bottle"],
        "diluent": conditions["diluent"],
        "oxygen_pct": conditions["oxygen_pct"],
        "flames_ignited_that_day": conditions.get("flames_ignited", ""),
        "chamber_pressure_bar": round(float(pressure_bar), 3),
        "fuel_flow_slpm": round(float(fuel_flow), 3),
        "burn_duration_s": round(burn_duration, 2),
        "extinction": extinction,
        "failure_reason": log.get("failure_reason"),
        "peak_ion_current_ua": round(ion_peak, 4),
        "peak_pmt_ua": round(pmt_peak, 4),
        "peak_radiometer_v": round(radiometer_peak, 4),
        "stability": stability,
        "pmt_cv": round(cv, 3),
        "notes": conditions.get("notes", ""),
    }
    return {"payload": payload, "provenance": provenance}


def select_test_points(
    detail: dict[str, Any],
    table: dict[str, dict[str, str]],
    *,
    per_day: int = 2,
    candidates_per_day: int = 6,
    accession: str = PRIMARY_ACCESSION,
    verbose: bool = True,
) -> list[dict[str, Any]]:
    """Pick long-burning and extinguished test points from each test day.

    The PSI download endpoint redirects to S3 and occasionally resets the
    connection, so requests are retried in ``download_file`` and fanned out
    across a small thread pool. Logs and telemetry are independent per test
    point, which makes the build minutes instead of an hour.
    """
    points = _test_point_index(detail)
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in points.values():
        if "data_file" not in point or "tp_file" not in point:
            continue
        by_day[point["test_day"]].append(point)

    candidates: list[dict[str, Any]] = []
    for day in sorted(by_day):
        ranked = sorted(
            by_day[day], key=lambda p: float(p.get("data_size") or 0), reverse=True
        )[:candidates_per_day]
        candidates.extend(ranked)

    def fetch_log(point: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        try:
            return point, parse_tp_log(download_text(accession, point["tp_file"]))
        except Exception as exc:  # noqa: BLE001 - one bad log must not stop the build
            if verbose:
                print(f"  {point['test_point']}: TP log failed ({exc})")
            return point, None

    scored_by_day: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for point, log in pool.map(fetch_log, candidates):
            if log is None or log.get("burn_duration_s") is None:
                continue
            scored_by_day[point["test_day"]].append((point, log))

    specs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for day in sorted(scored_by_day):
        scored = scored_by_day[day]
        # Prefer an intact burn for the primary run; keep one quenched case
        # for extinction coverage when the day offers both.
        intact = [item for item in scored if not item[1]["extinction_detected"]]
        if intact:
            primary = max(intact, key=lambda item: item[1]["burn_duration_s"])
        else:
            primary = max(scored, key=lambda item: item[1]["burn_duration_s"])
        picks = [primary]
        quenched = [item for item in scored if item[1]["extinction_detected"]]
        if quenched:
            quench = max(quenched, key=lambda item: item[1]["burn_duration_s"])
            if quench[0]["test_point"] != primary[0]["test_point"]:
                picks.append(quench)
        for point, log in picks[:per_day]:
            specs.append((day, point, log))

    def fetch_run(spec: tuple[str, dict[str, Any], dict[str, Any]]) -> dict[str, Any] | None:
        day, point, log = spec
        conditions = _conditions_for(day, table)
        try:
            raw = download_text(accession, point["data_file"])
            telemetry = parse_sflame_data(raw)
            summary = summarize_test_point(point, conditions, telemetry, log)
        except Exception as exc:  # noqa: BLE001
            if verbose:
                print(f"  {point['test_point']}: telemetry failed ({exc})")
            return None
        return {
            "experiment_id": f"{accession}/{point['test_point']}",
            "payload": summary["payload"].model_dump(),
            "provenance": summary["provenance"],
        }

    selected: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_run, spec) for spec in specs]
        for future in as_completed(futures):
            entry = future.result()
            if entry is None:
                continue
            selected.append(entry)
            if verbose:
                prov = entry["provenance"]
                print(
                    f"  {entry['experiment_id']}: {prov['fuel_bottle']} | "
                    f"{prov['atmosphere']} | burn {prov['burn_duration_s']} s | "
                    f"P {prov['chamber_pressure_bar']} bar"
                )
    selected.sort(key=lambda item: item["experiment_id"])
    return selected


def build_sflame_runs(
    *, per_day: int = 2, candidates_per_day: int = 6, verbose: bool = True
) -> dict[str, Any]:
    detail = fetch_investigation(PRIMARY_ACCESSION)
    table_file = next(
        (
            item["file_name"]
            for item in (detail.get("experimentalTable") or [])
            if str(item.get("file_name", "")).lower().endswith(".csv")
        ),
        None,
    )
    if not table_file:
        raise RuntimeError("PSI-23 has no experimental table CSV")
    table = parse_experimental_table(download_text(PRIMARY_ACCESSION, table_file))
    if verbose:
        print(f"Experimental table: {len(table)} test days")
    runs = select_test_points(
        detail,
        table,
        per_day=per_day,
        candidates_per_day=candidates_per_day,
        verbose=verbose,
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z"),
        "source": {
            "accession": PRIMARY_ACCESSION,
            "investigation": "ACME s-Flame (Structure and Response of Spherical Diffusion Flames)",
            "repository_url": f"{PSI_BASE}/physci/repo/data/investigations/{PRIMARY_ACCESSION}",
            "experimental_table": table_file,
            "notes": (
                "Conditions are per test day (atmosphere / fuel bottle). "
                "Chamber pressure is PTA3 converted per ACME-DOC non-imaging data "
                "file description. Burn duration and extinction come from the "
                "per-test-point TP log. Fuel is the dominant stated blend "
                "percentage; the full blend stays in fuel_blend. Flame radius and "
                "calibrated flame temperature are not present in the tabular "
                "telemetry."
            ),
        },
        "count": len(runs),
        "runs": runs,
    }
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    (CURATED_DIR / "sflame_runs.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8"
    )
    return payload


def load_curated_ground_truth() -> list[dict[str, Any]]:
    """Read the shipped s-Flame summaries (no network)."""
    path = CURATED_DIR / "sflame_runs.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return list(data.get("runs") or [])


def load_catalog() -> dict[str, Any]:
    path = CURATED_DIR / "catalog.json"
    if not path.exists():
        return {"count": 0, "investigations": []}
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NASA PSI data ingestion")
    parser.add_argument("command", choices=("catalog", "sflame", "all", "status"))
    parser.add_argument("--per-day", type=int, default=2)
    parser.add_argument("--candidates", type=int, default=6)
    args = parser.parse_args(argv)

    if args.command in ("catalog", "all"):
        catalog = build_catalog()
        print(f"Catalogue: {catalog['count']} combustion investigations")
    if args.command in ("sflame", "all"):
        runs = build_sflame_runs(
            per_day=args.per_day, candidates_per_day=args.candidates
        )
        print(f"s-Flame ground truth: {runs['count']} test points")
    if args.command == "status":
        catalog = load_catalog()
        runs = load_curated_ground_truth()
        print(f"Catalogue entries : {catalog.get('count', 0)}")
        print(f"s-Flame runs      : {len(runs)}")
        if runs:
            fuels = sorted({r['payload']['fuel'] for r in runs})
            ext = sum(1 for r in runs if r['payload'].get('extinction'))
            print(f"Fuels             : {', '.join(fuels)}")
            print(f"Extinguished runs : {ext}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
