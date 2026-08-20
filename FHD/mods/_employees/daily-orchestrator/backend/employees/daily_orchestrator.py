"""Deterministic, read-only daily work prioritizer."""

from __future__ import annotations

from typing import Any

EMPLOYEE_ID = "daily-orchestrator"
_PRIORITY = {"p0": 0, "p1": 1, "p2": 2, "p3": 3}
_SENSITIVE = {"token", "secret", "password", "api_key", "access_token", "private_key"}


def _has_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).strip().lower() in _SENSITIVE or _has_sensitive_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_sensitive_key(item) for item in value)
    return False


def _failure(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message[:500],
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Prioritize supplied work without dispatching, changing, or messaging anything."""

    data = dict(payload or {})
    if str(data.get("action") or "prioritize_work_items") != "prioritize_work_items":
        return _failure("unsupported action", "unsupported_action")
    if _has_sensitive_key(data):
        return _failure("输入包含禁止进入编排回执的敏感字段", "sensitive_input_blocked")
    raw_items = data.get("work_items")
    if not isinstance(raw_items, list) or not raw_items:
        return _failure("work_items must be a non-empty list", "missing_work_items")

    normalized: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_items[:200]):
        item = raw if isinstance(raw, dict) else {}
        item_id = str(item.get("id") or "").strip()[:160]
        priority = str(item.get("priority") or "p2").strip().lower()
        acceptance = item.get("acceptance") if isinstance(item.get("acceptance"), list) else []
        blockers = item.get("blocked_by") if isinstance(item.get("blocked_by"), list) else []
        if not item_id:
            issues.append({"code": "missing_id", "path": f"work_items[{index}].id"})
            continue
        if item_id in seen:
            issues.append({"code": "duplicate_id", "path": f"work_items[{index}].id"})
            continue
        seen.add(item_id)
        if priority not in _PRIORITY:
            issues.append({"code": "invalid_priority", "path": f"work_items[{index}].priority"})
            priority = "p2"
        normalized.append(
            {
                "id": item_id,
                "priority": priority,
                "risk_level": str(item.get("risk_level") or "medium").strip().lower()[:32],
                "blocked_by": [
                    str(value).strip()[:160] for value in blockers if str(value).strip()
                ],
                "acceptance": [
                    str(value).strip()[:300] for value in acceptance if str(value).strip()
                ],
            }
        )

    ordered = sorted(
        normalized,
        key=lambda item: (
            bool(item["blocked_by"]),
            _PRIORITY[item["priority"]],
            item["id"],
        ),
    )
    queue = [{**item, "queue_position": position} for position, item in enumerate(ordered, start=1)]
    status = "approved" if not issues else "rejected"
    summary = (
        f"已只读核对 {len(raw_items[:200])} 项每日工作："
        f"形成 {len(queue)} 项优先队列，发现 {len(issues)} 个契约问题；未执行派工。"
    )
    return {
        "ok": True,
        "status": status,
        "summary": summary,
        "queue": queue,
        "issues": issues,
        "ready_count": sum(not item["blocked_by"] for item in queue),
        "blocked_count": sum(bool(item["blocked_by"]) for item in queue),
        "evidence": [f"input.work_items[{index}]" for index in range(len(raw_items[:200]))],
        "read_only": True,
        "side_effects": [],
        "meta": {
            "employee_id": EMPLOYEE_ID,
            "contract_version": "1.0",
            "workspace_root_present": bool(str((ctx or {}).get("workspace_root") or "")),
        },
    }
