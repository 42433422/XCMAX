"""Facade attribute lookup for monkeypatch-friendly router dispatch."""

from __future__ import annotations

import sys
from typing import Any

_FACADE_MODULE = "app.services.tools_workflow_registered"


def facade_attr(name: str, default: Any = None) -> Any:
    """Read symbol from package facade when present (supports patch.object on facade)."""
    mod = sys.modules.get(_FACADE_MODULE)
    if mod is None:
        return default
    return mod.__dict__.get(name, default)
