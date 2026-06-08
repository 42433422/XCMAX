"""Deprecated shim — re-export from ``taiyangniao_attendance.rules`` (mod-local)."""

from __future__ import annotations

from . import _load_mod_submodule as _load

_mod = _load("rules")

TimeRange = _mod.TimeRange
is_rest_shift = _mod.is_rest_shift

__all__ = ["TimeRange", "is_rest_shift"]
del _load
