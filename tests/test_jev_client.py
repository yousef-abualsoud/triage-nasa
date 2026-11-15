"""Tier-1 engine wiring: .env loading, fallback reasons, concurrent sweeps."""

from __future__ import annotations

import os

import pytest

import env_loader
from jev_client import triage_pair, triage_sweep
from schema import UnifiedPayload


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


@pytest.mark.asyncio
async def test_triage_without_key_labels_local_engine(monkeypatch):
    monkeypatch.delenv("NANOGPT_API_KEY", raising=False)
    verdict = await triage_pair(None, _sim())
    assert verdict.engine == "local"
    assert "no NanoGPT key configured" in verdict.notes


@pytest.mark.asyncio
async def test_triage_call_failure_is_reported(monkeypatch):
    monkeypatch.setenv("NANOGPT_API_KEY", "test-key")

    class FailingClient:
        async def post(self, *args, **kwargs):
            raise RuntimeError("endpoint exploded")

    verdict = await triage_pair(None, _sim(), client=FailingClient())
    assert verdict.engine == "local"
    assert "NanoGPT call failed" in verdict.notes
    assert "RuntimeError" in verdict.notes
    assert "endpoint exploded" in verdict.notes
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
