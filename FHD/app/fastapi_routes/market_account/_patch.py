"""Patch-friendly indirection: attribute access always reads the package facade."""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    import app.fastapi_routes.market_account as pkg

    return getattr(pkg, name)
