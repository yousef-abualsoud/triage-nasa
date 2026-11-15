"""Tier-2 frontier synthesis: DeepSeek on NanoGPT, Azure fallback, local last."""

from __future__ import annotations

import httpx
import pytest

import tier2_client
from schema import JevVerdict, UnifiedPayload
from tier2_client import DEFAULT_TIER2_MODEL, synthesize, tier2_engine


def _sim() -> UnifiedPayload:
    return UnifiedPayload(
        source="sim",
        fuel="CH4",
        oxygen_pct=21.0,
        ambient_pressure_bar=1.0,
        gravity_mode="zero_g",
        peak_temp_k=1800.0,
        max_radius_mm=12.0,
        stability=70.0,
    )


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


def _verdict() -> JevVerdict:
    return JevVerdict(
        flame_morphology="spherical",
        buoyancy_driven_convection=False,
        nasa_experiment_profile_match="ACME",
        soot_volume_fraction_score=20.0,
        radiant_heat_loss_critical=True,
        stability_score=70.0,
        delta_score=40.0,
        confidence_score=0.8,
        engine="local",
        notes="test verdict",
    )


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.request = httpx.Request(
            "POST", "https://api.nano-gpt.com/api/v1/chat/completions"
        )

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=self.request, response=self
            )

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.url = None
        self.headers = None
        self.payload = None

    async def post(self, url, headers=None, json=None):
        self.url = url
        self.headers = headers
        self.payload = json
        return self.response


@pytest.mark.asyncio
async def test_local_template_without_credentials(monkeypatch):
    monkeypatch.delenv("NANOGPT_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    report = await synthesize(_sim(), _gt(), _verdict())
    assert report.engine == "local"
    assert report.engine_model == ""
    assert "no NANOGPT_API_KEY" in report.notes
    assert "local fallback" in report.markdown
    assert "no frontier model was used" in report.markdown
    assert "ACME s-Flame" in report.markdown


@pytest.mark.asyncio
async def test_deepseek_report_uses_typed_chat_endpoint(monkeypatch):
    monkeypatch.setenv("NANOGPT_API_KEY", "test-key")
    monkeypatch.delenv("TIER2_MODEL", raising=False)
    client = _FakeClient(
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "# Fire-Safety Diagnostic\n\nDeepSeek report body."
                        }
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.001},
            }
        )
    )

    report = await synthesize(_sim(), _gt(), _verdict(), client=client)

    assert client.url.endswith("/chat/completions")
    assert client.headers["Authorization"] == "Bearer test-key"
    assert client.payload["model"] == DEFAULT_TIER2_MODEL
    assert client.payload["max_tokens"] == 8000
    assert client.payload["messages"][1]["content"].startswith("SIM_RUN:")
    assert "2024 ISS" not in client.payload["messages"][0]["content"]
    assert "2015 ISS Combustion Science" in client.payload["messages"][1]["content"]
    assert "Apollo 1" in client.payload["messages"][1]["content"]
    assert report.engine == "nanogpt"
    assert report.engine_model == DEFAULT_TIER2_MODEL
    assert report.markdown == "# Fire-Safety Diagnostic\n\nDeepSeek report body."
    assert report.notes == ""


@pytest.mark.asyncio
async def test_model_env_override(monkeypatch):
    monkeypatch.setenv("NANOGPT_API_KEY", "test-key")
    monkeypatch.setenv("TIER2_MODEL", "deepseek/test-model:thinking")
    client = _FakeClient(
        _FakeResponse({"choices": [{"message": {"content": "# Report"}}]})
    )

    report = await synthesize(_sim(), None, _verdict(), client=client)
    assert client.payload["model"] == "deepseek/test-model:thinking"
    assert report.engine_model == "deepseek/test-model:thinking"


@pytest.mark.asyncio
async def test_api_failure_falls_back_with_structured_reason(monkeypatch):
    monkeypatch.setenv("NANOGPT_API_KEY", "test-key")
    response = httpx.Response(
        403,
        request=httpx.Request(
            "POST", "https://api.nano-gpt.com/api/v1/chat/completions"
        ),
        json={
            "error": {
                "message": "Model requires paid access.",
                "code": "paid_features_disabled",
            }
        },
    )

    class ForbiddenClient:
        async def post(self, *args, **kwargs):
            response.raise_for_status()

    report = await synthesize(_sim(), _gt(), _verdict(), client=ForbiddenClient())
    assert report.engine == "local"
    assert "HTTP 403" in report.notes
    assert "Model requires paid access." in report.notes
    assert "paid_features_disabled" in report.notes
    assert "local fallback" in report.markdown


@pytest.mark.asyncio
async def test_empty_completion_falls_back(monkeypatch):
    monkeypatch.setenv("NANOGPT_API_KEY", "test-key")
    client = _FakeClient(
        _FakeResponse({"choices": [{"message": {"content": "   "}}]})
    )

    report = await synthesize(_sim(), None, _verdict(), client=client)
    assert report.engine == "local"
    assert "empty completion" in report.notes


def test_engine_prefers_nanogpt_then_azure_then_local(monkeypatch):
    monkeypatch.delenv("NANOGPT_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    assert tier2_engine() == ("local", "")

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-test")
    assert tier2_engine() == ("azure", "gpt-4o-test")

    monkeypatch.setenv("NANOGPT_API_KEY", "nano-key")
    assert tier2_engine() == ("nanogpt", DEFAULT_TIER2_MODEL)


def test_markdown_fence_is_stripped():
    assert (
        tier2_client._clean_markdown("```markdown\n# Report\n\nBody\n```")
        == "# Report\n\nBody"
    )


@pytest.mark.asyncio
async def test_handle_tier2_ships_engine_and_synced_verdict(monkeypatch):
    import server
    from tier2_client import Tier2Report

    sim, verdict = _sim(), _verdict()

    async def fake_synthesize(*args, **kwargs):
        return Tier2Report("# Report\n\nBody", "nanogpt", DEFAULT_TIER2_MODEL)

    monkeypatch.setattr(server, "synthesize", fake_synthesize)
    server._RUN_CACHE["tier2-test-run"] = (None, sim, verdict)
    try:
        reply = await server._handle_tier2("tier2-test-run")
    finally:
        server._RUN_CACHE.pop("tier2-test-run", None)

    assert reply["kind"] == "tier2_report"
    assert reply["engine"] == "nanogpt"
    assert reply["engine_model"] == DEFAULT_TIER2_MODEL
    assert reply["markdown"].startswith("# Report")
    # The report's tier-1 basis is returned so the Jev panel can stay in sync.
    assert reply["verdict"]["delta_score"] == pytest.approx(40.0)
    assert "matched" in reply["match"]
