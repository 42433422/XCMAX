#!/usr/bin/env python3
"""检查 Mod 分层策略 SSOT 与显式 manifest 声明。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "mod_levels.json"
MOD_ROOTS = (ROOT / "mods", ROOT / "XCAGI" / "mods")


def _read_policy() -> dict:
    try:
        data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取分层 SSOT: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("分层 SSOT 顶层必须是对象")
    return data


def _iter_manifests():
    seen: set[str] = set()
    for root in MOD_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/manifest.json")):
            if path.parent.name.startswith("_"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            mid = str(data.get("id") or path.parent.name).strip()
            if mid in seen:
                continue
            seen.add(mid)
            yield path, data


def check() -> int:
    try:
        policy = _read_policy()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    errors: list[str] = []
    if policy.get("schema_version") != 1:
        errors.append("schema_version 必须为 1")
    kinds = policy.get("kinds") if isinstance(policy.get("kinds"), dict) else {}
    required = {
        "host_core": 1,
        "system_mod": 2,
        "industry_mod": 3,
        "custom_mod": 3,
        "employee_pack": 4,
    }
    for kind, level in required.items():
        row = kinds.get(kind) if isinstance(kinds.get(kind), dict) else {}
        if row.get("level") != level:
            errors.append(f"kinds.{kind}.level 必须为 {level}")
    manifest_by_id: dict[str, tuple[Path, dict]] = {}
    for path, manifest in _iter_manifests():
        manifest_by_id.setdefault(
            str(manifest.get("id") or path.parent.name).strip(), (path, manifest)
        )
        kind = str(manifest.get("mod_kind") or "").strip()
        if not kind:
            continue  # 旧 manifest 由运行时兼容分类，迁移期间不阻断
        if kind not in required:
            errors.append(f"{path}: 未知 mod_kind={kind}")
            continue
        if manifest.get("mod_level") != required[kind]:
            errors.append(f"{path}: mod_kind={kind} 必须使用 mod_level={required[kind]}")
        artifact = str(manifest.get("artifact") or "mod").strip().lower()
        if kind == "employee_pack" and artifact != "employee_pack":
            errors.append(f"{path}: employee_pack 必须使用 artifact=employee_pack")
        if kind != "employee_pack" and manifest.get("market_installable") is True:
            errors.append(f"{path}: 系统/行业/定制 Mod 不允许 market_installable=true")

    composites = policy.get("composites") if isinstance(policy.get("composites"), dict) else {}
    for owner, raw in composites.items():
        if not isinstance(raw, dict):
            errors.append(f"composites.{owner} 必须是对象")
            continue
        members = raw.get("members") if isinstance(raw.get("members"), list) else []
        for member in members:
            mid = str(member or "").strip()
            if not mid:
                errors.append(f"composites.{owner}.members 不能有空 ID")
                continue
            pair = manifest_by_id.get(mid)
            if pair is None:
                errors.append(f"composites.{owner}.members 缺少 manifest: {mid}")
                continue
            path, manifest = pair
            if str(manifest.get("composite_owner") or "").strip() != str(owner).strip():
                errors.append(f"{path}: composite_owner 必须为 {owner}")
        root_id = str(raw.get("legacy_root_id") or "").strip()
        if root_id and root_id not in {str(x or "").strip() for x in members}:
            errors.append(f"composites.{owner}.legacy_root_id 不在 members 中")

    if errors:
        print("Mod 分层 SSOT 检查失败：", file=sys.stderr)
        for item in errors:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("Mod 分层 SSOT 一致：策略与显式 manifest 声明有效")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 Mod 分层 SSOT")
    parser.add_argument("command", choices=("check",))
    args = parser.parse_args(argv)
    if args.command == "check":
        return check()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
