"""
Tier 2 frontier synthesis for the fire-safety diagnostic.

Primary engine: ``deepseek/deepseek-v4.1-flash-1017:thinking`` served by
NanoGPT's OpenAI-compatible chat endpoint (US-hosted infrastructure, same
Wolf-Amendment-safe route as the Tier 1 Jev decision model).

Fallback chain:
  NanoGPT (reuses ``NANOGPT_API_KEY``) -> Azure AI Foundry (optional) ->
  deterministic local Markdown template. Every report carries the engine and
  model that actually produced it, so the UI never labels a template report as
  a frontier-model result.

Gate: invoked ONLY for top-1% anomalous runs or explicit user request,
protecting trial quotas. The report is grounded in the 2015 ISS Combustion
Science Researcher's Guide and the Apollo 1 / Apollo 13 / Mir 1997 incident
context.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from schema import JevVerdict, UnifiedPayload

DEFAULT_NANOGPT_BASE_URL = "https://api.nano-gpt.com/api/v1"
DEFAULT_TIER2_MODEL = "deepseek/deepseek-v4.1-flash-1017:thinking"
DEFAULT_MAX_TOKENS = 8000
DEFAULT_TIMEOUT_S = 180.0

Tier2Engine = Literal["nanogpt", "azure", "local"]

RESEARCHERS_GUIDE_2015 = """Grounding excerpt (NASA, "A Researcher's Guide to
International Space Station Combustion Science", 2015):
- In microgravity, flames burn slower and with spherical symmetry because buoyant
  convection is absent; transport is diffusion-dominated.
- Radiative heat loss is proportionally dominant in microgravity flames; it can
  exceed chemical heat release and cause radiative quenching at low O2 or dilution.
- Practical quenching limits occur at lower oxygen percentages in microgravity than
  in normal gravity for many fuels; flames are also harder to ignite and easier to
  extinguish in reduced gravity.
- Soot production and residence time increase in microgravity, raising soot loading
  and radiative emission relative to 1G flames.
- Ventilation flows (fans, ISS ventilation) stretch flames, enhance mixing, and can
  either stabilize or extinguish depending on speed and dilution.
"""

INCIDENT_HISTORY = """Historical incident context (cabin fire-safety framing):
- Apollo 1 (1967): pure-O2 cabin atmosphere at elevated pressure turned a spark
  into a catastrophic cabin fire -> context for O2-enriched atmosphere risk.
- Apollo 13 (1970): O2 tank explosion -> context for pressure transients and
  oxidizer system anomalies.
- Mir 1997: solid-fuel oxygen generator fire, prolonged burn, blocked access ->
  context for ventilation-driven flame spread and detection/response delays.
"""

REPORT_INSTRUCTIONS = """You are an aerospace fire-safety diagnostician on the
T.R.I.A.G.E. mission team. Write a concise Markdown report (max ~450 words) with
these sections, starting with a single ``# Fire-Safety Diagnostic`` heading:
1. Verdict summary (2-3 sentences).
2. Physics interpretation — link the telemetry to microgravity combustion
   phenomena from the 2015 ISS Combustion Science Researcher's Guide (radiative
   loss dominance, diffusion-limited spherical flames, quench limits, soot).
3. Anomaly assessment — the Tier 1 flags, what they mean, likelihood of real
   hazard vs simulation artifact, comparison against Apollo 1 / Apollo 13 /
   Mir 1997 lessons where relevant.
4. Moon & Mars habitat fire-safety recommendation — 2-4 concrete Environmental
   Control & Life Support System (ECLSS) settings or crew procedures.
Return only the final Markdown report: no preamble, no code fences, no notes
about your reasoning."""

SYSTEM_PROMPT = (
    "You write precise aerospace fire-safety diagnostics. "
    "Follow the requested Markdown structure exactly."
)


@dataclass(frozen=True)
class Tier2Report:
    """A synthesized report plus the engine that actually produced it."""

    markdown: str
    engine: Tier2Engine
    engine_model: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Configuration (read at call time so tests and reloads see current env)
# ---------------------------------------------------------------------------


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _nanogpt_key() -> str:
    return _env("NANOGPT_API_KEY")


def _nanogpt_base_url() -> str:
    return _env("NANOGPT_BASE_URL", DEFAULT_NANOGPT_BASE_URL).rstrip("/")


def tier2_model() -> str:
    return _env("TIER2_MODEL", DEFAULT_TIER2_MODEL)


def _azure_endpoint() -> str:
    return _env("AZURE_OPENAI_ENDPOINT").rstrip("/")


def _azure_key() -> str:
    return _env("AZURE_OPENAI_API_KEY")


def _azure_api_version() -> str:
    return _env("AZURE_OPENAI_API_VERSION", "2024-10-21")


def _azure_deployment() -> str:
    return _env("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")


def azure_configured() -> bool:
    return bool(_azure_endpoint() and _azure_key())


def tier2_engine() -> tuple[Tier2Engine, str]:
    """Return the engine that ``synthesize`` will try first, plus its model."""
    if _nanogpt_key():
        return "nanogpt", tier2_model()
    if azure_configured():
        return "azure", _azure_deployment()
    return "local", ""


# ---------------------------------------------------------------------------
# Prompt + synthesis
# ---------------------------------------------------------------------------


def build_prompt(
    sim: UnifiedPayload,
    gt: UnifiedPayload | None,
    verdict: JevVerdict,
    extra_context: str = "",
) -> str:
    context_lines = [
        f"SIM_RUN: {sim.model_dump_json(exclude_none=True)}",
        f"NASA_GROUND_TRUTH: {gt.model_dump_json(exclude_none=True) if gt else 'N/A'}",
        f"TIER1_VERDICT: {verdict.model_dump_json()}",
        RESEARCHERS_GUIDE_2015,
        INCIDENT_HISTORY,
        REPORT_INSTRUCTIONS,
    ]
    if extra_context:
        context_lines.append(f"ADDITIONAL_CONTEXT: {extra_context}")
    return "\n\n".join(context_lines)


async def synthesize(
    sim: UnifiedPayload,
    gt: UnifiedPayload | None,
    verdict: JevVerdict,
    extra_context: str = "",
    *,
    client: Any | None = None,
) -> Tier2Report:
    """Produce the Tier 2 diagnostic through the best configured engine.

    ``client`` is injectable for tests; it must expose ``post(url, headers=...,
    json=...)``. On any frontier failure the local template is returned with an
    explicit ``notes`` reason instead of silently pretending a model ran.
    """
    prompt = build_prompt(sim, gt, verdict, extra_context)
    failures: list[str] = []

    if _nanogpt_key():
        try:
            markdown, model = await _nanogpt_report(prompt, client=client)
            return Tier2Report(markdown, "nanogpt", model)
        except Exception as exc:  # noqa: BLE001 - degrade to the next engine
            detail = _error_detail(exc)
            failures.append(f"NanoGPT {tier2_model()} failed — {detail}")
            print(f"[tier2] {failures[-1]}")

    if azure_configured():
        try:
            markdown, deployment = await _azure_report(prompt)
            return Tier2Report(
                markdown,
                "azure",
                deployment,
                _short_note("; ".join(failures)),
            )
        except Exception as exc:  # noqa: BLE001 - degrade to local template
            detail = _error_detail(exc)
            failures.append(f"Azure {_azure_deployment()} failed — {detail}")
            print(f"[tier2] {failures[-1]}")

    if not _nanogpt_key() and not azure_configured():
        note = "no NANOGPT_API_KEY or Azure credentials configured"
    else:
        note = _short_note("; ".join(failures)) or "frontier synthesis failed"
    print(f"[tier2] local fallback ({note})")
    return Tier2Report(
        _local_fallback_report(sim, gt, verdict),
        "local",
        "",
        note,
    )


async def _nanogpt_report(
    prompt: str, *, client: Any | None = None
) -> tuple[str, str]:
    model = tier2_model()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": _int_env("TIER2_MAX_TOKENS", DEFAULT_MAX_TOKENS),
        "temperature": 0.3,
    }
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(_float_env("TIER2_TIMEOUT_S", DEFAULT_TIMEOUT_S))
        )
    try:
        resp = await client.post(
            f"{_nanogpt_base_url()}/chat/completions",
            headers={"Authorization": f"Bearer {_nanogpt_key()}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        content = _completion_content(data)
        if not content:
            raise RuntimeError(
                "empty completion (the model may have spent its token budget on reasoning)"
            )
        usage = data.get("usage") or {}
        print(
            "[tier2] nanogpt {} ok: in={} out={} cost={}".format(
                model,
                usage.get("prompt_tokens", "?"),
                usage.get("completion_tokens", "?"),
                usage.get("cost", "?"),
            )
        )
        return _clean_markdown(content), model
    finally:
        if owns_client:
            await client.aclose()


async def _azure_report(prompt: str) -> tuple[str, str]:
    from openai import AsyncAzureOpenAI

    deployment = _azure_deployment()
    client = AsyncAzureOpenAI(
        api_key=_azure_key(),
        azure_endpoint=_azure_endpoint(),
        api_version=_azure_api_version(),
        azure_deployment=deployment,
    )
    try:
        resp = await client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1200,
            temperature=0.3,
        )
        content = resp.choices[0].message.content if resp.choices else None
        if not content or not content.strip():
            raise RuntimeError("empty completion")
        return _clean_markdown(content), deployment
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completion_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    return str(message.get("content") or "").strip()


def _clean_markdown(text: str) -> str:
    """Strip an accidental Markdown code fence around the whole report."""
    report = text.strip()
    if report.startswith("```"):
        report = re.sub(r"^```[a-zA-Z]*\s*\n?", "", report)
        report = re.sub(r"\n?```\s*$", "", report)
    return report.strip()


def _error_detail(exc: BaseException) -> str:
    """Short, human-readable API failure (structured NanoGPT errors included)."""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - non-JSON body
            body = None
        if isinstance(body, dict):
            err = body.get("error", body)
            if isinstance(err, dict):
                message = err.get("message") or err.get("detail")
                code = err.get("code") or err.get("type")
                if message:
                    detail = f"HTTP {response.status_code}: {message}"
                    return f"{detail} [{code}]" if code else detail
        return f"HTTP {response.status_code}"
    text = str(exc).strip()
    if not text:
        return type(exc).__name__
    name = type(exc).__name__
    return text if text.lower().startswith(name.lower()) else f"{name}: {text}"


def _short_note(text: str, limit: int = 400) -> str:
    note = " ".join(text.split())
    return note if len(note) <= limit else f"{note[: limit - 1]}…"


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _local_fallback_report(
    sim: UnifiedPayload, gt: UnifiedPayload | None, v: JevVerdict
) -> str:
    """Offline template report when no frontier engine is available."""
    fuel_name = sim.fuel
    grav = sim.gravity_mode
    peak = sim.peak_temp_k or 0.0
    radius = sim.max_radius_mm or 0.0
    o2 = sim.oxygen_pct
    if gt is None:
        gt_line = "no matching flight telemetry"
    else:
        measured: list[str] = []
        if gt.test_point:
            measured.append(f"{gt.investigation or 'PSI'} {gt.test_point}")
        if gt.burn_duration_s is not None:
            measured.append(
                f"burn {gt.burn_duration_s:.1f} s "
                f"({'extinguished' if gt.extinction else 'stable'})"
            )
        if gt.peak_temp_k is not None:
            measured.append(f"peak {gt.peak_temp_k:.0f} K")
        if gt.max_radius_mm is not None:
            measured.append(f"radius {gt.max_radius_mm:.1f} mm")
        measured.append(f"{gt.oxygen_pct:.1f}% O2 / {gt.ambient_pressure_bar:.2f} bar")
        gt_line = "NASA PSI ground truth: " + ", ".join(measured)
    delta_line = (
        f"Tier 1 delta score {v.delta_score}/100" if v.delta_score is not None else ""
    )
    quench_line = (
        f"Quenching observed at t={sim.quench_time_s}s"
        if sim.quench_time_s
        else "No quench observed in run"
    )
    o2_risk = "elevated" if o2 > 30 else "nominal"
    return f"""# Fire-Safety Diagnostic (local fallback)

**Run**: {fuel_name} / {grav} / O2 {o2}% / peak {peak:.0f} K / radius {radius:.1f} mm

{gt_line}. {delta_line}. {quench_line}.

## Physics interpretation
Morphology classified as **{v.flame_morphology}**; buoyancy-driven convection flagged
{'yes' if v.buoyancy_driven_convection else 'no'}. Per the 2015 ISS Combustion
Science Researcher's Guide, reduced-gravity flames are diffusion-limited and
spherical, radiative loss dominates the energy budget, and quench limits occur at
higher O2 than Earth flames for many fuels.

## Anomaly assessment
- Radiant heat loss flagged {'**critical**' if v.radiant_heat_loss_critical else 'not critical'}.
- Soot score {v.soot_volume_fraction_score}/100.
- Oxygen-enrichment risk: {o2_risk} (Apollo 1 lesson: O2-enriched cabins drastically
  accelerate fire spread).
- Profile match: {v.nasa_experiment_profile_match}.

## Moon & Mars habitat recommendation
- Keep habitat O2 partial pressure below enrichment thresholds; consider
  diluent-N2 fire-safety buffer per ECLSS design.
- Detector placement per Mir 1997 lesson: ensure ventilation paths cannot push
  flame fronts toward crew egress.
- For {grav} operations: verify extinguisher coverage aligns with the measured
  quench limit ({sim.quench_time_s or 'not observed'} s in this run).

*Generated by the local fallback template; no frontier model was used.*"""
