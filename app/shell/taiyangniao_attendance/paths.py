"""Deprecated shim — re-export from ``taiyangniao_attendance.paths`` (mod-local)."""

from __future__ import annotations

from . import _load_mod_submodule

_mod = _load_mod_submodule("paths")

attendance_workspace_root = _mod.attendance_workspace_root

__all__ = ["attendance_workspace_root"]
