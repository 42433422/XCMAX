"""Retry classification for self-maintenance employee dispatch failures."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional

_FAILURE_TEXT_KEYS = frozenset(
    {"content", "detail", "error", "message", "reason", "status", "stderr", "stdout"}
)
_TRANSIENT_TERMS = (
    "client network socket disconnected before secure tls connection",
    "connection refused",
    "econnrefused",
    "econnreset",
    "para api 调用失败",
    "para_api_failed_outboxed",
    "para_api_rejected_outboxed",
    "report-only 执行器失败",
    "socket hang up",
    "ssl_error_syscall",
    "timeout waiting for para",
    "未在线",
)


def _failure_texts(value: Any, *, depth: int = 0) -> Iterable[str]:
    if depth > 6:
        return
    if isinstance(value, dict):
        for key, item in list(value.items())[:24]:
            if str(key).lower() in _FAILURE_TEXT_KEYS and isinstance(item, str):
                yield item
            if isinstance(item, (dict, list)):
                yield from _failure_texts(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value[:12]:
            yield from _failure_texts(item, depth=depth + 1)


def is_transient_dispatch_failure(result: Any) -> bool:
    """Recognize bounded-retry transport failures, including long CLI wrappers.

    Agent wrappers can echo a multi-kilobyte prompt before appending the real
    transport exception. Inspecting each failure field's tail preserves that
    root cause without scanning arbitrary successful report text.
    """

    for raw_text in _failure_texts(result):
        text = raw_text[-8000:].lower()
        if any(term in text for term in _TRANSIENT_TERMS):
            return True
    return False


def successful_code_resume_resolution(final: Any) -> Optional[Dict[str, str]]:
    """Return identifiers for a resume candidate replaced by delivered code."""

    if not isinstance(final, dict):
        return None
    resume_candidate = final.get("resume_candidate")
    steps = final.get("steps")
    if not isinstance(resume_candidate, dict) or not isinstance(steps, list):
        return None
    if not any(
        isinstance(step, dict) and step.get("step") == "code" and step.get("ok") is True
        for step in steps
    ):
        return None
    return {
        "branch": str(resume_candidate.get("branch") or ""),
        "run_id": str(resume_candidate.get("failed_run_id") or ""),
        "task_id": str(resume_candidate.get("para_task_id") or ""),
    }


def close_successful_code_resume(
    memory: Dict[str, Any],
    final: Dict[str, Any],
    close_items: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    """Close only the prior retry item after replacement code is delivered."""

    resolution = successful_code_resume_resolution(final)
    if not resolution:
        return {"closed_count": 0, "closed_items": []}
    return close_items(
        memory,
        actor="self_maintenance_loop",
        branches=[resolution["branch"]],
        resolution_reason="superseded_by_successful_code_step",
        run_ids=[resolution["run_id"]],
        task_ids=[resolution["task_id"]],
    )
