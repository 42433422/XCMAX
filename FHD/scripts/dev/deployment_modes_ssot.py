#!/usr/bin/env python3
"""部署模式 SSOT 派生器。

唯一真相源: config/deployment_modes.yaml
派生产物:
  - config/deployment_modes.generated.json
  - frontend/src/constants/deploymentModes.generated.ts
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "config" / "deployment_modes.yaml"
SOURCE_REL = "config/deployment_modes.yaml"
JSON_TARGET = ROOT / "config" / "deployment_modes.generated.json"
TS_TARGET = ROOT / "frontend" / "src" / "constants" / "deploymentModes.generated.ts"
DART_TARGET = ROOT / "mobile-flutter-poc" / "lib" / "src" / "data" / "deployment_modes_ssot.dart"

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONFIG = 2


def load_source() -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        print("缺少 pyyaml，无法解析 deployment_modes.yaml", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    if not SOURCE.is_file():
        print(f"SSOT 源不存在: {SOURCE}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    data = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("deployment_modes.yaml 顶层应为映射", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    return data


def validate_source(src: dict[str, Any]) -> dict[str, Any]:
    modes = src.get("modes")
    if not isinstance(modes, list) or not modes:
        print("deployment_modes.yaml 必须包含非空 modes 列表", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)

    required_fields = {
        "id",
        "level",
        "label",
        "badge",
        "summary",
        "network_scope",
        "ai_mode",
        "database_mode",
        "mobile_connection",
        "performance_profile",
        "allows_outbound",
        "requires_postgresql",
        "features",
    }
    seen: set[str] = set()
    normalized_modes: list[dict[str, Any]] = []
    for item in modes:
        if not isinstance(item, dict):
            print("modes 每项必须为映射", file=sys.stderr)
            raise SystemExit(EXIT_CONFIG)
        missing = sorted(required_fields - set(item.keys()))
        if missing:
            print(f"mode 缺少字段 {missing}: {item.get('id')}", file=sys.stderr)
            raise SystemExit(EXIT_CONFIG)
        mode_id = str(item["id"]).strip()
        if not mode_id:
            print("mode.id 不能为空", file=sys.stderr)
            raise SystemExit(EXIT_CONFIG)
        if mode_id in seen:
            print(f"mode.id 重复: {mode_id}", file=sys.stderr)
            raise SystemExit(EXIT_CONFIG)
        seen.add(mode_id)
        normalized_modes.append(
            {
                "id": mode_id,
                "level": int(item["level"]),
                "label": str(item["label"]),
                "badge": str(item["badge"]),
                "summary": str(item["summary"]),
                "networkScope": str(item["network_scope"]),
                "aiMode": str(item["ai_mode"]),
                "databaseMode": str(item["database_mode"]),
                "mobileConnection": str(item["mobile_connection"]),
                "performanceProfile": str(item["performance_profile"]),
                "allowsOutbound": bool(item["allows_outbound"]),
                "requiresPostgresql": bool(item["requires_postgresql"]),
                "features": [str(x) for x in item["features"]],
            }
        )

    default_mode = str(src.get("default_mode") or "").strip()
    if default_mode not in seen:
        print(f"default_mode 不在 modes 中: {default_mode}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)

    return {
        "version": int(src.get("version") or 1),
        "defaultMode": default_mode,
        "modes": sorted(normalized_modes, key=lambda item: int(item["level"])),
        "mobileConnectionPolicy": src.get("mobile_connection_policy") or {},
    }


def render_json(model: dict[str, Any]) -> str:
    payload = {
        "_generated_from": SOURCE_REL,
        "_note": "DO NOT EDIT BY HAND — run scripts/dev/deployment_modes_ssot.py generate --apply",
        **model,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _ts_literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def render_ts(model: dict[str, Any]) -> str:
    mode_ids = [str(item["id"]) for item in model["modes"]]
    union = " | ".join(f"'{mode_id}'" for mode_id in mode_ids)
    lines = [
        f"// CI SSOT: generated from {SOURCE_REL} — DO NOT EDIT BY HAND",
        "// 改部署模式请编辑该 yaml 后运行: python scripts/dev/deployment_modes_ssot.py generate --apply",
        "",
        f"export type DeploymentModeId = {union};",
        "",
        "export type DeploymentMode = {",
        "  id: DeploymentModeId;",
        "  level: number;",
        "  label: string;",
        "  badge: string;",
        "  summary: string;",
        "  networkScope: string;",
        "  aiMode: 'online' | 'offline';",
        "  databaseMode: 'local_sqlite' | 'remote_postgresql';",
        "  mobileConnection: string;",
        "  performanceProfile: string;",
        "  allowsOutbound: boolean;",
        "  requiresPostgresql: boolean;",
        "  features: string[];",
        "};",
        "",
        f"export const DEFAULT_DEPLOYMENT_MODE: DeploymentModeId = '{model['defaultMode']}';",
        f"export const DEPLOYMENT_MODE_IDS = {_ts_literal(mode_ids)} as const;",
        f"export const DEPLOYMENT_MODES = {_ts_literal(model['modes'])} as DeploymentMode[];",
        "",
    ]
    return "\n".join(lines)


def _dart_string_list(values: list[str]) -> str:
    return "<String>[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in values) + "]"


def render_dart(model: dict[str, Any]) -> str:
    policies = model.get("mobileConnectionPolicy") or {}
    lan_first_connections = [
        str(name)
        for name, policy in sorted(policies.items())
        if isinstance(policy, dict)
        and str(policy.get("super_employee_execution") or "") == "lan_first_with_relay_fallback"
    ]
    modes = model.get("modes") or []
    mode_ids = [str(item["id"]) for item in modes if isinstance(item, dict)]
    lines = [
        f"// CI SSOT: generated from {SOURCE_REL} — DO NOT EDIT BY HAND",
        "// 改部署模式请编辑该 yaml 后运行: python scripts/dev/deployment_modes_ssot.py generate --apply",
        "",
        "class DeploymentModesSsot {",
        "  const DeploymentModesSsot._();",
        "",
        f"  static const defaultMode = {json.dumps(model['defaultMode'], ensure_ascii=False)};",
        f"  static const modeIds = {_dart_string_list(mode_ids)};",
        f"  static const mobileLanFirstConnections = {_dart_string_list(lan_first_connections)};",
        "",
        "  static bool mobileConnectionPrefersLan(String value) =>",
        "      mobileLanFirstConnections.contains(value.trim());",
        "}",
        "",
    ]
    return "\n".join(lines)


TARGETS = [
    ("json", JSON_TARGET, render_json),
    ("ts", TS_TARGET, render_ts),
    ("dart", DART_TARGET, render_dart),
]


def generate(*, apply: bool) -> int:
    model = validate_source(load_source())
    changed: list[str] = []
    for _, target, renderer in TARGETS:
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
        print("deployment-modes SSOT 派生产物一致")
    return EXIT_OK


def check() -> int:
    model = validate_source(load_source())
    drift: list[str] = []
    for _, target, renderer in TARGETS:
        expected = renderer(model)
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != expected:
            drift.append(str(target.relative_to(ROOT)))
    if drift:
        print("deployment-modes SSOT 漂移:", file=sys.stderr)
        for item in drift:
            print(f"  - {item}", file=sys.stderr)
        return EXIT_DRIFT
    print("deployment-modes SSOT 派生产物一致")
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
