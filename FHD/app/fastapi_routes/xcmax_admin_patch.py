"""Patch-friendly indirection for xcmax_admin facade symbols."""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    import app.fastapi_routes.xcmax_admin as pkg

    return getattr(pkg, name)
