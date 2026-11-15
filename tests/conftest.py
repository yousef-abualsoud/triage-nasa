"""Shared pytest path setup for the T.R.I.A.G.E. solver tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYTHON_DIR = ROOT / "src" / "python"
BUILD_DIR = ROOT / "build"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))
if BUILD_DIR.is_dir() and str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))


@pytest.fixture(autouse=True)
def _isolate_local_env(monkeypatch, tmp_path):
    """Keep a developer's real .env/key out of the test run.

    ``server`` calls ``load_env()`` at import time; point that at a missing
    file and clear AI credentials so tests remain deterministic and offline.
    Tests that want a key set it explicitly with monkeypatch.
    """
    import env_loader

    monkeypatch.setattr(env_loader, "ENV_PATH", tmp_path / "absent.env")
    for name in (
        "NANOGPT_API_KEY",
        "NANOGPT_BASE_URL",
        "JEV_MODEL",
        "JEV_CONCURRENCY",
        "TIER2_MODEL",
        "TIER2_MAX_TOKENS",
        "TIER2_TIMEOUT_S",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_DEPLOYMENT",
    ):
        monkeypatch.delenv(name, raising=False)
