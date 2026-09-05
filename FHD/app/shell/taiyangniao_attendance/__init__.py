"""Legacy Python imports delegated to the owning Mod's implementation.

Workbook parsing is shared; conversion rules belong to the independently
installed customer extension. No retired customer-host package is imported.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _ensure_mod_backend_on_path(stem: str = "parser") -> str:
    from app.infrastructure.mods.mod_manager import get_mod_manager

    generic = stem in {"parser", "header_resolver"}
    mod_id = "attendance-industry" if generic else "sunbird-attendance-custom"
    location = get_mod_manager().resolve_mod_directory(mod_id)
    if not location:
        raise ModuleNotFoundError(f"{mod_id} Mod is not installed")
    backend = str(Path(location) / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    return "attendance_formats" if generic else "sunbird_attendance"


def _load_mod_submodule(stem: str):
    if stem not in {"parser", "header_resolver", "convert", "mapper", "mapping", "rules", "paths"}:
        raise ModuleNotFoundError(f"Unsupported attendance module: {stem}")
    namespace = _ensure_mod_backend_on_path(stem)
    return importlib.import_module(f"{namespace}.{stem}")


__all__ = ["_load_mod_submodule"]
