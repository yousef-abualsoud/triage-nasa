"""
Tier 2 deep-dive synthesis on Azure AI Foundry (AsyncAzureOpenAI, eastus/eastus2).

Gate: invoked ONLY for top-1% anomalous runs or explicit user request, protecting
the trial subscription's tokens-per-minute quota. Produces a Markdown fire-safety
diagnostic grounded in the 2015 ISS Combustion Science Researcher's Guide and the
Apollo 1 / Apollo 13 / Mir 1997 incident context.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import JevVerdict, UnifiedPayload  # noqa: E402

AZURE_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
AZURE_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

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
these sections:
1. Verdict summary (2-3 sentences).
2. Physics interpretation — link the telemetry to microgravity combustion
   phenomena from the 2015 ISS Combustion Science Researcher's Guide (radiative
   loss dominance, diffusion-limited spherical flames, quench limits, soot).
3. Anomaly assessment — the Tier 1 flags, what they mean, likelihood of real
   hazard vs simulation artifact, comparison against Apollo 1 / Apollo 13 /
   Mir 1997 lessons where relevant.
4. Moon & Mars habitat fire-safety recommendation — 2-4 concrete Environmental
  Control & Life Support System (ECLSS) settings or crew procedures.
"""


def azure_configured() -> bool:
    return bool(AZURE_ENDPOINT and AZURE_API_KEY)


async def synthesize(
    sim: UnifiedPayload,
    gt: UnifiedPayload | None,
    verdict: JevVerdict,
    extra_context: str = "",
) -> str:
    """Produce the Tier 2 Markdown diagnostic. Local fallback if Azure unset."""
    context_lines = [
        f"SIM_RUN: {sim.model_dump_json()}",
        f"NASA_GROUND_TRUTH: {gt.model_dump_json() if gt else 'N/A'}",
        f"TIER1_VERDICT: {verdict.model_dump_json()}",
        RESEARCHERS_GUIDE_2015,
        INCIDENT_HISTORY,
        REPORT_INSTRUCTIONS,
    ]
    if extra_context:
        context_lines.append(f"ADDITIONAL_CONTEXT: {extra_context}")
    prompt = "\n\n".join(context_lines)

    if not azure_configured():
        return _local_fallback_report(sim, gt, verdict)

    from openai import AsyncAzureOpenAI

    client = AsyncAzureOpenAI(
        api_key=AZURE_API_KEY,
        azure_endpoint=AZURE_ENDPOINT,
        api_version=AZURE_API_VERSION,
        azure_deployment=AZURE_DEPLOYMENT,
    )
    try:
        resp = await client.chat.completions.create(
            model=AZURE_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You write precise aerospace fire-safety diagnostics."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1200,
            temperature=0.3,
        )
        return resp.choices[0].message.content or _local_fallback_report(sim, gt, verdict)
    except Exception as exc:  # noqa: BLE001 - degrade to local report on any Azure failure
        print(f"[azure_frontier] synthesis failed ({exc}); local fallback report")
        return _local_fallback_report(sim, gt, verdict)


def _local_fallback_report(sim: UnifiedPayload, gt: UnifiedPayload | None, v: JevVerdict) -> str:
    """Offline template report when Azure is unavailable — keeps the demo alive."""
    fuel_name = sim.fuel
    grav = sim.gravity_mode
    peak = sim.peak_temp_k or 0.0
    radius = sim.max_radius_mm or 0.0
    o2 = sim.oxygen_pct
    gt_line = "no matching flight telemetry" if gt is None else (
        f"NASA PSI ground truth: peak {gt.peak_temp_k} K, radius {gt.max_radius_mm} mm"
    )
    delta_line = f"Tier 1 delta score {v.delta_score}/100" if v.delta_score is not None else ""
    quench_line = (
        f"Quenching observed at t={sim.quench_time_s}s" if sim.quench_time_s
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

*Generated by the local fallback template; Azure AI Foundry unavailable.*"""