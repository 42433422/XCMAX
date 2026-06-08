"""Compat route mount phase (essential + legacy)."""

from __future__ import annotations

from fastapi import FastAPI

from app.fastapi_routes.mounts.essential_compat import register_essential_compat_routes
from app.fastapi_routes.mounts.legacy_compat import register_legacy_compat_routes

__all__ = ["register_essential_compat_routes", "register_legacy_compat_routes"]


def register_compat_routes(app: FastAPI, *, essential_only: bool = False) -> None:
    """Single compat entry: essential (CI) or full legacy stack."""
    if essential_only:
        register_essential_compat_routes(app)
    else:
        register_legacy_compat_routes(app)
