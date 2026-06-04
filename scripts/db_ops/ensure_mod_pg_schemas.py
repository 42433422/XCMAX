#!/usr/bin/env python3
"""为已安装的 Mod 在 PostgreSQL 上确保 schema 存在（非 isolated-database 模式）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _discover_mod_ids() -> list[str]:
    csv = (os.environ.get("XCAGI_MOD_IDS") or "").strip()
    if csv:
        return sorted({p.strip() for p in csv.split(",") if p.strip()})
    raw = (os.environ.get("XCAGI_MOD_DATABASE_URLS") or "").strip()
    if raw:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return sorted({str(k).strip() for k in obj if str(k).strip()})
        except json.JSONDecodeError:
            pass
    mods = _ROOT / "mods"
    if not mods.is_dir():
        return []
    out: list[str] = []
    for child in sorted(mods.iterdir()):
        mf = child / "manifest.json"
        if not mf.is_file():
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mid = str((data or {}).get("id") or "").strip()
        if mid:
            out.append(mid)
    return sorted(set(out))


def main() -> int:
    from app.db.mod_dal import get_mod_dal, reset_mod_dal_singleton

    reset_mod_dal_singleton()
    ids = _discover_mod_ids()
    if not ids:
        print("No mod ids found; set XCAGI_MOD_IDS or install mods under mods/")
        return 0
    dal = get_mod_dal(force_new=True)
    if getattr(dal, "backend", "") != "postgres":
        print(f"Mod DAL backend is {getattr(dal, 'backend', '?')}; skip PG schema ensure")
        return 0
    result = dal.ensure_mod_copies(ids)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
