"""Public, evidence-backed Goal/Loop items from strategic council receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

_PUBLIC_STATUS = {
    "auto_approved": "dispatched",
    "approved": "dispatched",
    "executing": "in_progress",
    "completed": "merged",
    "reviewed": "merged",
    "rejected": "closed",
    "withdrawn": "closed",
}
_STATUS_LABEL = {
    "open": "待处理",
    "dispatched": "已派发",
    "in_progress": "进行中",
    "merged": "已闭环",
    "closed": "已关闭",
}


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def verified_strategic_goal_items(*, limit: int = 100) -> list[dict[str, Any]]:
    """Expose only DB Goals linked by a verified council hash chain."""

    from modstore_server.db.base import get_session_factory
    from modstore_server.db.strategic import StrategicDecision
    from modstore_server.strategic_council import strategic_council_status

    status = strategic_council_status(limit=limit)
    if (
        status.get("ok") is not True
        or status.get("hash_chain_verified") is not True
        or status.get("ready") is not True
    ):
        return []
    receipts = [
        row
        for row in (status.get("recent_receipts") or [])
        if isinstance(row, dict)
        and row.get("verified") is True
        and str(row.get("goal_id") or "").strip()
        and str(row.get("loop_run_id") or "").strip()
        and str(row.get("para_task_id") or "").strip()
        and ((row.get("roles") or {}).get("para") or {}).get("status") == "linked"
        and ((row.get("roles") or {}).get("para") or {}).get("source_verified") is True
    ]
    goal_ids = list(dict.fromkeys(str(row["goal_id"]).strip() for row in receipts))
    if not goal_ids:
        return []

    with get_session_factory()() as session:
        goals = {
            str(row.decision_id): row
            for row in session.query(StrategicDecision)
            .filter(StrategicDecision.decision_id.in_(goal_ids))
            .all()
        }

    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for receipt in reversed(receipts):
        goal_id = str(receipt["goal_id"]).strip()
        goal = goals.get(goal_id)
        if goal is None or goal_id in seen:
            continue
        seen.add(goal_id)
        raw_status = str(goal.status or "proposed").lower()
        public_status = _PUBLIC_STATUS.get(raw_status, "open")
        created_at = str(receipt.get("created_at") or _iso(goal.created_at))
        output.append(
            {
                "title": str(goal.title or goal_id).strip()[:180],
                "priority": "P1" if str(goal.decision_type or "") == "strategic" else "P2",
                "status": public_status,
                "status_label": _STATUS_LABEL[public_status],
                "line": "P-S",
                "line_label": "软件线",
                "owner": "Para · 变更评审员",
                "employee_id": "change-request-auditor",
                "kind": "update",
                "day": created_at[:10],
                "updated_at": _iso(goal.updated_at or goal.created_at)[:40],
                "ts": created_at[11:16] if len(created_at) >= 16 else "",
                "source": "verified_strategic_council",
                "goal_id": goal_id,
                "loop_run_id": str(receipt["loop_run_id"]).strip(),
                "para_task_id": str(receipt["para_task_id"]).strip(),
                "receipt_id": str(receipt.get("receipt_id") or "").strip(),
            }
        )
    return output


__all__ = ["verified_strategic_goal_items"]
