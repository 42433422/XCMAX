#!/usr/bin/env python3
"""Generate database storage artifacts from config/database_storage_modes.yaml."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "config" / "database_storage_modes.yaml"
SOURCE_REL = "config/database_storage_modes.yaml"
JSON_TARGET = ROOT / "config" / "database_storage_modes.generated.json"
TS_TARGET = ROOT / "frontend" / "src" / "constants" / "databaseStorageModes.generated.ts"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        print("缺少 pyyaml", file=sys.stderr)
        raise SystemExit(2)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(2)
    return data


def model() -> dict[str, Any]:
    src = _load_yaml(SOURCE)
    rows = []
    for item in src.get("storage_modes") or []:
        rows.append(
            {
                "id": str(item["id"]),
                "label": str(item["label"]),
                "engine": str(item["engine"]),
                "profileMode": str(item["profile_mode"]),
                "desktopProfilePath": str(item["desktop_profile_path"]),
                "summary": str(item["summary"]),
                "requiresDatabaseUrl": bool(item["requires_database_url"]),
                "vectorIndexReady": bool(item["vector_index_ready"]),
            }
        )
    ids = {row["id"] for row in rows}
    default_mode = str(src.get("default_mode") or "")
    if not rows or default_mode not in ids:
        raise SystemExit(2)
    return {
        "version": int(src.get("version") or 1),
        "defaultMode": default_mode,
        "storageModes": rows,
        "transitions": src.get("transitions") or {},
    }


def render_json(m: dict[str, Any]) -> str:
    return (
        json.dumps(
            {
                "_generated_from": SOURCE_REL,
                "_note": "DO NOT EDIT BY HAND — run scripts/dev/database_storage_ssot.py generate --apply",
                **m,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def render_ts(m: dict[str, Any]) -> str:
    ids = [row["id"] for row in m["storageModes"]]
    union = " | ".join(f"'{item}'" for item in ids)
    return "\n".join(
        [
            f"// CI SSOT: generated from {SOURCE_REL} — DO NOT EDIT BY HAND",
            "// 改数据库存储模式请编辑该 yaml 后运行: python scripts/dev/database_storage_ssot.py generate --apply",
            "",
            f"export type DatabaseStorageModeId = {union};",
            "",
            f"export const DEFAULT_DATABASE_STORAGE_MODE: DatabaseStorageModeId = '{m['defaultMode']}';",
            f"export const DATABASE_STORAGE_MODE_IDS = {json.dumps(ids, ensure_ascii=False, indent=2)} as const;",
            f"export const DATABASE_STORAGE_MODES = {json.dumps(m['storageModes'], ensure_ascii=False, indent=2)};",
            f"export const DATABASE_STORAGE_TRANSITIONS = {json.dumps(m['transitions'], ensure_ascii=False, indent=2)};",
            "",
        ]
    )


TARGETS = [(JSON_TARGET, render_json), (TS_TARGET, render_ts)]


def generate(apply: bool) -> int:
    m = model()
    changed = []
    for target, renderer in TARGETS:
        expected = renderer(m)
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != expected:
            changed.append(str(target.relative_to(ROOT)))
            if apply:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(expected, encoding="utf-8")
    for item in changed:
        print(("已同步" if apply else "将变更") + f": {item}")
    if not changed:
        print("database-storage SSOT 派生产物一致")
    return 0


def check() -> int:
    m = model()
    drift = []
    for target, renderer in TARGETS:
        if (target.read_text(encoding="utf-8") if target.is_file() else "") != renderer(m):
            drift.append(str(target.relative_to(ROOT)))
    if drift:
        print("database-storage SSOT 漂移:", file=sys.stderr)
        for item in drift:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("database-storage SSOT 派生产物一致")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    gen = sub.add_parser("generate")
    gen.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return check() if args.cmd == "check" else generate(args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
