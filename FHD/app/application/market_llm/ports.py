"""Compat module path: debt19 renamed ports.py → protocols.py."""

from __future__ import annotations

from .protocols import *  # noqa: F403
from .protocols import __all__ as __all__  # type: ignore[misc]
