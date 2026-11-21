"""Node construction and pending-session lifecycle for clarification gates."""

from __future__ import annotations

import os
import time
import uuid
from copy import deepcopy
from typing import Any

from .workflow_types import Branch, PlanGraph, WorkflowNode

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
            "clarification": deepcopy(ambient.get("clarification") or {}),
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
    if not isinstance(entry, dict) or entry.get("kind") not in {
        "clarification",
        "clarification_unbound",
    }:
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


_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _chinese_ordinal(text: str) -> int | None:
    """解析「第二个 / 第2个 / 就第二个 / 第二项」等口语序号。

    排除被否定的序号：「不是第一个，是第二个」应取 2，而不是 1。
    """
    import re

    ordinal = r"第\s*([0-9]+|[一二两三四五六七八九]?十[一二三四五六七八九]?|[一二两三四五六七八九])\s*(?:个|项|条|位|号)?"
    normalized = text.strip().rstrip("。!！")
    correction = re.fullmatch(rf"(?:不是|不要|不选){ordinal}\s*[,，]\s*(.+)", normalized)
    if correction:
        normalized = correction.group(2)
    match = re.fullmatch(rf"(?:就|选|选择|要|是)?\s*{ordinal}", normalized)
    if match is None:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    if "十" in raw:
        before, _, after = raw.partition("十")
        return (_CN_DIGITS[before] if before else 1) * 10 + (_CN_DIGITS[after] if after else 0)
    return _CN_DIGITS[raw]


def resolve_confirmed_target(
    message: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Accept only a unique exact ID, name, or unambiguous one-based position."""
    if not candidates:
        return None
    text = str(message or "").strip()
    if not text:
        return None
    matches = {
        str(candidate["id"])
        for candidate in candidates
        if isinstance(candidate, dict)
        and candidate.get("id") not in (None, "")
        and text
        in {
            str(candidate.get(key) or "").strip()
            for key in ("id", "name", "customer_name", "unit_name", "product_name", "material_name")
        }
    }
    index = int(text) if text.isdigit() else _chinese_ordinal(text)
    if index is not None:
        if 1 <= index <= len(candidates):
            candidate = candidates[index - 1]
            if isinstance(candidate, dict) and candidate.get("id") not in (None, ""):
                matches.add(str(candidate["id"]))
    return {"id": matches.pop()} if len(matches) == 1 else None
