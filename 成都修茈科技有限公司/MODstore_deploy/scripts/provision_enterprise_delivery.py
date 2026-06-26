#!/usr/bin/env python3
"""Provision Modstore user_mods for enterprise delivery accounts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modstore_server.models import User, get_session_factory  # noqa: E402
from modstore_server.models_db import add_user_mod, get_user_mod_ids  # noqa: E402

ALL_INDUSTRY_MOD_IDS: tuple[str, ...] = ("attendance-industry", "coating-industry")

DELIVERY_PRESETS: dict[str, dict[str, Any]] = {
    "sunbird": {
        "username": "SUNBIRD",
        "mod_ids": ["attendance-industry", "taiyangniao-pro"],
        "note": "Sunbird delivery: attendance industry plus customer custom package.",
    },
    "enterprise-demo": {
        "username": "xcagi-enterprise-demo",
        "mod_ids": list(ALL_INDUSTRY_MOD_IDS),
        "note": "Enterprise demo account can select every open industry.",
    },
}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        mid = str(item or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


def _resolve_args(args: argparse.Namespace) -> tuple[str, list[str], str]:
    preset = DELIVERY_PRESETS.get(args.delivery or "")
    username = str(args.username or (preset or {}).get("username") or "").strip()
    mod_ids: list[str] = []
    note = str((preset or {}).get("note") or "")
    if preset:
        mod_ids.extend(str(x) for x in preset.get("mod_ids") or [])
    if args.all_industries:
        mod_ids.extend(ALL_INDUSTRY_MOD_IDS)
    mod_ids.extend(args.mod_id or [])
    mod_ids = _dedupe(mod_ids)
    if not username:
        raise SystemExit("--username is required when --delivery is not a known preset")
    if not mod_ids:
        raise SystemExit("no mod ids resolved; pass --delivery, --all-industries, or --mod-id")
    return username, mod_ids, note


def provision(username: str, mod_ids: list[str], *, dry_run: bool = False) -> dict[str, Any]:
    sf = get_session_factory()
    with sf() as session:
        user = session.query(User).filter(func.lower(User.username) == username.lower()).first()
        if user is None:
            return {"ok": False, "error": "USER_NOT_FOUND", "username": username}
        user_id = int(user.id)
        before_enterprise = bool(getattr(user, "is_enterprise", False))
        before_mod_ids = sorted(get_user_mod_ids(user_id))
        if not dry_run and not before_enterprise:
            user.is_enterprise = True
            session.commit()

    added: list[str] = []
    if not dry_run:
        before_set = set(before_mod_ids)
        for mod_id in mod_ids:
            add_user_mod(user_id, mod_id)
            if mod_id not in before_set:
                added.append(mod_id)

    after_mod_ids = (
        sorted(set(before_mod_ids) | set(mod_ids)) if dry_run else sorted(get_user_mod_ids(user_id))
    )
    return {
        "ok": True,
        "username": username,
        "user_id": user_id,
        "is_enterprise_before": before_enterprise,
        "is_enterprise_after": True,
        "mod_ids_before": before_mod_ids,
        "requested_mod_ids": mod_ids,
        "added_mod_ids": added,
        "mod_ids_after": after_mod_ids,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision enterprise delivery entitlements")
    parser.add_argument("--delivery", choices=sorted(DELIVERY_PRESETS), default="")
    parser.add_argument("--username", default="")
    parser.add_argument("--mod-id", action="append", default=[])
    parser.add_argument("--all-industries", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    username, mod_ids, note = _resolve_args(args)
    result = provision(username, mod_ids, dry_run=args.dry_run)
    if note:
        result["note"] = note
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
