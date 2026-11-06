"""Unified task lifecycle shared by Agent, Workflow, Employee, and tickets."""

from app.domain.task_lifecycle.adapters import (
    assert_legacy_transition,
    execution_transition_allowed,
    legacy_transition_allowed,
)
from app.domain.task_lifecycle.machine import (
    DEFAULT_MAX_ATTEMPTS,
    STATES,
    TERMINAL,
    retry_delay_seconds,
    transition_allowed,
)

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "STATES",
    "TERMINAL",
    "assert_legacy_transition",
    "execution_transition_allowed",
    "legacy_transition_allowed",
    "retry_delay_seconds",
    "transition_allowed",
]
