"""
Tier 1 bulk triage via typesafe/jev-latest on NanoGPT (async, concurrent).

Sends compact NASA-vs-sim payload pairs (~200 tokens each) and enforces the
structured JevVerdict output schema. Falls back to a deterministic local
heuristic when no API key is configured so demos never depend on network.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import CONSTANTS, JevVerdict, UnifiedPayload  # noqa: E402

NANOGPT_BASE_URL = os.environ.get("NANOGPT_BASE_URL", "https://nano-gpt.com/api/v1")
JEV_MODEL = "typesafe/jev-latest"
MAX_CONCURRENCY = int(os.environ.get("JEV_CONCURRENCY", "12"))
_TIMEOUT = httpx.Timeout(45.0)


def _api_key() -> str | None:
    return os.environ.get("NANOGPT_API_KEY")


def _triage_prompt(gt: UnifiedPayload | None, sim: UnifiedPayload) -> str:
    return (
        "You are a combustion telemetry triage engine. Compare the NASA PSI ground-truth "
        "run against the simulated run and classify. Respond ONLY with JSON matching: "
        '{"flame_morphology": "spherical"|"teardrop"|"fragmented"|"extinguished", '
        '"buoyancy_driven_convection": bool, '
        '"nasa_experiment_profile_match": "ACME"|"SOFIE"|"FLEX"|"NONE", '
        '"soot_volume_fraction_score": 0-100, '
        '"radiant_heat_loss_critical": bool, '
        '"stability_score": 0-100, "delta_score": 0-100, "confidence_score": 0-1, '
        '"notes": str}\n'
        f"NASA_GROUND_TRUTH: {gt.model_dump_json(exclude_none=True) if gt else 'N/A (no matching PSI run)'}\n"
        f"SIM_PREDICTION: {sim.model_dump_json(exclude_none=True)}"
    )


def _local_heuristic(gt: UnifiedPayload, sim: UnifiedPayload) -> JevVerdict:
    """Deterministic offline triage used when no NanoGPT key is present.

    The real solver is 1D spherical (R12): it cannot produce a transverse
    buoyant teardrop, so the offline heuristic never claims one. Gravity modes
    are reported as an effective radial acceleration, and the notes make the
    limitation explicit for the Tier-2 model.
    """
    mode = CONSTANTS["gravity_modes"].get(sim.gravity_mode, {})
    g_sim = float(mode.get("g_m_per_s2", 0.0))
    buoyant = g_sim > 0.1 and (sim.max_radius_mm or 0.0) > 1.0
    if (sim.peak_temp_k or 0.0) < 500.0:
        morph = "extinguished"
    elif (sim.inlet_velocity_ms or 0.0) > 0.3:
        morph = "fragmented"
    else:
        morph = "spherical"

    profile = "NONE"
    identity = ""
    if gt is not None:
        identity = " ".join(
            str(part or "")
            for part in (gt.experiment_id, gt.investigation, gt.accession)
        ).lower()
    if any(
        token in identity
        for token in ("acme", "sflame", "s-flame", "coflow", "psi-23", "psi-21", "psi-22", "psi-20", "psi-10")
    ):
        profile = "ACME"
    elif any(token in identity for token in ("flex", "psi-69", "psi-68")):
        profile = "FLEX"

    # Prefer measured fields where both sides actually carry them. Real
    # s-Flame tabular telemetry has no flame radius or calibrated temperature,
    # so the score falls back to stability + extinction behaviour instead of
    # inventing a comparison.
    components: list[float] = []
    if gt is not None:
        if gt.peak_temp_k and sim.peak_temp_k:
            components.append(
                abs(gt.peak_temp_k - sim.peak_temp_k) / max(gt.peak_temp_k, 1.0) * 100.0
            )
        if gt.max_radius_mm and sim.max_radius_mm:
            components.append(
                abs(gt.max_radius_mm - sim.max_radius_mm) / max(gt.max_radius_mm, 1.0) * 100.0
            )
        if gt.stability is not None and sim.stability is not None:
            components.append(abs(float(gt.stability) - float(sim.stability)))
        if gt.extinction is not None and sim.extinction is not None:
            components.append(0.0 if bool(gt.extinction) == bool(sim.extinction) else 100.0)
        if gt.burn_duration_s and sim.burn_duration_s:
            components.append(
                min(
                    abs(float(gt.burn_duration_s) - float(sim.burn_duration_s))
                    / max(float(gt.burn_duration_s), 1.0)
                    * 100.0,
                    100.0,
                )
            )
    delta_score = round(min(sum(components) / len(components), 100.0), 1) if components else 50.0
    stability = sim.stability if sim.stability is not None else 60.0

    soot_score = round(
        min(100.0, (sim.soot_yield_index or 0.0) * 100.0 / 0.05), 1
    )
    identity_note = ""
    if gt is not None and gt.test_point:
        identity_note = f" NASA GT: {gt.investigation or 'PSI'} {gt.test_point}."
    elif gt is None:
        identity_note = " No matching PSI fuel/gravity class; comparison withheld."
    return JevVerdict(
        flame_morphology=morph,  # type: ignore[arg-type]
        buoyancy_driven_convection=buoyant,
        nasa_experiment_profile_match=profile,  # type: ignore[arg-type]
        soot_volume_fraction_score=soot_score,
        radiant_heat_loss_critical=(sim.peak_temp_k or 0.0) > 1800.0,
        stability_score=float(stability),
        delta_score=float(delta_score),
        confidence_score=0.55 if delta_score < 60 else 0.4,
        notes=(
            "Local heuristic fallback (no NanoGPT key configured); 1D spherical "
            f"solver, gravity is an effective radial term (R2/R12).{identity_note}"
        )[:280],
    )


async def triage_pair(
    gt: UnifiedPayload | None,
    sim: UnifiedPayload,
    client: httpx.AsyncClient | None = None,
) -> JevVerdict:
    """Triage one ground-truth/sim pair through Jev (or local fallback)."""
    key = _api_key()
    prompt = _triage_prompt(gt, sim)
    if not key:
        return _local_heuristic(gt, sim)

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            base_url=NANOGPT_BASE_URL, timeout=_TIMEOUT, headers={"Authorization": f"Bearer {key}"}
        )
    assert client is not None

    async def _call() -> dict[str, Any]:
        assert client is not None
        resp = await client.post(
            "/chat/completions",
            json={
                "model": JEV_MODEL,
                "messages": [
                    {"role": "system", "content": "Output strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    try:
        data = await _call()
        return JevVerdict.model_validate(data)
    except Exception:
        return _local_heuristic(gt, sim)
    finally:
        if own_client and client is not None:
            await client.aclose()


async def triage_sweep(
    pairs: list[tuple[UnifiedPayload, UnifiedPayload]],
) -> list[JevVerdict]:
    """Concurrent triage of many pairs with bounded parallelism."""
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def one(pair: tuple[UnifiedPayload, UnifiedPayload]) -> JevVerdict:
        async with sem:
            return await triage_pair(*pair)

    async with httpx.AsyncClient(
        base_url=NANOGPT_BASE_URL,
        timeout=_TIMEOUT,
        headers={"Authorization": f"Bearer {_api_key() or 'unset'}"},
    ) as client:
        return await asyncio.gather(*(one(p) for p in pairs))