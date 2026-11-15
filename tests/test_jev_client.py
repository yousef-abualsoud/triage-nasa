"""Tier-1 engine wiring: .env loading, Jev decisions mapping, fallbacks, sweeps."""

from __future__ import annotations

import os

import httpx
import pytest

import env_loader
from jev_client import _decision_request, triage_pair, triage_sweep
from schema import UnifiedPayload

ANSWERS = {
    "flame_morphology": {
        "type": "choice",
        "choice": "spherical",
        "confidence": 0.9,
        "probabilities": {"spherical": 0.9, "teardrop": 0.02, "fragmented": 0.03, "extinguished": 0.05},
    },
    "buoyancy_driven_convection": {"type": "noul", "noul": 0.8},
    "nasa_experiment_profile_match": {
        "type": "choice",
        "choice": "ACME",
        "confidence": 0.85,
        "probabilities": {"ACME": 0.85, "SOFIE": 0.05, "FLEX": 0.05, "NONE": 0.05},
    },
    "soot_volume_fraction_score": {
        "type": "score",
        "score": 1.0,
        "confidence": 0.7,
        "legend": {"0": "0 (no soot)", "1": "20"},
        "probabilities": {"0": 0.2, "1": 0.8},
    },
    "radiant_heat_loss_critical": {"type": "noul", "noul": 0.65},
    "stability_score": {
        "type": "score",
        "score": 4.0,
        "confidence": 0.75,
        "legend": {"4": "80"},
        "probabilities": {"4": 1.0},
    },
    "delta_score": {
        "type": "score",
        "score": 2.5,
        "confidence": 0.6,
        "legend": {"2": "40", "3": "60"},
        "probabilities": {"2": 0.5, "3": 0.5},
    },
}


def _sim(**overrides) -> UnifiedPayload:
    data = {
        "source": "sim",
        "fuel": "CH4",
        "oxygen_pct": 21.0,
        "ambient_pressure_bar": 1.0,
        "gravity_mode": "zero_g",
        "peak_temp_k": 1800.0,
        "stability": 70.0,
    }
    data.update(overrides)
    return UnifiedPayload(**data)


def _gt() -> UnifiedPayload:
    return UnifiedPayload(
        source="psi",
        fuel="CH4",
        oxygen_pct=21.0,
        ambient_pressure_bar=1.05,
        gravity_mode="iss_micro_g",
        investigation="ACME s-Flame",
        accession="PSI-23",
        test_point="19304A2",
        burn_duration_s=8.0,
        extinction=True,
    )


def test_env_loader_reads_file_without_overwriting_shell(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TR_IAGE_ENV_TEST=from_file\nTR_IAGE_ENV_KEEP=from_file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TR_IAGE_ENV_KEEP", "from_shell")
    monkeypatch.delenv("TR_IAGE_ENV_TEST", raising=False)
    try:
        assert env_loader.load_env(env_file) is True
        assert os.environ["TR_IAGE_ENV_TEST"] == "from_file"
        assert os.environ["TR_IAGE_ENV_KEEP"] == "from_shell"
    finally:
        os.environ.pop("TR_IAGE_ENV_TEST", None)
    assert env_loader.load_env(tmp_path / "missing.env") is False


def test_decision_request_is_typed_and_compact():
    request = _decision_request(None, _sim())
    assert request["model"] == "typesafe/jev-latest"
    assert request["state"]["nasa_ground_truth"] is None
    assert "profile_r" not in request["state"]["sim_prediction"]
    assert set(request["questions"]) == {
        "flame_morphology",
        "buoyancy_driven_convection",
        "nasa_experiment_profile_match",
        "soot_volume_fraction_score",
        "radiant_heat_loss_critical",
        "stability_score",
        "delta_score",
    }
    assert request["questions"]["flame_morphology"]["type"] == "choice"
    assert request["questions"]["buoyancy_driven_convection"]["type"] == "noul"
    assert request["questions"]["delta_score"]["type"] == "score"
    assert len(request["questions"]["delta_score"]["criteria"]) == 6


@pytest.mark.asyncio
async def test_triage_without_key_labels_local_engine(monkeypatch):
    monkeypatch.delenv("NANOGPT_API_KEY", raising=False)
    verdict = await triage_pair(None, _sim())
    assert verdict.engine == "local"
    assert "no NanoGPT key configured" in verdict.notes


@pytest.mark.asyncio
async def test_decisions_answers_map_onto_verdict(monkeypatch):
    monkeypatch.setenv("NANOGPT_API_KEY", "test-key")

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"answers": ANSWERS}

    class FakeClient:
        def __init__(self):
            self.path = None
            self.payload = None

        async def post(self, path, json):
            self.path = path
            self.payload = json
            return FakeResponse()

    client = FakeClient()
    gt = _gt()
    verdict = await triage_pair(gt, _sim(extinction=False), client=client)

    assert client.path == "/decisions"
    assert client.payload["model"] == "typesafe/jev-latest"
    assert client.payload["state"]["nasa_ground_truth"]["test_point"] == "19304A2"

    assert verdict.engine == "jev"
    assert verdict.flame_morphology == "spherical"
    assert verdict.buoyancy_driven_convection is True
    assert verdict.nasa_experiment_profile_match == "ACME"
    assert verdict.radiant_heat_loss_critical is True
    assert verdict.soot_volume_fraction_score == pytest.approx(20.0)
    assert verdict.stability_score == pytest.approx(80.0)
    assert verdict.delta_score == pytest.approx(50.0)
    assert verdict.confidence_score == pytest.approx(0.76)
    assert "Jev typesafe/jev-latest decision verdict" in verdict.notes
    assert "NASA GT: ACME s-Flame 19304A2" in verdict.notes
    assert len(verdict.notes) <= 280


@pytest.mark.asyncio
async def test_triage_call_failure_is_reported(monkeypatch):
    monkeypatch.setenv("NANOGPT_API_KEY", "test-key")

    class FailingClient:
        async def post(self, *args, **kwargs):
            raise RuntimeError("endpoint exploded")

    verdict = await triage_pair(None, _sim(), client=FailingClient())
    assert verdict.engine == "local"
    assert "Jev decision call failed" in verdict.notes
    assert "RuntimeError" in verdict.notes
    assert "endpoint exploded" in verdict.notes
    assert len(verdict.notes) <= 280


@pytest.mark.asyncio
async def test_api_error_body_is_surfaced(monkeypatch):
    monkeypatch.setenv("NANOGPT_API_KEY", "test-key")
    request = httpx.Request("POST", "https://api.nano-gpt.com/api/v1/decisions")
    response = httpx.Response(
        403,
        request=request,
        json={
            "error": {
                "message": "Decisions models are not available while paid models are disabled.",
                "code": "paid_features_disabled",
            }
        },
    )

    class ForbiddenClient:
        async def post(self, *args, **kwargs):
            response.raise_for_status()

    verdict = await triage_pair(None, _sim(), client=ForbiddenClient())
    assert verdict.engine == "local"
    assert "HTTP 403" in verdict.notes
    assert "paid models are disabled" in verdict.notes
    assert "paid_features_disabled" in verdict.notes
    assert len(verdict.notes) <= 280


@pytest.mark.asyncio
async def test_sweep_without_key_stays_local(monkeypatch):
    monkeypatch.delenv("NANOGPT_API_KEY", raising=False)
    verdicts = await triage_sweep(
        [(None, _sim()), (None, _sim(oxygen_pct=30.0))]
    )
    assert len(verdicts) == 2
    assert all(v.engine == "local" for v in verdicts)
    assert all("no NanoGPT key configured" in v.notes for v in verdicts)
    assert await triage_sweep([]) == []


@pytest.mark.asyncio
async def test_handle_sweep_preserves_each_point_and_engine(monkeypatch):
    monkeypatch.delenv("NANOGPT_API_KEY", raising=False)
    from server import _handle_sweep

    out = await _handle_sweep(
        {"oxygen_pct": [20.0, 21.0]},
        {"fuel": "CH4", "Nr": 16, "iteration_count": 1, "dt_s": 0.001},
    )
    assert [r["value"] for r in out["results"]] == [20.0, 21.0]
    assert len({r["run_id"] for r in out["results"]}) == 2
    assert all(r["verdict"]["engine"] == "local" for r in out["results"])
    assert all("match" in r for r in out["results"])
