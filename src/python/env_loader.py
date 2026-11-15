"""Optional repo-root ``.env`` loading for local (non-Docker) runs.

Docker Compose injects variables directly, so this is mainly for the documented
``cp .env.example .env`` workflow. Existing process environment values always
win: a developer can override a file entry from the shell without editing it.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"


def load_env(path: Path | None = None, *, override: bool = False) -> bool:
    """Load ``KEY=VALUE`` pairs from ``path`` (default: repo-root ``.env``).

    Returns ``False`` when the file does not exist, so an absent ``.env`` stays
    a clean no-op.
    """
    target = Path(path).expanduser() if path is not None else ENV_PATH
    if not target.is_file():
        return False
    return bool(load_dotenv(target, override=override))
