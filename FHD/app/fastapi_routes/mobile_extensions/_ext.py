"""Lazy proxy to ``mobile_api_extensions`` for test patch compatibility in split route modules."""

from __future__ import annotations

import importlib
from typing import Any


def __getattr__(name: str) -> Any:
    ext = importlib.import_module("app.fastapi_routes.mobile_api_extensions")
    return getattr(ext, name)
