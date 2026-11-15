"""Shared pytest path setup for the T.R.I.A.G.E. solver tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_DIR = ROOT / "src" / "python"
BUILD_DIR = ROOT / "build"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))
if BUILD_DIR.is_dir() and str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))
