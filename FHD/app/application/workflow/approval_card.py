"""Structured approval_card payload for Chat inline UI (Wave 2)."""

from __future__ import annotations

from typing import Any


def build_approval_card_payload(*, action: str, inner: dict[str, Any]) -> dict[str, Any]:
    blocking = inner.get("blocking_nodes") or []
    if not isinstance(blocking, list):
        blocking = []
    approval_nodes = inner.get("approval_nodes") or []
    if not isinstance(approval_nodes, list):
        approval_nodes = []
    todo = inner.get("todo") or inner.get("todo_steps") or []
    if not isinstance(todo, list):
        todo = []

    approval_required = bool(inner.get("approval_required"))
    confirm_mode = "approval" if approval_required else "interactive"
    try:
        from resources.config.risk_actions_loader import get_action_approval

        for node in approval_nodes:
            if not isinstance(node, dict):
                continue
            tool_id = str(node.get("tool_id") or "").strip()
            act = str(node.get("action") or "execute").strip()
            if tool_id and get_action_approval(tool_id, act) == "always":
                approval_required = True
                confirm_mode = "approval"
    except Exception:  # noqa: BLE001
        pass

    return {
        "version": 1,
        "kind": str(action or "workflow_confirmation_required"),
        "plan_id": inner.get("plan_id"),
        "run_id": inner.get("run_id") or inner.get("agent_run_id"),
        "agent_run_id": inner.get("agent_run_id") or inner.get("run_id"),
        "intent": inner.get("intent"),
        "blocking_nodes": [str(x) for x in blocking if x],
        "approval_required": approval_required,
        "approval_nodes": approval_nodes,
        "approval_request_ids": inner.get("approval_request_ids") or [],
        "approval_path": str(inner.get("approval_path") or "").strip(),
        "todo": [str(x) for x in todo if x],
        "reason": str(inner.get("reason") or "").strip(),
        "confirm_mode": confirm_mode,
    }


__all__ = ["build_approval_card_payload"]
