"""Compat entry: debt19 renamed blueprints → pack_surface; keep this path for manifest/tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PACK = Path(__file__).with_name("pack_surface.py")
_SPEC = importlib.util.spec_from_file_location("_top_architect_pack_surface", _PACK)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load pack_surface from {_PACK}")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

register_fastapi_routes = _MOD.register_fastapi_routes
mod_init = _MOD.mod_init
_dispatch_run = _MOD._dispatch_run
_resolve_mod_path = _MOD._resolve_mod_path
_load_employee = _MOD._load_employee
_error = _MOD._error

__all__ = [
    "register_fastapi_routes",
    "mod_init",
    "_dispatch_run",
    "_resolve_mod_path",
    "_load_employee",
    "_error",
]
