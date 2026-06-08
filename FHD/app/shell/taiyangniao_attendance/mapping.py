"""Deprecated shim — re-export from ``taiyangniao_attendance.mapping`` (mod-local)."""

from __future__ import annotations

from . import _load_mod_submodule as _load

_mod = _load("mapping")

DEFAULT_COLUMN_MAP = _mod.DEFAULT_COLUMN_MAP

__all__ = ["DEFAULT_COLUMN_MAP"]
del _load
