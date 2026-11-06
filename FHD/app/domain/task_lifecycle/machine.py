"""Canonical task states. Business code must transition through these rules."""

from __future__ import annotations

STATES = frozenset(
    {
        "created",
        "queued",
        "running",
        "waiting_approval",
        "succeeded",
        "failed",
        "timed_out",
        "cancelled",
        "rejected",
    }
)

TERMINAL = frozenset({"succeeded", "failed", "timed_out", "cancelled", "rejected"})

# failed/timed_out → queued is listed here and still requires retryable=True.
_ALLOWED: dict[str, frozenset[str]] = {
    "created": frozenset({"queued"}),
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"waiting_approval", "succeeded", "failed", "timed_out", "cancelled"}),
    "waiting_approval": frozenset({"queued", "rejected", "cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset({"queued"}),
    "timed_out": frozenset({"queued"}),
    "cancelled": frozenset(),
    "rejected": frozenset(),
}

NON_RETRYABLE_CODES = frozenset(
    {
        "permission_denied",
        "invalid_params",
        "approval_rejected",
        "business_rule",
    }
)

# Delay(n) = min(1 * 2^(n-1), 30), n starts at 1. Jitter is applied by the ledger.
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_WAIT_SECONDS = 30.0


def transition_allowed(
    current: str,
    target: str,
    *,
    retryable: bool = False,
) -> bool:
    """Return whether a business transition is legal.

    Same-state is not a transition. Retry edges require ``retryable``.
    ``running → queued`` is intentionally absent: only the scheduler recovery
    path may requeue an attempt that never opened a side effect.
    """
    if current not in _ALLOWED or target not in STATES:
        return False
    if target not in _ALLOWED[current]:
        return False
    if current in {"failed", "timed_out"} and target == "queued":
        return bool(retryable)
    return True


def retry_delay_seconds(retry_number: int, *, max_wait: float = DEFAULT_MAX_WAIT_SECONDS) -> float:
    """Backoff for the Nth retry. ``retry_number`` starts at 1."""
    step = max(1, int(retry_number))
    return float(min(2 ** (step - 1), max_wait))
