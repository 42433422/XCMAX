"""Desktop and mobile navigation from the shared, versioned catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from app.utils.path_io.path_utils import get_base_dir

_CATALOG = json.loads(
    (Path(get_base_dir()) / "config/core_navigation.json").read_text(encoding="utf-8")
)
_GROUPS = {"tasks", "business", "data", "computer"}


def _mobile_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": row["key"],
        "name": row["name"],
        "path": row["path"],
        "icon": row["iconClass"],
        "mobile_group": row.get("mobile_group", "business"),
        "requires_desktop": row.get("requires_desktop", False),
    }


_CORE_NAV_ITEMS = [_mobile_item(row) for row in [*_CATALOG["core"], _CATALOG["settings"]]]
_ADMIN_NAV_ITEM = _mobile_item(_CATALOG["admin"])
_ROLE_VISIBLE_KEYS = {
    "admin": None,
    "enterprise": {r["key"] for r in _CORE_NAV_ITEMS},
    "personal": set(_CATALOG["personal_core_keys"]),
}
_ALL_ITEMS = {
    row["key"]: _mobile_item(row)
    for row in [
        *_CATALOG["industry"],
        *_CATALOG["core"],
        _CATALOG["settings"],
        _CATALOG["admin"],
    ]
}
_PATH_KEYS = {row["path"]: key for key, row in _ALL_ITEMS.items()}
_CHILD_PARENT_KEYS = {
    child["key"]: row["key"] for row in _CATALOG["core"] for child in row.get("children", [])
}


def _rows(value: object) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def resolve_mobile_navigation(
    mods: list[dict[str, Any]],
    *,
    account_kind: str,
    tenant: bool = False,
    tenant_member: bool = False,
    permissions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Consume only the entitlement-filtered installed Mods from mobile_mod_items."""
    permissions = permissions or []
    allowed = _ROLE_VISIBLE_KEYS.get(account_kind, _ROLE_VISIBLE_KEYS["personal"])
    if tenant_member:
        allowed = {"settings"}
        if "elt.read" in permissions:
            allowed.add("business-docking")
    items = {
        row["key"]: {**row, "source": "core"}
        for row in _CORE_NAV_ITEMS
        if allowed is None or row["key"] in allowed
    }
    if account_kind == "admin" and not tenant_member:
        items[_ADMIN_NAV_ITEM["key"]] = {**_ADMIN_NAV_ITEM, "source": "core"}
    mods = _rows(mods)
    installed = {str(mod.get("id") or "").strip() for mod in mods}
    for mod in mods:
        mod_id = str(mod.get("id") or "").strip()
        if not mod_id:
            continue
        overrides = _rows(mod.get("menu_overrides"))
        # Only declared industry subsystems or visible overrides create host slots.
        industry = mod.get("industry") if isinstance(mod.get("industry"), dict) else {}
        subsystems = industry.get("subsystems") or {}
        slots = (
            [
                {"key": key, **(value if isinstance(value, dict) else {})}
                for key, value in subsystems.items()
            ]
            if isinstance(subsystems, dict)
            else []
        )
        entries = [(row, True) for row in [*slots, *overrides]] + [
            (row, False) for row in _rows(mod.get("frontend_menu") or mod.get("menu"))
        ]
        for entry, host_slot in entries:
            if entry.get("hidden") is True or entry.get("visible") is False:
                continue
            raw_key = str(entry.get("key") or entry.get("id") or "").strip()
            if not raw_key:
                continue
            raw_path = str(entry.get("path") or entry.get("url") or "").strip()
            key = (
                raw_key
                if raw_key in _ALL_ITEMS or raw_key in _CHILD_PARENT_KEYS
                else _CATALOG["mod_aliases"].get(raw_key, "")
            )
            key = _PATH_KEYS.get(unquote(raw_path.split("?", 1)[0].split("#", 1)[0]), key)
            key = _CHILD_PARENT_KEYS.get(key, key)
            canonical = _ALL_ITEMS.get(key)
            if host_slot and canonical is None:
                continue
            if key == _ADMIN_NAV_ITEM["key"] and (account_kind != "admin" or tenant_member):
                continue
            if account_kind == "personal" and canonical and key not in (allowed or set()):
                continue
            path = raw_path or (canonical["path"] if canonical else f"/mod/{mod_id}")
            if any(ord(char) < 32 for char in path):
                continue
            try:
                parsed = urlsplit(path)
            except ValueError:
                continue
            decoded_path = unquote(parsed.path)
            if (
                parsed.scheme
                or parsed.netloc
                or not decoded_path.startswith("/")
                or decoded_path.startswith("//")
                or "\\" in decoded_path
                or any(part in {".", ".."} for part in decoded_path.split("/"))
            ):
                continue
            if tenant and not decoded_path.startswith("/mod/"):
                if (
                    key not in (allowed or set())
                    or not canonical
                    or decoded_path != canonical["path"]
                ):
                    path = _CATALOG["tenant_paths"].get(key, "")
                    if not path:
                        continue
                    decoded_path = path
            if decoded_path.startswith("/mod/") and decoded_path.split("/")[2] not in installed:
                continue
            key = key or (raw_key if raw_key.startswith("mod-") else f"mod-{raw_key}")
            item = {
                **(canonical or {}),
                "key": key,
                "path": path,
                "source": "mod",
                "mod_id": mod_id,
                "name": str(
                    entry.get("label")
                    or entry.get("name")
                    or (canonical or {}).get("name")
                    or mod.get("name")
                    or mod_id
                ),
                "icon": str(
                    entry.get("icon")
                    or entry.get("iconClass")
                    or (canonical or {}).get("icon")
                    or "fa-cube"
                ),
                "mobile_group": (canonical or {}).get("mobile_group", "business"),
                "requires_desktop": (canonical or {}).get("requires_desktop", False),
            }
            if not canonical:
                if isinstance(entry.get("mobile_group"), str) and entry["mobile_group"] in _GROUPS:
                    item["mobile_group"] = entry["mobile_group"]
                item["requires_desktop"] = entry.get("requires_desktop") is True
            items[key] = item
    # Different manifest ids may describe the same page; expose it only once.
    return list({item["path"]: item for item in items.values()}.values())
