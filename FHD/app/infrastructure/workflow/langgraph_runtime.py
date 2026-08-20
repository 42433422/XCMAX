"""XCAGI LangGraph workflow runtime — LG-W1-T3.

``XCAGILangGraphRuntime`` is the self-contained LangGraph graph executor. It
implements the application ``WorkflowRuntime`` port purely on top of the vendored
``StateGraph`` (``langgraph.graph.state``): a ``PlanGraph`` is compiled into a
``StateGraph`` whose nodes execute business tools through the ``ToolDispatcher``,
accumulate ``node_outputs`` / ``workflow_trace`` / ``workflow_status`` via proper
channels/reducers (never bare ``LastValue`` for accumulators), emit
``state.update`` events, honour ``depends_on`` + ``branches`` / ``next``, retry
with failure short-circuit, and produce ``WorkflowRunResult`` /
``NodeExecutionResult`` from the final graph state.

It never imports the legacy ``WorkflowEngine``. Checkpoint-based ``resume_run``
rebuilds the graph from a ``CheckpointStore`` snapshot and skips executed nodes;
``replay_run`` reconstructs results without re-executing. ``agentic_loop`` /
``tool_registry`` are not implemented and fail closed with ``NotImplementedError``.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Iterator

from langgraph.graph.state import END, START, StateGraph

from app.application.workflow.ports.events import StateEventPublisher
from app.application.workflow.ports.runtime import WorkflowRuntime
from app.application.workflow.types import (
    StateSchema,
    WorkflowNode,
)
from app.infrastructure.workflow.langgraph_assert import assert_vendored_sources

logger = logging.getLogger(__name__)

# Fail-closed boot gate: every langgraph module must resolve to the vendored
# packages with the package-specific pinned PROVENANCE, or this
# runtime refuses to start instead of silently running on a PyPI distribution.
assert_vendored_sources()

__all__ = ["END", "START", "StateGraph", "XCAGILangGraphRuntime"]


def _merge_dict(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(a or {})
    out.update(dict(b or {}))
    return out


# Internal bookkeeping channels the runtime owns; schema-declared keys that
# collide with these are never emitted as schema writes to avoid clobbering.
_INTERNAL_CHANNELS = frozenset(
    {
        "node_outputs",
        "workflow_trace",
        "workflow_status",
        "executed",
        "blocked",
        "results",
        "failure",
        "message",
    }
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _summarize_output(output: dict[str, Any]) -> str:
    text = output.get("message") or output.get("error") or output.get("output") or ""
    return str(text)[:200]


class _ReadersWriterGate:
    """Readers–writer execution gate controlling node concurrency.

    Readers — nodes that are **low-risk AND idempotent** — may run concurrently
    with one another. Writers — any high-risk or non-idempotent node — hold
    exclusive access and never overlap any other node. When ``parallel=False``
    every node is treated as a writer so the whole graph is serialized.
    """

    def __init__(self, parallel: bool) -> None:
        self._parallel = parallel
        self._cond = threading.Condition()
        self._readers = 0
        self._writer = False
        self._writers_waiting = 0

    @staticmethod
    def is_reader(node: WorkflowNode) -> bool:
        return bool(node.idempotent) and node.risk == "low"

    def _is_exclusive(self, node: WorkflowNode) -> bool:
        if not self._parallel:
            return True
        return not self.is_reader(node)

    @contextlib.contextmanager
    def execution(self, node: WorkflowNode) -> Iterator[None]:
        exclusive = self._is_exclusive(node)
        if exclusive:
            self._acquire_writer()
        else:
            self._acquire_reader()
        try:
            yield
        finally:
            if exclusive:
                self._release_writer()
            else:
                self._release_reader()

    def _acquire_reader(self) -> None:
        with self._cond:
            while self._writer or self._writers_waiting:
                self._cond.wait()
            self._readers += 1

    def _release_reader(self) -> None:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def _acquire_writer(self) -> None:
        with self._cond:
            self._writers_waiting += 1
            try:
                while self._writer or self._readers:
                    self._cond.wait()
                self._writer = True
            finally:
                self._writers_waiting -= 1

    def _release_writer(self) -> None:
        with self._cond:
            self._writer = False
            self._cond.notify_all()


_construction_module = importlib.import_module("app.infrastructure.workflow.langgraph_construction")
_execution_module = importlib.import_module("app.infrastructure.workflow.langgraph_execution")
if TYPE_CHECKING:
    from app.infrastructure.workflow.langgraph_construction import LangGraphConstructionMixin
    from app.infrastructure.workflow.langgraph_execution import LangGraphExecutionMixin
else:
    LangGraphConstructionMixin = _construction_module.LangGraphConstructionMixin
    LangGraphExecutionMixin = _execution_module.LangGraphExecutionMixin


class XCAGILangGraphRuntime(LangGraphConstructionMixin, LangGraphExecutionMixin, WorkflowRuntime):
    """LangGraph-backed ``WorkflowRuntime`` executing plans via a vendored StateGraph."""

    def __init__(
        self,
        tool_dispatcher: Any | None = None,
        state_event_publisher: StateEventPublisher | None = None,
        state_schema: StateSchema | None = None,
    ) -> None:
        self._dispatch: Any = tool_dispatcher or _default_dispatcher
        self._publisher: StateEventPublisher | None = state_event_publisher
        self._state_schema: StateSchema | None = state_schema
        self._callback: Any = None

    # -- StateGraph construction -----------------------------------------------


def _default_dispatcher(tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": False,
        "message": f"未接线 dispatcher: {tool_id}.{action}",
    }
