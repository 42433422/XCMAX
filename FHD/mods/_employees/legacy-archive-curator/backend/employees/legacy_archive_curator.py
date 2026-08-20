"""Deterministic, read-only legacy archive candidate auditor."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    inventory = dict(payload or {}).get("inventory")
    if not isinstance(inventory, list) or not inventory:
        return _failed("inventory must be a non-empty list", "missing_inventory")
    candidates: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    for index, raw in enumerate(inventory[:500]):
        item = raw if isinstance(raw, dict) else {}
        path = str(item.get("path") or "").strip()[:500]
        references = (
            item.get("referenced_by") if isinstance(item.get("referenced_by"), list) else []
        )
        days = item.get("last_used_days")
        recovery = str(item.get("recovery_path") or "").strip()[:500]
        if not path or path.startswith("/") or ".." in path.split("/"):
            issues.append({"code": "unsafe_inventory_path", "path": f"inventory[{index}].path"})
            continue
        if not isinstance(days, int | float) or float(days) < 0:
            issues.append({"code": "invalid_age", "path": f"inventory[{index}].last_used_days"})
            continue
        if not references and float(days) >= 90:
            if not recovery:
                issues.append(
                    {"code": "missing_recovery_path", "path": f"inventory[{index}].recovery_path"}
                )
            else:
                candidates.append(
                    {"path": path, "last_used_days": float(days), "recovery_path": recovery}
                )
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"遗留资产清单已只读核对：{len(candidates)} 个可归档候选、{len(issues)} 个阻塞项；未移动或删除文件。",
        "archive_candidates": candidates,
        "issues": issues,
        "evidence": [
            "input.inventory",
            "input.inventory.referenced_by",
            "input.inventory.recovery_path",
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
