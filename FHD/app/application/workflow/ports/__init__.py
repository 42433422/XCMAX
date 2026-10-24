"""Workflow application ports.

``WorkflowRuntime`` is defined here (needs application plan/result types).
Checkpoint/events/tools protocols are re-exported from ``app.domain.workflow.ports``.
Do not add new port modules under this package (structure gate G5).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.application.workflow.types import PlanGraph, StateSchema, WorkflowRunResult
from app.domain.workflow.ports import (
    Checkpoint,
    CheckpointStore,
    EventBusPort,
    StateEventPublisher,
    StateUpdateEvent,
    StateUpdatePayload,
    StateUpdateStatus,
    ToolCall,
    ToolDispatcher,
    ToolResult,
)

__all__ = [
    "WorkflowRuntime",
    "Callback",
    "CheckpointStore",
    "Checkpoint",
    "EventBusPort",
    "StateEventPublisher",
    "StateUpdateEvent",
    "StateUpdatePayload",
    "StateUpdateStatus",
    "ToolDispatcher",
    "ToolCall",
    "ToolResult",
    "PlanGraph",
    "StateSchema",
    "WorkflowRunResult",
]


@runtime_checkable
class Callback(Protocol):
    """A state event callback (e.g. ``{"type": "state.update", ...}``)."""

    def __call__(self, event: dict[str, Any]) -> None: ...


@runtime_checkable
class WorkflowRuntime(Protocol):
    """Execute, resume, and replay a workflow plan."""

    def run(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        max_retries: int = 1,
        agentic_loop: bool = False,
        tool_registry: dict[str, Any] | None = None,
        user_id: str | None = None,
        state_schema: StateSchema | None = None,
        parallel: bool = True,
        checkpointer: Any | None = None,
        state_event_callback: Callback | None = None,
    ) -> WorkflowRunResult:
        """Execute ``plan`` and return the run result."""
        ...

    def resume_run(
        self,
        plan: PlanGraph,
        checkpoint_id: str,
        *,
        checkpointer: Any,
        max_retries: int = 1,
        state_schema: StateSchema | None = None,
        parallel: bool = True,
    ) -> WorkflowRunResult:
        """Resume execution from ``checkpoint_id`` without re-running completed nodes."""
        ...

    def replay_run(
        self,
        plan_id: str,
        checkpoint_id: str | None = None,
        *,
        checkpointer: Any,
    ) -> WorkflowRunResult:
        """Read-only replay of executed node outputs from a checkpoint."""
        ...
