"""遗留 ``/api/wechat_contacts/*`` 经独立微信 bridge Mod 门面代理。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.utils.operational_errors import RECOVERABLE_ERRORS

WECHAT_BRIDGE_MOD_ID = "xcagi-wechat-bridge"
MOD_SOURCE = f"mod:{WECHAT_BRIDGE_MOD_ID}"


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _read_wechat_manifest() -> dict:
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        manager = get_mod_manager()
        meta = manager.get_mod(WECHAT_BRIDGE_MOD_ID)
        mod_dir = Path(meta.mod_path) if meta and meta.mod_path else None
        if mod_dir is None:
            resolved = manager.resolve_mod_directory(WECHAT_BRIDGE_MOD_ID)
            mod_dir = Path(resolved) if resolved else None
        if mod_dir and (mod_dir / "manifest.json").is_file():
            data = json.loads((mod_dir / "manifest.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except RECOVERABLE_ERRORS:
        pass

    repo_mod = Path(__file__).resolve().parents[2] / "mods" / WECHAT_BRIDGE_MOD_ID
    try:
        data = json.loads((repo_mod / "manifest.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except RECOVERABLE_ERRORS:
        return {}


def is_wechat_contacts_via_erp_facade_enabled() -> bool:
    if _truthy_env("XCAGI_DISABLE_WECHAT_CONTACTS_FACADE") or _truthy_env(
        "XCAGI_DISABLE_WECHAT_CONTACTS_ERP_FACADE"
    ):
        return False
    if _truthy_env("XCAGI_WECHAT_CONTACTS_FACADE") or _truthy_env(
        "XCAGI_WECHAT_CONTACTS_ERP_FACADE"
    ):
        return True
    cfg = _read_wechat_manifest().get("config") or {}
    if isinstance(cfg, dict) and cfg.get("wechat_contacts_via_facade") is True:
        return True
    return False


def tag_legacy_response(out: object) -> object:
    if isinstance(out, dict) and "source" not in out:
        tagged = dict(out)
        tagged["source"] = MOD_SOURCE
        tagged["execution_path"] = "wechat_contacts_facade"
        return tagged
    return out


__all__ = [
    "WECHAT_BRIDGE_MOD_ID",
    "is_wechat_contacts_via_erp_facade_enabled",
    "tag_legacy_response",
]
