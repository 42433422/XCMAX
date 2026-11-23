"""Map legacy module statuses onto the canonical task state machine."""

from __future__ import annotations

from app.domain.task_lifecycle.machine import STATES, transition_allowed

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
        "blocked": "blocked",
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
        "pending": "queued",
        "accepted": "queued",
        "running": "running",
        "awaiting_approval": "waiting_approval",
        "waiting_approval": "waiting_approval",
        "success": "succeeded",
        "succeeded": "succeeded",
        "completed": "succeeded",
        # Unverified employee results stay non-success. They are not a retry.
        "unknown": "unknown",
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
    token = str(status or "").strip().lower()
    canonical = table.get(token, token if token in STATES else None)
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


LEASED_STATES = frozenset({"running", "claimed"})
APPROVAL_STATES = frozenset({"waiting_approval"})
WAITING_STATES = APPROVAL_STATES | {"waiting_input", "waiting_auth", "paused", "blocked"}
SUCCEEDED_STATES = frozenset({"succeeded", "completed"})


def canonical_execution_state(state: str) -> str:
    """Map transport aliases without erasing pause, input or uncertain effects."""
    return _EXECUTION.get(str(state or "").strip().lower(), str(state or "").strip().lower())


_EXECUTION = {
    **{state: state for state in STATES},
    "claimed": "running",
    "running": "running",
    "outcome_unknown": "unknown",
    "completed": "succeeded",
}


def execution_transition_allowed(
    current: str,
    target: str,
    *,
    retryable: bool = False,
) -> bool:
    """Scheduler queue words mapped onto the canonical machine before a write."""
    current_state = _EXECUTION.get(str(current or "").strip().lower())
    target_state = _EXECUTION.get(str(target or "").strip().lower())
    if current_state is None or target_state is None:
        return False
    if current_state == target_state:
        return True
    return transition_allowed(current_state, target_state, retryable=retryable)


def execution_requeue_allowed(current: str, *, retryable: bool = False) -> bool:
    """Enqueue may reopen only a legal non-terminal queue state."""
    state = str(current or "queued")
    if state == "queued":
        return True
    return execution_transition_allowed(state, "queued", retryable=retryable)


def assert_legacy_transition(
    module: str,
    current: str,
    target: str,
    *,
    retryable: bool = False,
) -> None:
    if not legacy_transition_allowed(module, current, target, retryable=retryable):
        raise LegacyTransitionError(f"非法任务状态转换: {module} {current} → {target}")
