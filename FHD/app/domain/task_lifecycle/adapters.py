"""Map legacy module statuses onto the canonical task state machine."""

from __future__ import annotations

from app.domain.task_lifecycle.machine import transition_allowed

# Values are canonical states. Unknown legacy tokens are rejected.
_LEGACY: dict[str, dict[str, str]] = {
    "agent": {
        "created": "created",
        "queued": "queued",
        "planning": "queued",
        "retrying": "queued",
        "claimed": "running",
        "running": "running",
        "waiting_user": "waiting_approval",
        "waiting_approval": "waiting_approval",
        "completed": "succeeded",
        "succeeded": "succeeded",
        "failed": "failed",
        "timed_out": "timed_out",
        "cancelled": "cancelled",
        "rejected": "rejected",
        "blocked": "failed",
    },
    "workflow": {
        "pending": "queued",
        "created": "created",
        "queued": "queued",
        "running": "running",
        "awaiting_approval": "waiting_approval",
        "waiting_approval": "waiting_approval",
        "succeeded": "succeeded",
        "failed": "failed",
        "timed_out": "timed_out",
        "cancelled": "cancelled",
        "rejected": "rejected",
    },
    "employee": {
        "unknown": "created",
        "pending": "queued",
        "accepted": "queued",
        "running": "running",
        "awaiting_approval": "waiting_approval",
        "waiting_approval": "waiting_approval",
        "success": "succeeded",
        "succeeded": "succeeded",
        "completed": "succeeded",
        "failed": "failed",
        "timed_out": "timed_out",
        "cancelled": "cancelled",
        "rejected": "rejected",
    },
    "ticket": {
        "created": "created",
        "open": "queued",
        "queued": "queued",
        "running": "running",
        "waiting_approval": "waiting_approval",
        "resolved": "succeeded",
        "succeeded": "succeeded",
        "failed": "failed",
        "timed_out": "timed_out",
        "cancelled": "cancelled",
        "rejected": "rejected",
    },
}


class LegacyTransitionError(ValueError):
    """A module tried to move a task outside the shared state machine."""


def canonicalize(module: str, status: str) -> str:
    table = _LEGACY.get(module)
    if table is None:
        raise LegacyTransitionError(f"未知任务模块: {module}")
    canonical = table.get(str(status or "").strip().lower())
    if canonical is None:
        raise LegacyTransitionError(f"{module} 状态未纳入统一状态机: {status}")
    return canonical


def legacy_transition_allowed(
    module: str,
    current: str,
    target: str,
    *,
    retryable: bool = False,
) -> bool:
    current_state = canonicalize(module, current)
    target_state = canonicalize(module, target)
    if current_state == target_state:
        return True
    return transition_allowed(current_state, target_state, retryable=retryable)


def assert_legacy_transition(
    module: str,
    current: str,
    target: str,
    *,
    retryable: bool = False,
) -> None:
    if not legacy_transition_allowed(module, current, target, retryable=retryable):
        raise LegacyTransitionError(f"非法任务状态转换: {module} {current} → {target}")
