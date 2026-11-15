"""
Tier 1 triage via TypeSafe Jev on NanoGPT.

Jev is a *decision model*, not a chat model: it answers named typed questions
(``choice``/``score``/``noul``) and returns calibrated probabilities. We map
those answers onto the existing ``JevVerdict`` schema so every downstream
consumer (UI, Tier 2, sweeps) stays unchanged.

Endpoint: ``POST {NANOGPT_BASE_URL}/decisions`` (native Decisions API).
Reference: https://docs.nano-gpt.com/api-reference/endpoint/decisions
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import CONSTANTS, JevVerdict, UnifiedPayload  # noqa: E402

NANOGPT_BASE_URL = os.environ.get("NANOGPT_BASE_URL", "https://api.nano-gpt.com/api/v1")
JEV_MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.14")
MAX_CONCURRENCY = int(os.environ.get("JEV_CONCURRENCY", "12"))
_TIMEOUT = httpx.Timeout(45.0)

# Six ordered rubric points => an answer of 0..5 maps linearly onto 0..100.
_SCORE_STEPS = 5
_SOOT_CRITERIA = [
    "0 (no soot)",
    "20",
    "40",
    "60",
    "80",
    "100 (heavy soot)",
]
_STABILITY_CRITERIA = [
    "0 (unstable or extinguished)",
    "20",
    "40",
    "60",
    "80",
    "100 (steady flame)",
]
_DELTA_CRITERIA = [
    "0 (identical)",
    "20",
    "40",
    "60",
    "80",
    "100 (no agreement)",
]


def _api_key() -> str | None:
    return os.environ.get("NANOGPT_API_KEY")


def _decision_request(gt: UnifiedPayload | None, sim: UnifiedPayload) -> dict[str, Any]:
    """Build the native Decisions API request.

    The state carries only compact scalar telemetry — the 24-point profile
    arrays are omitted because they cost tokens without informing the verdict.
    """
    state = {
        "task": (
            "Compare the NASA PSI reference run with the simulated 1D spherical "
            "combustion run and answer the typed questions."
        ),
        "nasa_ground_truth": (
            gt.model_dump(exclude_none=True, exclude={"profile_r", "profile_t"})
            if gt
            else None
        ),
        "sim_prediction": sim.model_dump(
            exclude_none=True, exclude={"profile_r", "profile_t"}
        ),
        "solver_constraints": {
            "geometry": "1D spherical finite-volume; a transverse buoyant teardrop is not resolvable.",
            "gravity": "Gravity enters only as an effective radial acceleration.",
            "no_ground_truth": (
                "When nasa_ground_truth is null, choose NONE for the experiment "
                "profile and use 50 for delta."
            ),
        },
    }

    questions = {
        "flame_morphology": {
            "type": "choice",
            "instructions": (
                "Classify the simulated flame morphology. Choose extinguished "
                "when peak temperature is below about 500 K, fragmented when the "
                "field is broken or inflow-dominated, otherwise spherical. The "
                "solver is 1D spherical, so do not claim a transverse teardrop."
            ),
            "criteria": {
                "spherical": "Centered, sustained, roughly spherical burn",
                "teardrop": "Transverse buoyant teardrop (not resolvable here)",
                "fragmented": "Broken, highly stretched, or inflow-dominated field",
                "extinguished": "No sustained burn (peak temperature below ~500 K)",
            },
        },
        "buoyancy_driven_convection": {
            "type": "noul",
            "instructions": (
                "Is buoyancy-driven convection significant in this run? Consider "
                "the gravity mode and the reported flame radius."
            ),
            "criteria": {
                "true": "Effective gravity and flame size make buoyant convection significant",
                "false": "Diffusion or weak effective gravity dominates",
            },
        },
        "nasa_experiment_profile_match": {
            "type": "choice",
            "instructions": (
                "Which NASA experiment profile best matches this comparison? Use "
                "the ground-truth investigation identity when present; choose "
                "NONE when ground truth is absent or unrelated."
            ),
            "criteria": {
                "ACME": "ACME s-Flame / Coflow microgravity spherical flames",
                "SOFIE": "SOFIE droplet or flame experiment",
                "FLEX": "FLEX flame-spread experiment",
                "NONE": "No matching NASA experiment profile",
            },
        },
        "soot_volume_fraction_score": {
            "type": "score",
            "instructions": (
                "How much soot is the simulated flame producing? Consider "
                "soot_yield_index when present."
            ),
            "criteria": _SOOT_CRITERIA,
        },
        "radiant_heat_loss_critical": {
            "type": "noul",
            "instructions": (
                "Is radiant heat loss critical for this flame, based on peak "
                "temperature and the reported telemetry?"
            ),
            "criteria": {
                "true": "Radiative loss materially affects the burn",
                "false": "Radiative loss is not dominant",
            },
        },
        "stability_score": {
            "type": "score",
            "instructions": "How stable is the simulated flame?",
            "criteria": _STABILITY_CRITERIA,
        },
        "delta_score": {
            "type": "score",
            "instructions": (
                "How much does the simulation disagree with the NASA reference? "
                "Use 50 when ground truth is absent."
            ),
            "criteria": _DELTA_CRITERIA,
        },
    }

    return {"model": JEV_MODEL, "state": state, "questions": questions}


def _typed_answer(answers: dict[str, Any], name: str, kind: str) -> dict[str, Any]:
    answer = answers.get(name)
    if not isinstance(answer, dict) or answer.get("type") != kind:
        raise ValueError(f"Jev answer {name!r} missing or not type {kind!r}")
    return answer


def _choice_answer(
    answers: dict[str, Any], name: str, allowed: set[str]
) -> tuple[str, float]:
    answer = _typed_answer(answers, name, "choice")
    choice = answer.get("choice")
    if choice not in allowed:
        raise ValueError(f"Jev answer {name!r} returned unexpected choice {choice!r}")
    return str(choice), float(answer.get("confidence") or 0.0)


def _noul_answer(answers: dict[str, Any], name: str) -> tuple[bool, float]:
    answer = _typed_answer(answers, name, "noul")
    probability = float(answer.get("noul"))
    return probability >= 0.5, probability


def _score_answer(answers: dict[str, Any], name: str) -> tuple[float, float]:
    answer = _typed_answer(answers, name, "score")
    # Jev returns the expected rubric index (0.._SCORE_STEPS); scale to 0..100.
    rubric = float(answer.get("score"))
    value = max(0.0, min(rubric / _SCORE_STEPS, 1.0)) * 100.0
    return round(value, 1), float(answer.get("confidence") or 0.0)


def _verdict_from_answers(
    gt: UnifiedPayload | None, answers: dict[str, Any]
) -> JevVerdict:
    """Map Jev's typed answers onto the stable ``JevVerdict`` contract."""
    morphology, p_morphology = _choice_answer(
        answers,
        "flame_morphology",
        {"spherical", "teardrop", "fragmented", "extinguished"},
    )
    profile, p_profile = _choice_answer(
        answers,
        "nasa_experiment_profile_match",
        {"ACME", "SOFIE", "FLEX", "NONE"},
    )
    buoyant, _ = _noul_answer(answers, "buoyancy_driven_convection")
    radiant, _ = _noul_answer(answers, "radiant_heat_loss_critical")
    soot, p_soot = _score_answer(answers, "soot_volume_fraction_score")
    stability, p_stability = _score_answer(answers, "stability_score")
    delta, p_delta = _score_answer(answers, "delta_score")

    confidences = [p_morphology, p_profile, p_soot, p_stability, p_delta]
    confidence = max(0.0, min(sum(confidences) / len(confidences), 1.0))

    if gt is not None and gt.test_point:
        identity_note = f" NASA GT: {gt.investigation or 'PSI'} {gt.test_point}."
    elif gt is None:
        identity_note = " No matching PSI fuel/gravity class; comparison withheld."
    else:
        identity_note = ""

    notes = (
        f"Jev {JEV_MODEL} decision verdict. Morphology {morphology} "
        f"({p_morphology:.0%}); profile {profile} ({p_profile:.0%}); delta "
        f"{delta:.0f}/100, stability {stability:.0f}/100. Buoyancy "
        f"{'yes' if buoyant else 'no'}; radiant loss "
        f"{'critical' if radiant else 'not critical'}.{identity_note}"
    )[:280]

    return JevVerdict(
        flame_morphology=morphology,  # type: ignore[arg-type]
        buoyancy_driven_convection=buoyant,
        nasa_experiment_profile_match=profile,  # type: ignore[arg-type]
        soot_volume_fraction_score=soot,
        radiant_heat_loss_critical=radiant,
        stability_score=stability,
        delta_score=delta,
        confidence_score=confidence,
        engine="jev",
        engine_model=JEV_MODEL,
        notes=notes,
    )


def _local_heuristic(
    gt: UnifiedPayload | None,
    sim: UnifiedPayload,
    fallback_reason: str = "no NanoGPT key configured",
) -> JevVerdict:
    """Deterministic offline triage used when Jev is unavailable.

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
        engine="local",
        notes=(
            f"Local heuristic fallback ({fallback_reason}); 1D spherical "
            f"solver, gravity is an effective radial term (R2/R12).{identity_note}"
        )[:280],
    )


def _error_detail(exc: Exception) -> str:
    """Extract NanoGPT's structured error instead of a bare HTTP status."""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            payload = response.json()
        except Exception:
            payload = None
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "request failed")
            code = error.get("code")
            detail = f"HTTP {response.status_code}: {message}"
            if code and str(code) not in message:
                detail += f" [{code}]"
            return detail
        text = " ".join((response.text or "").split())
        if text:
            return f"HTTP {response.status_code}: {text[:160]}"
    message = " ".join(f"{type(exc).__name__}: {exc}".split())
    return message[:160]


async def triage_pair(
    gt: UnifiedPayload | None,
    sim: UnifiedPayload,
    client: httpx.AsyncClient | None = None,
) -> JevVerdict:
    """Triage one ground-truth/sim pair through Jev (or local fallback)."""
    key = _api_key()
    if not key:
        return _local_heuristic(gt, sim)

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            base_url=NANOGPT_BASE_URL, timeout=_TIMEOUT, headers={"Authorization": f"Bearer {key}"}
        )
    assert client is not None

    try:
        resp = await client.post("/decisions", json=_decision_request(gt, sim))
        resp.raise_for_status()
        payload = resp.json()
        answers = payload.get("answers") if isinstance(payload, dict) else None
        if not isinstance(answers, dict):
            raise ValueError("Jev response has no answers object")
        return _verdict_from_answers(gt, answers)
    except Exception as exc:
        # Keep the failure visible instead of reporting it as a missing key.
        return _local_heuristic(gt, sim, f"Jev decision call failed — {_error_detail(exc)}")
    finally:
        if own_client and client is not None:
            await client.aclose()


async def triage_sweep(
    pairs: list[tuple[UnifiedPayload | None, UnifiedPayload]],
) -> list[JevVerdict]:
    """Concurrent triage of many pairs with bounded parallelism."""
    if not pairs:
        return []
    # The local heuristic is synchronous; skip the HTTP client entirely.
    if not _api_key():
        return [_local_heuristic(gt, sim) for gt, sim in pairs]

    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def one(pair: tuple[UnifiedPayload | None, UnifiedPayload]) -> JevVerdict:
        async with sem:
            return await triage_pair(*pair)

    async with httpx.AsyncClient(
        base_url=NANOGPT_BASE_URL,
        timeout=_TIMEOUT,
        headers={"Authorization": f"Bearer {_api_key()}"},
    ) as client:
        return await asyncio.gather(*(one(p) for p in pairs))
