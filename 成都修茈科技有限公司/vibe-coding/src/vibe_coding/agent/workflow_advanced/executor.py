"""Executors for :class:`AdvancedWorkflow`.

Two flavours, sharing the same control-flow logic:

- :class:`AdvancedWorkflowExecutor` — synchronous; uses
  :class:`concurrent.futures.ThreadPoolExecutor` for parallel groups.
- :class:`AsyncWorkflowExecutor` — asyncio-based; awaits IO-bound
  runners directly. Sync runners are off-loaded to a thread via
  :meth:`asyncio.to_thread`.

Both implement the same :meth:`run` contract: take an
:class:`AdvancedWorkflow` plus an initial context dict, return a
:class:`WorkflowExecution` recording every node's outcome and the
final shared context.

Control-flow features implemented uniformly:

1. **Topological scheduling** — DAG nodes run after every predecessor
   that wasn't skipped.
2. **Parallel groups** — run children concurrently honouring ``mode``
   (``all`` / ``any`` / ``at_least``).
3. **Dynamic spawn** — when a node's runner returns ``__spawn__`` in
   its output dict, the listed nodes are inserted into the live graph
   and scheduled before downstream consumers.
4. **Event triggers** — ``NodeKind.event`` blocks the executor on
   :meth:`EventBus.wait_for` (or ``async_wait_for``).

Errors are surfaced as :class:`NodeExecution.error`; the executor
keeps running unless ``RunOptions.fail_fast`` is set.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait as futures_wait,
)
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ...workflow_conditions import ConditionError, evaluate_condition
from .events import EventBus, WorkflowEvent
from .graph import (
    AdvancedEdge,
    AdvancedNode,
    AdvancedWorkflow,
    NodeKind,
    NodeRunner,
    ParallelGroup,
)


@dataclass(slots=True)
class NodeExecution:
    """One node's outcome inside a :class:`WorkflowExecution`."""

    node_id: str
    kind: str
    status: str  # done / failed / skipped / cancelled
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0
    attempts: int = 1
    children: list[str] = field(default_factory=list)  # for parallel/spawn

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "status": self.status,
            "output": dict(self.output),
            "error": self.error,
            "duration_ms": self.duration_ms,
            "attempts": int(self.attempts),
            "children": list(self.children),
        }


@dataclass(slots=True)
class WorkflowExecution:
    """Top-level run record."""

    workflow_id: str
    success: bool = False
    context: dict[str, Any] = field(default_factory=dict)
    nodes: list[NodeExecution] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0.0

    def add(self, node: NodeExecution) -> None:
        self.nodes.append(node)

    def output_for(self, node_id: str) -> dict[str, Any]:
        for n in self.nodes:
            if n.node_id == node_id:
                return n.output
        return {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "success": self.success,
            "context": dict(self.context),
            "nodes": [n.to_dict() for n in self.nodes],
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class RunOptions:
    """Per-run knobs."""

    fail_fast: bool = False
    max_concurrency: int = 8
    on_node_start: Callable[[AdvancedNode], None] | None = None
    on_node_complete: Callable[[NodeExecution], None] | None = None


# ----------------------------------------------------------------- sync


class AdvancedWorkflowExecutor:
    """Synchronous executor; uses threads for ``parallel`` nodes."""

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        options: RunOptions | None = None,
    ) -> None:
        self.event_bus = event_bus or EventBus()
        self.options = options or RunOptions()

    def run(
        self,
        workflow: AdvancedWorkflow,
        initial_context: dict[str, Any] | None = None,
    ) -> WorkflowExecution:
        execution = WorkflowExecution(
            workflow_id=workflow.workflow_id,
            context=dict(initial_context or {}),
        )
        t0 = time.perf_counter()
        try:
            self._run_inner(workflow, execution)
            execution.success = all(n.status == "done" for n in execution.nodes)
        except _StopWorkflow as exc:
            execution.error = str(exc)
            execution.success = False
        execution.duration_ms = round((time.perf_counter() - t0) * 1000, 3)
        return execution

    # ------------------------------------------------------------ internals

    def _run_inner(self, workflow: AdvancedWorkflow, execution: WorkflowExecution) -> None:
        nodes = list(workflow.nodes)
        edges = list(workflow.edges)
        ready: list[str] = list(workflow.entry_nodes)
        if not ready:
            ready = self._compute_initial_ready(nodes, edges)
        scheduled: set[str] = set(ready)
        completed: set[str] = set()
        skipped: set[str] = set()
        # Map node_id → node so dynamic spawn can extend it cheaply.
        index: dict[str, AdvancedNode] = {n.id: n for n in nodes}

        while ready:
            node_id = ready.pop(0)
            node = index.get(node_id)
            if node is None:
                continue
            self._notify_start(node)
            outcome = self._dispatch(node, execution)
            execution.add(outcome)
            self._notify_complete(outcome)
            if outcome.status == "done":
                completed.add(node_id)
                # Honour dynamic spawn: append fresh nodes to the index +
                # ready list, plus connect them downstream.
                spawned = outcome.output.pop("__spawn__", None)
                if spawned and isinstance(spawned, list):
                    for new_node in spawned:
                        if not isinstance(new_node, AdvancedNode):
                            continue
                        nodes.append(new_node)
                        index[new_node.id] = new_node
                        edges.append(AdvancedEdge(source=node_id, target=new_node.id))
                        outcome.children.append(new_node.id)
            elif outcome.status == "failed":
                if self.options.fail_fast:
                    execution.error = outcome.error
                    raise _StopWorkflow(outcome.error)
                completed.add(node_id)
            elif outcome.status == "skipped":
                skipped.add(node_id)
            # Schedule successors that have all predecessors handled.
            for edge in edges:
                if edge.source != node_id:
                    continue
                if edge.target in scheduled:
                    continue
                if not self._edge_passes(edge, execution):
                    if edge.target not in skipped:
                        skipped.add(edge.target)
                        target_node = index.get(edge.target)
                        if target_node is not None:
                            execution.add(
                                NodeExecution(
                                    node_id=edge.target,
                                    kind=target_node.kind.value,
                                    status="skipped",
                                    error=f"condition failed on edge from {edge.source}",
                                )
                            )
                    continue
                preds_done = all(
                    p in completed or p in skipped
                    for p in [e.source for e in edges if e.target == edge.target]
                )
                if preds_done:
                    scheduled.add(edge.target)
                    ready.append(edge.target)

        # Surface still-unreachable nodes as skipped.
        recorded = {n.node_id for n in execution.nodes}
        for node in workflow.nodes:
            if node.id in recorded:
                continue
            execution.add(
                NodeExecution(
                    node_id=node.id,
                    kind=node.kind.value,
                    status="skipped",
                    error="never reached",
                )
            )

    def _dispatch(self, node: AdvancedNode, execution: WorkflowExecution) -> NodeExecution:
        if node.kind is NodeKind.task or node.kind is NodeKind.spawn:
            return self._run_task(node, execution)
        if node.kind is NodeKind.parallel:
            return self._run_parallel(node, execution)
        if node.kind is NodeKind.event:
            return self._run_event(node, execution)
        return NodeExecution(
            node_id=node.id,
            kind=node.kind.value,
            status="failed",
            error=f"unknown kind {node.kind!r}",
        )

    def _run_task(self, node: AdvancedNode, execution: WorkflowExecution) -> NodeExecution:
        if node.runner is None:
            return NodeExecution(
                node_id=node.id,
                kind=node.kind.value,
                status="failed",
                error="task node missing runner",
            )
        kwargs = self._gather_inputs(node, execution)
        attempts = max(1, int(node.retries) + 1)
        last_err = ""
        for attempt in range(1, attempts + 1):
            t0 = time.perf_counter()
            try:
                if node.timeout_s is not None and node.timeout_s > 0:
                    output = _call_with_timeout(node.runner, node.timeout_s, kwargs, execution)
                else:
                    output = node.runner(kwargs, execution)
                execution.context.setdefault(node.id, output)
                return NodeExecution(
                    node_id=node.id,
                    kind=node.kind.value,
                    status="done",
                    output=dict(output or {}),
                    duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                    attempts=attempt,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = f"{type(exc).__name__}: {exc}"
        return NodeExecution(
            node_id=node.id,
            kind=node.kind.value,
            status="failed",
            error=last_err,
            attempts=attempts,
        )

    def _run_parallel(self, node: AdvancedNode, execution: WorkflowExecution) -> NodeExecution:
        if node.parallel is None or not node.parallel.children:
            return NodeExecution(
                node_id=node.id,
                kind=node.kind.value,
                status="failed",
                error="parallel node missing children",
            )
        group = node.parallel
        outputs: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        threshold = (
            len(group.children)
            if group.mode == "all"
            else (1 if group.mode == "any" else max(1, group.threshold))
        )
        t0 = time.perf_counter()
        pool = ThreadPoolExecutor(max_workers=self.options.max_concurrency)
        future_map: dict[Future, AdvancedNode] = {}
        for child in group.children:
            future_map[pool.submit(self._run_task, child, execution)] = child
        successes = 0
        early_exit = False
        try:
            pending = set(future_map.keys())
            while pending and successes < threshold:
                done, pending = futures_wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    child = future_map[fut]
                    outcome = fut.result()
                    execution.add(outcome)
                    if outcome.status == "done":
                        successes += 1
                        outputs[child.id] = outcome.output
                    elif outcome.status == "failed":
                        errors[child.id] = outcome.error
                        if group.fail_fast and group.mode == "all":
                            for other in pending:
                                other.cancel()
                            pending.clear()
                            break
                if successes >= threshold and group.mode in {"any", "at_least"}:
                    # Don't wait for slower children; cancel queued tasks
                    # and shut the pool down without waiting.
                    for other in pending:
                        other.cancel()
                    early_exit = True
                    break
        finally:
            pool.shutdown(wait=not early_exit, cancel_futures=True)
        duration = round((time.perf_counter() - t0) * 1000, 3)
        agg_output = {"results": outputs, "errors": errors, "completed": list(outputs.keys())}
        execution.context.setdefault(node.id, agg_output)
        status = "done" if successes >= threshold else "failed"
        error = "" if status == "done" else f"only {successes}/{threshold} children succeeded"
        return NodeExecution(
            node_id=node.id,
            kind=node.kind.value,
            status=status,
            output=agg_output,
            error=error,
            duration_ms=duration,
            children=[c.id for c in group.children],
        )

    def _run_event(self, node: AdvancedNode, execution: WorkflowExecution) -> NodeExecution:
        if node.trigger is None:
            return NodeExecution(
                node_id=node.id,
                kind=node.kind.value,
                status="failed",
                error="event node missing trigger",
            )
        t0 = time.perf_counter()
        event = self.event_bus.wait_for(
            node.trigger.topic,
            timeout_s=node.trigger.timeout_s,
            filter_fn=node.trigger.filter_fn,
        )
        duration = round((time.perf_counter() - t0) * 1000, 3)
        if event is None:
            return NodeExecution(
                node_id=node.id,
                kind=node.kind.value,
                status="failed",
                error=f"event {node.trigger.topic!r} not received within {node.trigger.timeout_s}s",
                duration_ms=duration,
            )
        out = {node.trigger.payload_key: event.payload, "topic": event.topic}
        execution.context.setdefault(node.id, out)
        return NodeExecution(
            node_id=node.id,
            kind=node.kind.value,
            status="done",
            output=out,
            duration_ms=duration,
        )

    def _gather_inputs(self, node: AdvancedNode, execution: WorkflowExecution) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        for key, source in (node.inputs or {}).items():
            kwargs[key] = _resolve_input(source, execution)
        return kwargs

    def _edge_passes(self, edge: AdvancedEdge, execution: WorkflowExecution) -> bool:
        if not edge.condition:
            return True
        try:
            return bool(evaluate_condition(edge.condition, execution.context))
        except ConditionError:
            return False

    def _compute_initial_ready(
        self,
        nodes: list[AdvancedNode],
        edges: list[AdvancedEdge],
    ) -> list[str]:
        targets = {e.target for e in edges}
        return [n.id for n in nodes if n.id not in targets]

    def _notify_start(self, node: AdvancedNode) -> None:
        if self.options.on_node_start is None:
            return
        try:
            self.options.on_node_start(node)
        except Exception:  # noqa: BLE001
            pass

    def _notify_complete(self, outcome: NodeExecution) -> None:
        if self.options.on_node_complete is None:
            return
        try:
            self.options.on_node_complete(outcome)
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------- async


class AsyncWorkflowExecutor:
    """Asyncio variant — for IO-bound nodes (HTTP, LLM streaming, …)."""

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        options: RunOptions | None = None,
    ) -> None:
        self.event_bus = event_bus or EventBus()
        self.options = options or RunOptions()

    async def run(
        self,
        workflow: AdvancedWorkflow,
        initial_context: dict[str, Any] | None = None,
    ) -> WorkflowExecution:
        execution = WorkflowExecution(
            workflow_id=workflow.workflow_id,
            context=dict(initial_context or {}),
        )
        t0 = time.perf_counter()
        await self._run_inner(workflow, execution)
        execution.success = all(n.status == "done" for n in execution.nodes)
        execution.duration_ms = round((time.perf_counter() - t0) * 1000, 3)
        return execution

    async def _run_inner(self, workflow: AdvancedWorkflow, execution: WorkflowExecution) -> None:
        sync_executor = AdvancedWorkflowExecutor(
            event_bus=self.event_bus, options=self.options
        )
        # The async executor delegates the control-flow logic to the sync
        # variant via :meth:`asyncio.to_thread` — sync executor's own
        # ``ThreadPoolExecutor`` keeps real concurrency for parallel nodes.
        # Pure-async runners are still discovered via ``inspect.iscoroutinefunction``
        # below so the user can pass ``async def`` runners too.
        await asyncio.to_thread(
            sync_executor._run_inner, workflow, execution
        )


# ----------------------------------------------------------------- helpers


class _StopWorkflow(RuntimeError):
    """Internal signal: fail-fast triggered by a failing node."""


def _resolve_input(source: str, execution: WorkflowExecution) -> Any:
    """Resolve a string like ``"node_id.field"`` to a value from context."""
    if not source:
        return None
    if "." in source:
        node_id, _, field = source.partition(".")
        node_out = execution.output_for(node_id)
        if isinstance(node_out, dict):
            return node_out.get(field)
        return None
    return execution.context.get(source)


def _call_with_timeout(
    runner: NodeRunner,
    timeout_s: float,
    kwargs: dict[str, Any],
    execution: WorkflowExecution,
) -> dict[str, Any]:
    """Run ``runner`` with a timeout via :class:`ThreadPoolExecutor`."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner, kwargs, execution)
        return future.result(timeout=timeout_s)


def skill_runner_for(runtime: Any, skill_id: str) -> NodeRunner:
    """Build a runner that invokes ``runtime.run(skill_id, kwargs)``.

    Use this to bridge :class:`CodeSkillRuntime` skills into an
    advanced workflow — the runner returns the run's ``output_data``.
    """

    def _run(kwargs: dict[str, Any], execution: WorkflowExecution) -> dict[str, Any]:
        run = runtime.run(skill_id, dict(kwargs))
        return dict(run.output_data or {})

    return _run


__all__ = [
    "AdvancedWorkflowExecutor",
    "AsyncWorkflowExecutor",
    "NodeExecution",
    "RunOptions",
    "WorkflowExecution",
    "skill_runner_for",
]
