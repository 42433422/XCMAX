"""Owner-facing Work Order list and approval operations."""

from __future__ import annotations

from typing import Any


def _receipts(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
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


def _ready(view: dict[str, Any]) -> bool:
    receipts = _receipts(view)
    return view.get("status") == "in_dev" and all(
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
                "can_decide": is_owner and _ready(view),
                "gates": {name: rec.get("gate_status") for name, rec in receipts.items()},
            }
        )
    return items


def decide_owner_work_order(
    wo_id: str, decision: str, *, local_user_id: int, actor: str, note: str = ""
) -> dict[str, Any]:
    from app.services.work_order_gate import record_gate
    from app.services.work_order_ssot import get_work_order

    view = get_work_order(wo_id)
    if not view:
        return {"ok": False, "reason": "unknown_work_order"}
    if not _ready(view):
        return {"ok": False, "reason": "gates_incomplete"}
    return record_gate(
        wo_id,
        "owner_approval",
        decision,
        evidence={"local_user_id": int(local_user_id), "actor": actor},
        note=note[:500],
        source="owner_console",
    )
