"""QualityOps AI backend. Paths below never depend on the working directory."""

import os
from pathlib import Path

# ponytail: assumes the in-repo (editable) install backend/src/app; a wheel install would need these passed in.
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
EVAL_DIR = REPO_ROOT / "docs" / "evaluations"


def database_url() -> str:
    """DATABASE_URL if set, else backend/qualityops.db (same default as alembic.ini)."""
    return os.environ.get("DATABASE_URL") or f"sqlite:///{(BACKEND_DIR / 'qualityops.db').as_posix()}"
