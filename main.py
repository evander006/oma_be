"""Convenience entrypoint from repo root.

Prefer: `cd backend && uvicorn app.main:app --reload`
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.main import app  # noqa: E402

__all__ = ["app"]
