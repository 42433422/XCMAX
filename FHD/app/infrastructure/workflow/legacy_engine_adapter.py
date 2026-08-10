"""LegacyEngineAdapter — expose the legacy ``WorkflowEngine`` as ``WorkflowRuntime``.

LG-W1-T6. This infrastructure adapter hands the application-layer
``WorkflowRuntime`` port the existing hand-written ``WorkflowEngine`` unchanged
(the ``legacy`` runtime path in the gray-release gate). The adapter is a thin,
1:1 pass-through: method signatures mirror the port exactly, and the engine owns
all execution, state merge, checkpointing, resume and replay semantics.

Dependency direction (DDD): ``infrastructure → ports + domain``. This module
imports the application ``WorkflowEngine`` and the ``WorkflowRuntime`` port, but
never ``langgraph``, ``sqlalchemy``, ``app.neuro_bus`` or ``fastapi``. The
LangGraph runtime, when enabled, is a sibling implementation of the same port
(``langgraph_runtime.py``), selected by ``runtime_selector``.
"""

from __future__ import annotations

from typing import Any

from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.ports.runtime import (
    Callback,
    PlanGraph,
    StateSchema,
    WorkflowRunResult,
)
from app.application.workflow.ports.tools import ToolDispatcher


class LegacyEngineAdapter:
    """Adapter making the legacy ``WorkflowEngine`` satisfy ``WorkflowRuntime``.

    Constructed **keyword-only** with the business ``tool_dispatcher`` (and an
    optional state event callback) exactly like ``WorkflowEngine``; every
    ``WorkflowRuntime`` method delegates to the wrapped engine unchanged. The
    adapter is fail-closed: it refuses to build without a dispatcher, so a
    misconfigured composition root fails loudly at construction instead of
    at first node execution.

    Read-only accessors expose the wrapped engine and the dispatcher so callers
    / tests can assert engine identity and dispatcher pass-through.
    """

    def __init__(
        self,
        *,
        tool_dispatcher: ToolDispatcher,
        state_event_callback: Callback | None = None,
    ) -> None:
        # fail-closed: a null dispatcher would only explode mid-run; reject early.
        if tool_dispatcher is None:
            raise ValueError("LegacyEngineAdapter requires a non-null tool_dispatcher")
        self._dispatcher = tool_dispatcher
        self._engine = WorkflowEngine(
            tool_dispatcher=tool_dispatcher,
            state_event_callback=state_event_callback,
        )

    @property
    def engine(self) -> WorkflowEngine:
        """The wrapped legacy ``WorkflowEngine`` instance (identity check)."""
        return self._engine

    @property
    def dispatcher(self) -> ToolDispatcher:
        """The dispatcher passed through to the engine (pass-through check)."""
        return self._dispatcher

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
        """Execute ``plan`` via the legacy engine and return the run result."""
        return self._engine.run(
            plan=plan,
            runtime_context=runtime_context,
            max_retries=max_retries,
            agentic_loop=agentic_loop,
            tool_registry=tool_registry,
            user_id=user_id,
            state_schema=state_schema,
            parallel=parallel,
            checkpointer=checkpointer,
            state_event_callback=state_event_callback,
        )

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
        """Resume from ``checkpoint_id`` without re-running completed nodes."""
        return self._engine.resume_run(
            plan,
            checkpoint_id,
            checkpointer=checkpointer,
            max_retries=max_retries,
            state_schema=state_schema,
            parallel=parallel,
        )

    def replay_run(
        self,
        plan_id: str,
        checkpoint_id: str | None = None,
        *,
        checkpointer: Any,
    ) -> WorkflowRunResult:
        """Read-only replay of executed node outputs from a checkpoint."""
        return self._engine.replay_run(
            plan_id,
            checkpoint_id,
            checkpointer=checkpointer,
        )