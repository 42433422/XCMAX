#!/usr/bin/env python3
"""Generate deployment mode artifacts from config/deployment_modes.yaml."""

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


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        print("缺少 pyyaml", file=sys.stderr)
        raise SystemExit(2)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print(f"{path} 顶层必须是映射", file=sys.stderr)
        raise SystemExit(2)
    return data


def model() -> dict[str, Any]:
    src = _load_yaml(SOURCE)
    modes = src.get("modes")
    if not isinstance(modes, list) or not modes:
        print("deployment_modes.yaml 缺少 modes", file=sys.stderr)
        raise SystemExit(2)
    out = []
    seen: set[str] = set()
    for item in modes:
        if not isinstance(item, dict):
            raise SystemExit(2)
        mode_id = str(item.get("id") or "").strip()
        if not mode_id or mode_id in seen:
            raise SystemExit(2)
        seen.add(mode_id)
        out.append(
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
                "features": [str(x) for x in item.get("features") or []],
            }
        )
    default_mode = str(src.get("default_mode") or "").strip()
    if default_mode not in seen:
        raise SystemExit(2)
    return {
        "version": int(src.get("version") or 1),
        "defaultMode": default_mode,
        "modes": sorted(out, key=lambda row: row["level"]),
        "mobileConnectionPolicy": src.get("mobile_connection_policy") or {},
    }


def render_json(m: dict[str, Any]) -> str:
    return (
        json.dumps(
            {
                "_generated_from": SOURCE_REL,
                "_note": "DO NOT EDIT BY HAND — run scripts/dev/deployment_modes_ssot.py generate --apply",
                **m,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def render_ts(m: dict[str, Any]) -> str:
    ids = [row["id"] for row in m["modes"]]
    union = " | ".join(f"'{item}'" for item in ids)
    return "\n".join(
        [
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
            f"export const DEFAULT_DEPLOYMENT_MODE: DeploymentModeId = '{m['defaultMode']}';",
            f"export const DEPLOYMENT_MODE_IDS = {json.dumps(ids, ensure_ascii=False, indent=2)} as const;",
            f"export const DEPLOYMENT_MODES = {json.dumps(m['modes'], ensure_ascii=False, indent=2)} as DeploymentMode[];",
            "",
        ]
    )


def render_dart(m: dict[str, Any]) -> str:
    def dart_quote(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    policies = m.get("mobileConnectionPolicy") or {}
    lan_first = [
        str(name)
        for name, policy in sorted(policies.items())
        if isinstance(policy, dict)
        and str(policy.get("super_employee_execution") or "") == "lan_first_with_relay_fallback"
    ]
    ids = [row["id"] for row in m["modes"]]
    lan_lines = ["  static const mobileLanFirstConnections = <String>["]
    lan_lines += [f"    {dart_quote(item)}," for item in lan_first]
    lan_lines += ["  ];"]
    return "\n".join(
        [
            f"// CI SSOT: generated from {SOURCE_REL} — DO NOT EDIT BY HAND",
            "// 改部署模式请编辑该 yaml 后运行: python scripts/dev/deployment_modes_ssot.py generate --apply",
            "",
            "class DeploymentModesSsot {",
            "  const DeploymentModesSsot._();",
            "",
            f"  static const defaultMode = {dart_quote(m['defaultMode'])};",
            f"  static const modeIds = <String>[{', '.join(dart_quote(x) for x in ids)}];",
            *lan_lines,
            "",
            "  static bool mobileConnectionPrefersLan(String value) =>",
            "      mobileLanFirstConnections.contains(value.trim());",
            "}",
            "",
        ]
    )


TARGETS = [(JSON_TARGET, render_json), (TS_TARGET, render_ts), (DART_TARGET, render_dart)]


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
        print("deployment-modes SSOT 派生产物一致")
    return 0


def check() -> int:
    m = model()
    drift = []
    for target, renderer in TARGETS:
        if (target.read_text(encoding="utf-8") if target.is_file() else "") != renderer(m):
            drift.append(str(target.relative_to(ROOT)))
    if drift:
        print("deployment-modes SSOT 漂移:", file=sys.stderr)
        for item in drift:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("deployment-modes SSOT 派生产物一致")
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
