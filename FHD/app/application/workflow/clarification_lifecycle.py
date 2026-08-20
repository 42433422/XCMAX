"""Node construction and pending-session lifecycle for clarification gates."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from .types import Branch, PlanGraph, WorkflowNode

DEFAULT_TTL_SECONDS = 1800


def clarification_ttl_seconds() -> int:
    try:
        return max(
            30,
            int(os.environ.get("XCAGI_CLARIFICATION_TTL_SECONDS") or DEFAULT_TTL_SECONDS),
        )
    except ValueError:
        return DEFAULT_TTL_SECONDS


def build_clarify_node(
    question: str,
    ambient: dict[str, Any] | None = None,
) -> WorkflowNode:
    """Create a clarification node that pauses before its target operation."""
    ambient = ambient or {}
    node_id = str(ambient.get("node_id") or f"clarify_{uuid.uuid4().hex[:8]}")
    target = str(ambient.get("target_node_id") or "")
    return WorkflowNode(
        node_id=node_id,
        tool_id="clarify",
        action="ask",
        params={
            "question": str(question or ""),
            "answer_key": str(ambient.get("answer_key") or "confirmed"),
            "target_node_id": target,
        },
        risk="low",
        idempotent=True,
        description="反问澄清：写/高风险操作参数缺失或歧义，待用户确认后再继续",
        branches=[Branch(target=target, condition={"key": "answer_confirmed", "equals": True})],
        next=ambient.get("cancel_node_id"),
    )


def insert_clarify_node(plan: PlanGraph, clarify_node: WorkflowNode) -> None:
    """Append a clarification node once."""
    if any(node.node_id == clarify_node.node_id for node in plan.nodes):
        return
    plan.nodes.append(clarify_node)


def entry_is_expired(entry: dict[str, Any] | None, now: float | None = None) -> bool:
    """Return whether one pending clarification has exceeded its TTL."""
    if not isinstance(entry, dict) or entry.get("kind") != "clarification":
        return False
    now = time.time() if now is None else now
    try:
        created = float(entry.get("created_at") or 0)
    except (TypeError, ValueError):
        created = 0.0
    try:
        ttl = float(entry.get("ttl_seconds") or clarification_ttl_seconds())
    except (TypeError, ValueError):
        ttl = float(clarification_ttl_seconds())
    return created > 0 and (now - created) > ttl


def sweep_expired(entries: dict[str, Any], now: float | None = None) -> list[str]:
    """Remove all expired pending clarifications and return their user IDs."""
    now = time.time() if now is None else now
    expired: list[str] = []
    for user_id, entry in list(entries.items()):
        if entry_is_expired(entry, now):
            expired.append(str(user_id))
            entries.pop(user_id, None)
    return expired


def make_pending_entry(
    *,
    plan: PlanGraph,
    runtime_context: dict[str, Any],
    thinking_steps: str,
    clarification: dict[str, Any],
    clarify_node_id: str,
    target_node_id: str,
    now: float | None = None,
) -> dict[str, Any]:
    """Build the clarification form of an AI-chat pending workflow entry."""
    return {
        "plan": plan,
        "runtime_context": runtime_context,
        "pending_id": uuid.uuid4().hex,
        "thinking_steps": thinking_steps,
        "kind": "clarification",
        "clarify_node_id": clarify_node_id,
        "target_node_id": target_node_id,
        "clarification": clarification,
        "created_at": time.time() if now is None else now,
        "ttl_seconds": clarification_ttl_seconds(),
        "approval_required": False,
        "approval_nodes": [],
    }


def resolve_confirmed_target(
    message: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve a candidate by exact ID, name, or one-based list position."""
    if not candidates:
        return None
    text = str(message or "").strip()
    if not text:
        return None
    for candidate in candidates:
        candidate_id = str(candidate.get("id") or "").strip()
        if candidate_id and candidate_id == text:
            return {"id": candidate_id}
    for candidate in candidates:
        name = str(
            candidate.get("name")
            or candidate.get("customer_name")
            or candidate.get("unit_name")
            or ""
        ).strip()
        if name and (name == text or name in text or text in name):
            return {"id": str(candidate.get("id") or "")}
    if text.isdigit():
        index = int(text)
        if 1 <= index <= len(candidates):
            return {"id": str(candidates[index - 1].get("id") or "")}
    return None
