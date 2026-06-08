from __future__ import annotations

import os
from typing import Any


def _required_mod_ids() -> list[str]:
    raw = (os.environ.get("FHD_DB_MOD_GATE") or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]


def _enabled_mod_ids() -> set[str]:
    # Minimal recovery: honor env override only.
    raw = (os.environ.get("FHD_ENABLED_MOD_IDS") or "").strip()
    if not raw:
        return set()
    return {x.strip() for x in raw.replace(";", ",").split(",") if x.strip()}


def mod_db_gate_state() -> dict[str, Any]:
    required = _required_mod_ids()
    if not required:
        return {"gate_open": True, "required_mod_ids": [], "enabled_mod_ids": []}
    enabled = _enabled_mod_ids()
    missing = [m for m in required if m not in enabled]
    if missing:
        return {
            "gate_open": False,
            "required_mod_ids": required,
            "enabled_mod_ids": sorted(enabled),
            "missing_mod_ids": missing,
            "reason": f"missing required mods: {', '.join(missing)}",
        }
    return {"gate_open": True, "required_mod_ids": required, "enabled_mod_ids": sorted(enabled)}


def mod_db_gate_open() -> bool:
    return bool(mod_db_gate_state().get("gate_open"))
