#!/usr/bin/env python3
"""数据库存储模式 SSOT 派生器。

唯一真相源: config/database_storage_modes.yaml
派生产物:
  - config/database_storage_modes.generated.json
  - frontend/src/constants/databaseStorageModes.generated.ts
"""

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

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONFIG = 2


def load_source() -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        print("缺少 pyyaml，无法解析 database_storage_modes.yaml", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    if not SOURCE.is_file():
        print(f"SSOT 源不存在: {SOURCE}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    data = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("database_storage_modes.yaml 顶层应为映射", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    return data


def validate_source(src: dict[str, Any]) -> dict[str, Any]:
    modes = src.get("storage_modes")
    if not isinstance(modes, list) or not modes:
        print("database_storage_modes.yaml 必须包含非空 storage_modes 列表", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    required = {
        "id",
        "label",
        "engine",
        "profile_mode",
        "desktop_profile_path",
        "summary",
        "requires_database_url",
        "vector_index_ready",
    }
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in modes:
        if not isinstance(item, dict):
            print("storage_modes 每项必须为映射", file=sys.stderr)
            raise SystemExit(EXIT_CONFIG)
        missing = sorted(required - set(item.keys()))
        if missing:
            print(f"storage mode 缺少字段 {missing}: {item.get('id')}", file=sys.stderr)
            raise SystemExit(EXIT_CONFIG)
        mode_id = str(item["id"]).strip()
        if not mode_id or mode_id in seen:
            print(f"storage mode id 无效或重复: {mode_id}", file=sys.stderr)
            raise SystemExit(EXIT_CONFIG)
        seen.add(mode_id)
        normalized.append(
            {
                "id": mode_id,
                "label": str(item["label"]),
                "engine": str(item["engine"]),
                "profileMode": str(item["profile_mode"]),
                "desktopProfilePath": str(item["desktop_profile_path"]),
                "summary": str(item["summary"]),
                "requiresDatabaseUrl": bool(item["requires_database_url"]),
                "vectorIndexReady": bool(item["vector_index_ready"]),
            }
        )
    default_mode = str(src.get("default_mode") or "").strip()
    if default_mode not in seen:
        print(f"default_mode 不在 storage_modes 中: {default_mode}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    transitions = src.get("transitions")
    if not isinstance(transitions, dict) or "sqlite_to_postgresql" not in transitions:
        print("transitions.sqlite_to_postgresql 必须存在", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    return {
        "version": int(src.get("version") or 1),
        "defaultMode": default_mode,
        "storageModes": normalized,
        "transitions": transitions,
    }


def render_json(model: dict[str, Any]) -> str:
    payload = {
        "_generated_from": SOURCE_REL,
        "_note": "DO NOT EDIT BY HAND — run scripts/dev/database_storage_ssot.py generate --apply",
        **model,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_ts(model: dict[str, Any]) -> str:
    ids = [str(item["id"]) for item in model["storageModes"]]
    union = " | ".join(f"'{item}'" for item in ids)
    lines = [
        f"// CI SSOT: generated from {SOURCE_REL} — DO NOT EDIT BY HAND",
        "// 改数据库存储模式请编辑该 yaml 后运行: python scripts/dev/database_storage_ssot.py generate --apply",
        "",
        f"export type DatabaseStorageModeId = {union};",
        "",
        f"export const DEFAULT_DATABASE_STORAGE_MODE: DatabaseStorageModeId = '{model['defaultMode']}';",
        f"export const DATABASE_STORAGE_MODE_IDS = {json.dumps(ids, ensure_ascii=False, indent=2)} as const;",
        f"export const DATABASE_STORAGE_MODES = {json.dumps(model['storageModes'], ensure_ascii=False, indent=2)};",
        f"export const DATABASE_STORAGE_TRANSITIONS = {json.dumps(model['transitions'], ensure_ascii=False, indent=2)};",
        "",
    ]
    return "\n".join(lines)


TARGETS = [
    (JSON_TARGET, render_json),
    (TS_TARGET, render_ts),
]


def generate(*, apply: bool) -> int:
    model = validate_source(load_source())
    changed: list[str] = []
    for target, renderer in TARGETS:
        expected = renderer(model)
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != expected:
            changed.append(str(target.relative_to(ROOT)))
            if apply:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(expected, encoding="utf-8")
    if changed:
        action = "已同步" if apply else "将变更"
        for item in changed:
            print(f"{action}: {item}")
    else:
        print("database-storage SSOT 派生产物一致")
    return EXIT_OK


def check() -> int:
    model = validate_source(load_source())
    drift: list[str] = []
    for target, renderer in TARGETS:
        expected = renderer(model)
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != expected:
            drift.append(str(target.relative_to(ROOT)))
    if drift:
        print("database-storage SSOT 漂移:", file=sys.stderr)
        for item in drift:
            print(f"  - {item}", file=sys.stderr)
        return EXIT_DRIFT
    print("database-storage SSOT 派生产物一致")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    gen = sub.add_parser("generate")
    gen.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check()
    if args.command == "generate":
        return generate(apply=bool(args.apply))
    return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
