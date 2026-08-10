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

    Constructed **keyword-only** with either an already-built ``engine`` or a
    ``tool_dispatcher`` (plus optional ``state_event_callback``) used to build
    one. Every ``WorkflowRuntime`` method delegates to the wrapped engine
    unchanged. The adapter is fail-closed: it refuses to build without either an
    engine or a dispatcher, so a misconfigured composition root fails loudly at
    construction instead of at first node execution.

    Read-only accessors expose the wrapped engine (identity) and the dispatcher
    it is wired to (always derived from the engine).
    """

    def __init__(
        self,
        *,
        engine: WorkflowEngine | None = None,
        tool_dispatcher: ToolDispatcher | None = None,
        state_event_callback: Callback | None = None,
    ) -> None:
        # fail-closed: require an injected engine OR a dispatcher to build one.
        if engine is None and tool_dispatcher is None:
            raise ValueError("LegacyEngineAdapter requires either `engine` or `tool_dispatcher`")
        # Conflict guards: an injected engine already owns its dispatcher and
        # callback, so supplying them alongside the engine is ambiguous and must
        # fail loudly instead of silently ignoring the extra wiring.
        if engine is not None and tool_dispatcher is not None:
            raise ValueError(
                "LegacyEngineAdapter accepts either `engine` or `tool_dispatcher`, not both"
            )
        if engine is not None and state_event_callback is not None:
            raise ValueError(
                "LegacyEngineAdapter `state_event_callback` only applies when "
                "building from `tool_dispatcher` (engine already owns its callback)"
            )
        if engine is not None:
            self._engine = engine
        else:
            self._engine = WorkflowEngine(
                tool_dispatcher=tool_dispatcher,
                state_event_callback=state_event_callback,
            )
        # Dispatcher is always derived from the engine's own dispatcher, keeping
        # engine identity and dispatcher pass-through consistent whether the
        # engine was injected or built from a dispatcher.
        self._dispatcher = getattr(self._engine, "_dispatch", None)

    @property
    def engine(self) -> WorkflowEngine:
        """The wrapped legacy ``WorkflowEngine`` (identity of the injected engine)."""
        return self._engine

    @property
    def dispatcher(self) -> ToolDispatcher | None:
        """The dispatcher the engine is wired to (derived from the engine)."""
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
