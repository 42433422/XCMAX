"""Unified task lifecycle shared by Agent, Workflow, Employee, and tickets."""

from app.domain.task_lifecycle.adapters import (
    assert_legacy_transition,
    legacy_transition_allowed,
)
from app.domain.task_lifecycle.ledger import TaskLedger, TaskLifecycleError
from app.domain.task_lifecycle.machine import (
    STATES,
    TERMINAL,
    retry_delay_seconds,
    transition_allowed,
)

__all__ = [
    "STATES",
    "TERMINAL",
    "TaskLedger",
    "TaskLifecycleError",
    "assert_legacy_transition",
    "legacy_transition_allowed",
    "retry_delay_seconds",
    "transition_allowed",
]
