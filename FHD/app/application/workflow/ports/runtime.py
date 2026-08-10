"""WorkflowRuntime port — contract for the workflow execution runtime.

Defines the runtime contract consumed by the application layer. Both the legacy
``WorkflowEngine`` (via ``LegacyEngineAdapter``) and the LangGraph runtime
(``infrastructure/workflow/langgraph_runtime.py``) implement this port, and the
infrastructure selector switches between them.

Method signatures mirror the legacy ``WorkflowEngine`` API so adapters map 1:1.
This port depends only on application/domain types and ``Any`` — never on
``app.infrastructure``, ``app.neuro_bus``, ``langgraph``, ``sqlalchemy``, or
``fastapi``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..types import PlanGraph, StateSchema, WorkflowRunResult

# Re-export the domain types used by the runtime contract so callers can depend
# on this single port module.
__all__ = [
    "WorkflowRuntime",
    "PlanGraph",
    "StateSchema",
    "WorkflowRunResult",
]


@runtime_checkable
class Callback(Protocol):
    """A state event callback (e.g. ``{"type": "state.update", ...}``)."""

    def __call__(self, event: dict[str, Any]) -> None:
        ...


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