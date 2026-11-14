"""
T.R.I.A.G.E. backend: asyncio full-duplex WebSocket server & sweep controller.

Protocol (JSON envelopes):
  inbound:
    {kind: "config", config: {...SimConfig fields}}        -> re-run live sim
    {kind: "sweep", sweep: {param: [values...]}}           -> parameter sweep
    {kind: "triage", run_id: str}                          -> tier 1 verdict + nearest PSI GT
    {kind: "tier2", run_id: str}                           -> tier 2 report (Azure-gated)
    {kind: "fuel_list"}                                    -> merged presets + field ranges
    {kind: "fuel_save", key, data}                         -> create/update custom preset
    {kind: "fuel_delete", key}                             -> remove custom preset
    {kind: "ping"}
  outbound:
    {kind: "sim_result", ...}  {kind: "sweep_result", ...}
    {kind: "triage", verdict, ground_truth}  {kind: "tier2_report", ...}
    {kind: "fuel_list" | "fuel_saved" | "fuel_deleted", fuels, fields}
    {kind: "error", message}   {kind: "pong"}

Run:  .venv/bin/python src/python/server.py   (serves on ws://localhost:8765)
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import websockets  # noqa: E402

from azure_frontier_client import azure_configured, synthesize  # noqa: E402
from fuel_db import FUEL_FIELDS, list_presets  # noqa: E402
import fuel_db  # noqa: E402
from jev_client import triage_pair  # noqa: E402
from s3_ingest import load_ground_truth  # noqa: E402
from schema import (  # noqa: E402
    SimConfig,
    SimResult,
    UnifiedPayload,
)
from sim_bridge import run as run_sim  # noqa: E402

HOST = "0.0.0.0"
PORT = 8765
RECENT_CAP = 40  # frames kept per client stream to bound memory

# Lightweight per-process run cache: run_id -> (SimResult, UnifiedPayload, verdict?)
_RUN_CACHE: dict[str, tuple[SimResult, UnifiedPayload, Any]] = {}


def _slim_frames(res: SimResult) -> list[list[list[float]]]:
    """Cap streamed frames so a 20s sweep cannot flood the browser."""
    if len(res.frames) <= RECENT_CAP:
        return res.frames
    step = len(res.frames) / RECENT_CAP
    idx = sorted({int(i * step) for i in range(RECENT_CAP)} | {len(res.frames) - 1})
    return [res.frames[i] for i in idx]


def _sim_result_message(res: SimResult) -> dict[str, Any]:
    return {
        "kind": "sim_result",
        "run_id": res.config.cache_key(),
        "solver": res.solver,
        "config": res.config.model_dump(),
        "times": res.times[-RECENT_CAP:],
        "frames": _slim_frames(res),
        "history": res.history[-RECENT_CAP:],
        "final": res.final,
        "unified": res.to_unified().model_dump(),
    }


async def _handle_config(config: dict[str, Any]) -> dict[str, Any]:
    cfg = SimConfig.model_validate(config)
    res = await asyncio.to_thread(run_sim, cfg)
    _RUN_CACHE[cfg.cache_key()] = (res, res.to_unified(), None)
    return _sim_result_message(res)


SWEEP_PARAMS = {
    "oxygen_pct", "ambient_pressure_bar", "inlet_velocity_ms", "ignition_energy_j",
    "iteration_count", "ambient_temperature_k", "custom_gravity_m_per_s2",
}


async def _handle_sweep(
    sweep: dict[str, list[float]], base: dict[str, Any]
) -> dict[str, Any]:
    """1-D parameter sweep; returns per-run finals + verdicts (tier-1 triage)."""
    base_cfg = SimConfig.model_validate(base)
    results: list[dict[str, Any]] = []
    if sweep:
        param, values = next(iter(sweep.items()))
    else:
        param, values = "oxygen_pct", [16.0, 21.0, 26.0]
    if param not in SWEEP_PARAMS:
        raise ValueError(f"sweep param {param!r} not allowed; pick from {sorted(SWEEP_PARAMS)}")
    for v in values:
        cfg = base_cfg.model_copy(update={param: v})
        res = await asyncio.to_thread(run_sim, cfg)
        sim_payload = res.to_unified()
        gt = await _nearest_ground_truth(sim_payload)
        verdict = await triage_pair(gt, sim_payload)
        rid = cfg.cache_key()
        _RUN_CACHE[rid] = (res, sim_payload, verdict)
        results.append(
            {
                "param": param,
                "value": v,
                "run_id": rid,
                "final": res.final,
                "unified": sim_payload.model_dump(),
                "verdict": verdict.model_dump(),
            }
        )
    return {"kind": "sweep_result", "results": results}


async def _nearest_ground_truth(sim: UnifiedPayload) -> UnifiedPayload:
    """Find the closest PSI ground-truth run (fuel + gravity + coarse params)."""
    gts = load_ground_truth()
    best: tuple[float, UnifiedPayload] | None = None
    for entry in gts:
        p = entry["payload"]
        if p.get("fuel") != sim.fuel:
            continue
        if p.get("gravity_mode") != sim.gravity_mode:
            continue
        dist = (
            abs(float(p.get("oxygen_pct", 21.0)) - sim.oxygen_pct) / 40.0
            + abs(float(p.get("ambient_pressure_bar", 1.0)) - sim.ambient_pressure_bar) / 2.0
            + abs(float(p.get("inlet_velocity_ms", 0.0)) - sim.inlet_velocity_ms) / 2.0
        )
        if best is None or dist < best[0]:
            best = (dist, UnifiedPayload.model_validate(p))
    if best is None:
        # Synthetic fallback payload keeps triage comparable even without match.
        return UnifiedPayload(
            source="psi", fuel=sim.fuel, oxygen_pct=sim.oxygen_pct,
            ambient_pressure_bar=sim.ambient_pressure_bar, gravity_mode=sim.gravity_mode,
        )
    return best[1]


async def _handle_fuel_list() -> dict[str, Any]:
    presets = list_presets()
    fuels = {k: {"name": v.get("name", k), "formula": v.get("formula", k), "custom": k not in ("CH4", "C2H4", "C3H8", "H2")} for k, v in presets.items()}
    return {
        "kind": "fuel_list",
        "fuels": fuels,
        "fields": {k: {"min": lo, "max": hi} for k, (lo, hi) in FUEL_FIELDS.items()},
    }


async def _handle_fuel_save(key: str, data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(key, str) or not key.strip():
        raise ValueError("fuel key required")
    presets = await asyncio.to_thread(fuel_db.save_preset, key, data or {})
    fuels = {k: {"name": v.get("name", k), "formula": v.get("formula", k), "custom": k not in ("CH4", "C2H4", "C3H8", "H2")} for k, v in presets.items()}
    return {"kind": "fuel_saved", "key": key.strip().upper(), "fuels": fuels, "fields": {k: {"min": lo, "max": hi} for k, (lo, hi) in FUEL_FIELDS.items()}}


async def _handle_fuel_delete(key: str) -> dict[str, Any]:
    presets = await asyncio.to_thread(fuel_db.delete_preset, key)
    fuels = {k: {"name": v.get("name", k), "formula": v.get("formula", k), "custom": k not in ("CH4", "C2H4", "C3H8", "H2")} for k, v in presets.items()}
    return {"kind": "fuel_deleted", "key": key, "fuels": fuels}


async def _handle_triage(run_id: str) -> dict[str, Any]:
    if run_id not in _RUN_CACHE:
        raise ValueError(f"unknown run_id {run_id!r}")
    res, sim_payload, verdict = _RUN_CACHE[run_id]
    gt = await _nearest_ground_truth(sim_payload)
    if verdict is None:
        verdict = await triage_pair(gt, sim_payload)
        _RUN_CACHE[run_id] = (res, sim_payload, verdict)
    return {
        "kind": "triage",
        "run_id": run_id,
        "verdict": verdict.model_dump(),
        # The nearest PSI ground truth ships with the verdict so the UI can
        # render field-level agreement percentages without a second round trip.
        "ground_truth": gt.model_dump(),
    }


async def _handle_tier2(run_id: str) -> dict[str, Any]:
    if run_id not in _RUN_CACHE:
        raise ValueError(f"unknown run_id {run_id!r}")
    res, sim_payload, verdict = _RUN_CACHE[run_id]
    if verdict is None:
        msg = await _handle_triage(run_id)
        verdict = type(verdict).model_validate(msg["verdict"]) if verdict is not None else None
    gt = await _nearest_ground_truth(sim_payload)
    v = verdict or (await triage_pair(gt, sim_payload))
    report_md = await synthesize(sim_payload, gt, v)
    return {"kind": "tier2_report", "run_id": run_id, "markdown": report_md, "azure": azure_configured()}


async def _dispatch(raw: str) -> dict[str, Any]:
    msg = json.loads(raw)
    kind = msg.get("kind")
    if kind == "ping":
        return {"kind": "pong"}
    if kind == "config":
        return await _handle_config(msg["config"])
    if kind == "sweep":
        base = msg.get("base", {})
        return await _handle_sweep(msg.get("sweep", {}), base)
    if kind == "fuel_list":
        return await _handle_fuel_list()
    if kind == "fuel_save":
        return await _handle_fuel_save(msg.get("key", ""), msg.get("data", {}))
    if kind == "fuel_delete":
        return await _handle_fuel_delete(msg.get("key", ""))
    if kind == "triage":
        return await _handle_triage(msg["run_id"])
    if kind == "tier2":
        return await _handle_tier2(msg["run_id"])
    raise ValueError(f"unknown message kind {kind!r}")


async def _serve(ws) -> None:
    peer = ws.remote_address
    print(f"[server] client connected {peer}")
    try:
        async for raw in ws:
            try:
                reply = await _dispatch(raw)
            except Exception as exc:  # noqa: BLE001 - report to UI instead of dying
                reply = {"kind": "error", "message": f"{type(exc).__name__}: {exc}"}
            await ws.send(json.dumps(reply))
    except websockets.ConnectionClosed:
        pass
    finally:
        print(f"[server] client disconnected {peer}")


async def main() -> None:
    async with websockets.serve(_serve, HOST, PORT, max_size=64 * 1024 * 1024):
        print(f"[server] T.R.I.A.G.E. backend on ws://{HOST}:{PORT}")
        print("[server] solver:", "triage_core (C++)" if _RUN_CACHE is not None else "?")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[server] shutting down")