"""XCAGI Business Harness protocol helpers.

The harness keeps a business conversation (thread), one user turn, one durable
task, one or more execution attempts, approval gates, events, and the terminal
business result as separate identities.  The helpers in this module are pure so
all execution entry points can share the same contract.
"""

from __future__ import annotations

import uuid
from typing import Any

BUSINESS_HARNESS_PROTOCOL = "xcagi.business-harness.v1"
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})

_FACT_KEYS = (
    "id",
    "customer_id",
    "product_id",
    "material_id",
    "order_id",
    "record_id",
    "request_id",
    "request_no",
    "order_number",
    "document_id",
    "doc_name",
    "name",
    "created",
    "updated",
    "deleted",
    "count",
    "total",
)


def _text(value: Any, *, limit: int = 512) -> str:
    return str(value or "").strip()[:limit]


def ensure_business_harness_context(
    context: dict[str, Any] | None,
    *,
    message: str = "",
) -> dict[str, Any]:
    """Return a context with stable turn/task IDs without conflating the thread."""
    normalized = dict(context or {})
    conversation_id = _text(
        normalized.get("conversation_id") or normalized.get("session_id"), limit=160
    )
    turn_id = _text(normalized.get("turn_id"), limit=160) or f"turn_{uuid.uuid4().hex}"
    task_id = _text(normalized.get("task_id"), limit=160) or f"task_{uuid.uuid4().hex}"
    normalized.update(
        {
            "business_harness_protocol": BUSINESS_HARNESS_PROTOCOL,
            "turn_id": turn_id,
            "task_id": task_id,
        }
    )
    if conversation_id:
        normalized["conversation_id"] = conversation_id
        normalized.setdefault("session_id", conversation_id)
    if message and not _text(normalized.get("task_title"), limit=80):
        normalized["task_title"] = _text(message, limit=80)
    return normalized


def harness_event_context(run: Any) -> dict[str, Any]:
    """Build the identity envelope attached to every durable run event."""
    metadata = getattr(run, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    task = metadata.get("task_context")
    task = task if isinstance(task, dict) else {}
    runtime = metadata.get("runtime_context")
    runtime = runtime if isinstance(runtime, dict) else {}
    try:
        attempt = max(1, int(task.get("attempt") or 1))
    except (TypeError, ValueError):
        attempt = 1
    return {
        "protocol": BUSINESS_HARNESS_PROTOCOL,
        "task_id": _text(
            task.get("task_id") or runtime.get("task_id") or getattr(run, "run_id", ""), limit=160
        ),
        "turn_id": _text(task.get("turn_id") or runtime.get("turn_id"), limit=160),
        "conversation_id": _text(
            task.get("conversation_id")
            or runtime.get("conversation_id")
            or runtime.get("session_id"),
            limit=160,
        ),
        "run_id": _text(getattr(run, "run_id", ""), limit=96),
        "attempt": attempt,
    }


def _iter_result_payloads(run: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    final_output = getattr(run, "final_output", {})
    final_output = final_output if isinstance(final_output, dict) else {}
    node_outputs = final_output.get("node_outputs")
    if isinstance(node_outputs, dict):
        payloads.extend(value for value in node_outputs.values() if isinstance(value, dict))
    for step in getattr(run, "steps", []) or []:
        output = getattr(step, "output", {})
        if isinstance(output, dict) and output not in payloads:
            payloads.append(output)
    chat_payload = final_output.get("chat_payload")
    if isinstance(chat_payload, dict):
        payloads.append(chat_payload)
    return payloads


def _result_summary(run: Any, payloads: list[dict[str, Any]]) -> str:
    status = _text(getattr(run, "status", ""), limit=32)
    if status == "failed":
        return "业务任务执行失败，详细信息已记录"
    if status == "cancelled":
        return "业务任务已取消，未继续执行"
    for payload in reversed(payloads):
        raw_nested = payload.get("data")
        nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
        for candidate in (
            payload.get("response"),
            payload.get("message"),
            nested.get("message"),
            nested.get("summary"),
        ):
            text = _text(candidate, limit=800)
            if text:
                return text
    return "业务任务已完成"


def _result_facts(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for payload in payloads:
        raw_nested = payload.get("data")
        nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
        for source in (payload, nested):
            for key in _FACT_KEYS:
                value = source.get(key)
                if isinstance(value, (str, int, float, bool)) and value not in ("", None):
                    facts[key] = value
    return facts


def ensure_terminal_business_result(run: Any) -> dict[str, Any]:
    """Attach a bounded, user-readable terminal result to a completed run."""
    status = _text(getattr(run, "status", ""), limit=32)
    if status not in TERMINAL_RUN_STATUSES:
        return {}
    final_output = getattr(run, "final_output", {})
    final_output = dict(final_output) if isinstance(final_output, dict) else {}
    existing = final_output.get("business_result")
    if isinstance(existing, dict) and existing.get("protocol") == BUSINESS_HARNESS_PROTOCOL:
        return dict(existing)
    payloads = _iter_result_payloads(run)
    identity = harness_event_context(run)
    artifacts = getattr(run, "artifacts", []) or []
    result = {
        "protocol": BUSINESS_HARNESS_PROTOCOL,
        "status": status,
        "success": status == "completed",
        "summary": _result_summary(run, payloads),
        "facts": _result_facts(payloads),
        "task_id": identity["task_id"],
        "turn_id": identity["turn_id"],
        "conversation_id": identity["conversation_id"],
        "run_id": identity["run_id"],
        "attempt": identity["attempt"],
        "evidence": {
            "event_count": len(getattr(run, "events", []) or []),
            "completed_tool_count": sum(
                str(getattr(call, "status", "")) == "completed"
                for call in (getattr(run, "tool_calls", []) or [])
            ),
            "artifact_ids": [
                _text(getattr(artifact, "artifact_id", ""), limit=96)
                for artifact in artifacts
                if _text(getattr(artifact, "artifact_id", ""), limit=96)
            ],
        },
        "projection_key": f"{BUSINESS_HARNESS_PROTOCOL}:{identity['run_id']}:{status}",
    }
    final_output["business_result"] = result
    run.final_output = final_output
    return result


__all__ = [
    "BUSINESS_HARNESS_PROTOCOL",
    "TERMINAL_RUN_STATUSES",
    "ensure_business_harness_context",
    "ensure_terminal_business_result",
    "harness_event_context",
]
