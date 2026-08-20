"""Deterministic, read-only Mod and ESkill registry consistency auditor."""

from __future__ import annotations

from collections import Counter
from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    registry = dict(payload or {}).get("asset_registry")
    if not isinstance(registry, dict):
        return _failed("asset_registry object is required", "missing_asset_registry")
    issues: list[dict[str, str]] = []
    rows: list[tuple[str, str, str]] = []
    for group in ("mods", "eskills", "employee_packs"):
        values = registry.get(group) if isinstance(registry.get(group), list) else []
        for index, raw in enumerate(values[:300]):
            item = raw if isinstance(raw, dict) else {}
            asset_id = str(item.get("id") or "").strip()[:160]
            version = str(item.get("version") or "").strip()[:80]
            if not asset_id or not version:
                issues.append(
                    {"code": "missing_identity", "path": f"asset_registry.{group}[{index}]"}
                )
            else:
                rows.append((group, asset_id, version))
    duplicate_ids = sorted(
        key for key, count in Counter(row[1] for row in rows).items() if count > 1
    )
    for asset_id in duplicate_ids:
        issues.append({"code": "duplicate_asset_id", "path": asset_id})
    references = registry.get("references") if isinstance(registry.get("references"), list) else []
    known = {row[1] for row in rows}
    for index, raw in enumerate(references[:400]):
        ref = raw if isinstance(raw, dict) else {}
        if str(ref.get("from") or "") not in known or str(ref.get("to") or "") not in known:
            issues.append(
                {"code": "dangling_reference", "path": f"asset_registry.references[{index}]"}
            )
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"Mod/ESkill 注册表已只读核对：{len(rows)} 项资产、{len(references)} 条引用、{len(issues)} 个阻塞项；未上架或写注册表。",
        "asset_count": len(rows),
        "issues": issues,
        "registry_consistent": not issues,
        "evidence": [
            "input.asset_registry.mods",
            "input.asset_registry.eskills",
            "input.asset_registry.employee_packs",
            "input.asset_registry.references",
        ],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
