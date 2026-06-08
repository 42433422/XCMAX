"""Deprecated shim — re-export from ``taiyangniao_attendance.convert`` (mod-local)."""

from __future__ import annotations

from . import _load_mod_submodule

_mod = _load_mod_submodule("convert")

convert_attendance_file = _mod.convert_attendance_file

__all__ = ["convert_attendance_file"]
