"""Stable exception categories exposed to isolated Mod code."""

from __future__ import annotations

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

__all__ = ["BOUNDARY_ERRORS", "RECOVERABLE_ERRORS"]
