"""Owner-facing Work Order list and approval operations."""

from __future__ import annotations

from typing import Any


def _receipts(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    receipts = {
        name: {
            **event,
            "gate_status": str(event.get("gate_status") or ref.get("gate_status") or ""),
        }
        for event in view.get("history") or []
        if event.get("event") == "gate"
        for ref in [event.get("ref") if isinstance(event.get("ref"), dict) else {}]
        for name in [str(event.get("gate") or ref.get("gate") or "")]
        if name
    }
    decision = next(
        (
            row
            for row in reversed(view.get("history") or [])
            if row.get("event") == "transition"
            and isinstance(row.get("ref"), dict)
            and row["ref"].get("owner_decision")
        ),
        None,
    )
    if decision:
        receipts["owner_approval"] = {
            "gate_status": decision["ref"]["owner_decision"],
            "note": decision.get("note", ""),
            "at": decision.get("at", ""),
        }
    return receipts


def _ready(view: dict[str, Any]) -> bool:
    receipts = _receipts(view)
    return all(
        receipts.get(gate, {}).get("gate_status") == status
        for gate, status in (
            ("repro", "RED"),
            ("fix", "FIX_VALIDATED_IN_DEV"),
            ("owner_instance", "OWNER_INSTANCE_VERIFIED"),
        )
    )


def list_owner_work_orders(limit: int = 200, *, is_owner: bool = False) -> list[dict[str, Any]]:
    from app.services.work_order_ssot import list_work_orders

    items = []
    for view in list_work_orders(limit=max(1, min(int(limit), 500))):
        receipts = _receipts(view)
        items.append(
            {
                **view,
                "owner_instance_verified": receipts.get("owner_instance", {}).get("gate_status")
                == "OWNER_INSTANCE_VERIFIED",
                "can_decide": is_owner and view.get("status") == "in_dev" and _ready(view),
                "can_resume": is_owner and view.get("status") == "held" and _ready(view),
                "gates": {name: rec.get("gate_status") for name, rec in receipts.items()},
            }
        )
    return items


def decide_owner_work_order(
    wo_id: str, decision: str, *, local_user_id: int, actor: str, note: str = ""
) -> dict[str, Any]:
    from app.services.work_order_ssot import get_work_order, record_transition

    view = get_work_order(wo_id)
    if not view:
        return {"ok": False, "reason": "unknown_work_order"}
    targets = {"approved": "approved", "rejected": "rework", "held": "held", "resume": "in_dev"}
    target = targets.get(decision)
    if target is None:
        return {"ok": False, "reason": "invalid_decision"}
    resumable = decision == "resume" and view.get("status") == "held"
    reviewable = decision in {"approved", "rejected", "held"} and view.get("status") == "in_dev"
    if not _ready(view) or not (resumable or reviewable):
        return {"ok": False, "reason": "gates_incomplete"}
    if decision in {"rejected", "held"} and len(str(note or "").strip()) < 4:
        return {"ok": False, "reason": "decision_note_required"}
    effective_note = str(note or "").strip()
    if decision == "resume" and not effective_note:
        effective_note = "Owner 恢复处理"
    result = record_transition(
        wo_id,
        target,
        ref={"owner_decision": decision, "local_user_id": int(local_user_id), "actor": actor},
        note=effective_note[:500],
        source="owner_console",
    )
    if result.get("ok"):
        return {**result, "decision": decision, "status": target}
    return result
