"""Shared helpers for FastAPI route registration."""

from __future__ import annotations

import os


def is_ci_strict() -> bool:
    """When CI=1, optional route import failures should fail the build."""
    return os.environ.get("CI", "").strip().lower() in ("1", "true", "yes", "on")
