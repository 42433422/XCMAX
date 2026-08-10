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
import logging
import operator
import threading
import time
from datetime import UTC, datetime
from typing import Annotated, Any, Iterator, TypedDict

from langgraph.graph.state import END, START, StateGraph

from app.application.workflow.ports.checkpoint import CheckpointStore
from app.application.workflow.ports.events import StateEventPublisher, StateUpdateEvent
from app.application.workflow.ports.runtime import WorkflowRuntime
from app.application.workflow.types import (
    NodeExecutionResult,
    PlanGraph,
    StateField,
    StateSchema,
    WorkflowNode,
    WorkflowRunResult,
    apply_state_schema,
)
from app.infrastructure.workflow.langgraph_assert import assert_vendored_sources
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# Fail-closed boot gate: every langgraph module must resolve to the vendored
# packages with the pinned PROVENANCE (tag 1.2.10 / commit 41341457…), or this
# runtime refuses to start instead of silently running on a PyPI distribution.
assert_vendored_sources()


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


class XCAGILangGraphRuntime(WorkflowRuntime):
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

    def build_graph(
        self,
        plan: PlanGraph,
        *,
        runtime_context: dict[str, Any] | None = None,
        state_schema: StateSchema | None = None,
        max_retries: int = 1,
        parallel: bool = True,
    ) -> StateGraph:
        """Compile-stage: build the vendored ``StateGraph`` for ``plan`` (uncompiled)."""
        gate = _ReadersWriterGate(parallel)
        effective = state_schema or self._state_schema
        graph = StateGraph(self._schema(runtime_context, effective))
        for node in plan.nodes:
            graph.add_node(
                node.node_id,
                self._make_node_fn(
                    node, max_retries, [n.node_id for n in plan.nodes], gate, effective
                ),
            )
        self._add_edges(graph, plan)
        return graph

    def compile_graph(
        self,
        plan: PlanGraph,
        *,
        runtime_context: dict[str, Any] | None = None,
        state_schema: StateSchema | None = None,
        max_retries: int = 1,
        parallel: bool = True,
    ) -> Any:
        """Compile the vendored graph (raises if the plan structure is invalid)."""
        return self.build_graph(
            plan,
            runtime_context=runtime_context,
            state_schema=state_schema,
            max_retries=max_retries,
            parallel=parallel,
        ).compile()

    def invoke_graph(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        state_schema: StateSchema | None = None,
        max_retries: int = 1,
        parallel: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Compile and invoke the graph, returning the final graph state."""
        graph = self.compile_graph(
            plan,
            runtime_context=runtime_context,
            state_schema=state_schema,
            max_retries=max_retries,
            parallel=parallel,
        )
        return graph.invoke(
            self._initial_state(runtime_context),
            config={"recursion_limit": self._recursion_limit(plan)},
            **kwargs,
        )

    # -- WorkflowRuntime execution path ----------------------------------------

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
        checkpointer: CheckpointStore | None = None,
        state_event_callback: Any | None = None,
    ) -> WorkflowRunResult:
        if agentic_loop or tool_registry is not None:
            raise NotImplementedError(
                "XCAGILangGraphRuntime 不支持 agentic_loop / tool_registry（fail-closed）"
            )
        self._callback = state_event_callback
        try:
            initial = self._initial_state(runtime_context)
            graph = self.compile_graph(
                plan,
                runtime_context=initial,
                state_schema=state_schema,
                max_retries=max_retries,
                parallel=parallel,
            )
            final = self._stream_run(graph, plan, dict(initial), checkpointer, parallel=parallel)
            result = self._to_run_result(plan, final)
            # On a successful run persist one extra final "completed" checkpoint so the
            # most advanced snapshot always carries the completed workflow_status.
            if checkpointer is not None and result.success:
                self._save_checkpoint(checkpointer, plan, final)
            return result
        finally:
            self._callback = None

    def resume_run(
        self,
        plan: PlanGraph,
        checkpoint_id: str,
        *,
        checkpointer: CheckpointStore,
        max_retries: int = 1,
        state_schema: StateSchema | None = None,
        parallel: bool = True,
    ) -> WorkflowRunResult:
        cp = checkpointer.get_checkpoint(plan.plan_id, checkpoint_id)
        if cp is None:
            return WorkflowRunResult(
                plan_id=plan.plan_id,
                success=False,
                message=f"checkpoint 不存在: {checkpoint_id}",
            )
        initial = self._checkpoint_state(cp)
        graph = self.compile_graph(
            plan,
            runtime_context=initial,
            state_schema=state_schema,
            max_retries=max_retries,
            parallel=parallel,
        )
        final = self._stream_run(graph, plan, dict(initial), checkpointer, parallel=parallel)
        result = self._to_run_result(plan, final)
        if result.success:
            self._save_checkpoint(checkpointer, plan, final)
        return result

    def replay_run(
        self,
        plan_id: str,
        checkpoint_id: str | None = None,
        *,
        checkpointer: CheckpointStore,
    ) -> WorkflowRunResult:
        if checkpoint_id is None:
            cp = checkpointer.latest_checkpoint(plan_id)
        else:
            cp = checkpointer.get_checkpoint(plan_id, checkpoint_id)
        if cp is None:
            return WorkflowRunResult(
                plan_id=plan_id,
                success=False,
                message="checkpoint 不存在，无法重放",
            )
        rc = dict(cp.get("runtime_context") or {})
        results = rc.get("results") or []
        if results:
            node_results = [NodeExecutionResult(**dict(r)) for r in results]
        else:
            node_results = self._replay_from_trace(
                rc.get("workflow_trace") or [], rc.get("node_outputs") or {}
            )
        ws = rc.get("workflow_status") or {}
        success = bool(node_results) and ws.get("state") == "completed"
        return WorkflowRunResult(
            plan_id=plan_id,
            success=success,
            node_results=node_results,
            final_context=rc,
            message="重放自 checkpoint（未重新执行）",
        )

    # -- graph construction helpers ---------------------------------------------

    @staticmethod
    def _recursion_limit(plan: PlanGraph) -> int:
        return max(100, len(plan.nodes) * 20)

    def _schema(
        self, runtime_context: dict[str, Any] | None, state_schema: StateSchema | None
    ) -> type[TypedDict]:
        fields: dict[str, Any] = {
            "node_outputs": Annotated[dict, _merge_dict],
            "workflow_trace": Annotated[list, operator.add],
            "workflow_status": Annotated[dict, _merge_dict],
            "executed": Annotated[list, operator.add],
            "blocked": Annotated[list, operator.add],
            "results": Annotated[list, operator.add],
            "failure": Annotated[dict, _merge_dict],
            "message": str,
        }
        # Schema-declared keys get graph channels that mirror their merge semantics
        # (append → list reducer, merge_dict → dict reducer, set → LastValue).
        effective = state_schema or self._state_schema
        if effective is not None:
            for sf in effective.fields.values():
                fields.setdefault(sf.key, self._channel_for(sf))
        # Plain runtime_context keys are opaque LastValue channels.
        for extra in (runtime_context,):
            if extra:
                for key in extra:
                    fields.setdefault(key, Any)
        return TypedDict("XCAGIWorkflowState", fields)

    @staticmethod
    def _channel_for(sf: StateField) -> Any:
        """Return the graph-channel annotation matching a field's merge semantics."""
        if sf.merge == "append":
            return Annotated[list, operator.add]
        if sf.merge == "merge_dict":
            return Annotated[dict, _merge_dict]
        return Any

    @staticmethod
    def _contribute(sf: StateField, value: Any) -> Any:
        """Shape a node output value into the update a merge-semantics channel expects."""
        if sf.merge == "append":
            return [value]
        return value

    def _initial_state(self, runtime_context: dict[str, Any] | None) -> dict[str, Any]:
        state = dict(runtime_context or {})
        state.setdefault("node_outputs", {})
        state.setdefault("workflow_trace", [])
        state.setdefault("workflow_status", {})
        state.setdefault("executed", [])
        state.setdefault("blocked", [])
        state.setdefault("results", [])
        return state

    @staticmethod
    def _checkpoint_state(cp: dict[str, Any]) -> dict[str, Any]:
        rc = dict(cp.get("runtime_context") or {})
        rc.setdefault("executed", list(cp.get("executed_nodes") or []))
        rc.setdefault("blocked", list(cp.get("blocked") or []))
        rc.setdefault("node_outputs", {})
        rc.setdefault("workflow_trace", [])
        rc.setdefault("workflow_status", {})
        rc.setdefault("results", [])
        return rc

    def _add_edges(self, graph: StateGraph, plan: PlanGraph) -> None:
        nodes = list(plan.nodes)
        node_ids = {n.node_id for n in nodes}
        cand_by: dict[str, set[str]] = {}
        all_candidates: set[str] = set()
        for n in nodes:
            cands = self._candidates(n)
            cand_by[n.node_id] = set(cands)
            all_candidates.update(cands)
        succ: dict[str, list[str]] = {n.node_id: [] for n in nodes}
        for n in nodes:
            for dep in n.depends_on:
                if dep in node_ids and dep != n.node_id:
                    if n.node_id in cand_by.get(dep, set()):
                        continue  # reached via the router's conditional edge
                    succ[dep].append(n.node_id)
        roots = [n.node_id for n in nodes if not n.depends_on and n.node_id not in all_candidates]
        for r in roots:
            graph.add_edge(START, r)
        for n in nodes:
            targets = list(dict.fromkeys(succ[n.node_id]))
            path_map: dict[str, Any] = {t: t for t in targets}
            for c in cand_by.get(n.node_id, set()):
                path_map[c] = c
            path_map["__end__"] = END
            graph.add_conditional_edges(n.node_id, self._make_route_fn(n, targets), path_map)

    @staticmethod
    def _candidates(node: WorkflowNode) -> list[str]:
        out: list[str] = []
        if node.branches:
            out.extend(b.target for b in node.branches if b.target)
        if node.next and node.next not in out:
            out.append(node.next)
        return out

    def _make_route_fn(self, node: WorkflowNode, successors: list[str]) -> Any:
        nid = node.node_id
        candidates = set(self._candidates(node))

        def route(state: dict[str, Any]) -> Any:
            if state.get("failure"):
                return "__end__"
            if candidates:
                out = (state.get("node_outputs") or {}).get(nid, {})
                chosen = self._resolve_successor(node, out)
                return chosen if chosen in candidates else "__end__"
            return successors if successors else "__end__"

        return route

    def _make_node_fn(
        self,
        node: WorkflowNode,
        max_retries: int,
        plan_node_ids: list[str],
        gate: _ReadersWriterGate,
        effective_schema: StateSchema | None = None,
    ) -> Any:
        nid = node.node_id
        candidates = set(self._candidates(node))
        schema_fields = effective_schema.fields if effective_schema is not None else {}

        def fn(state: dict[str, Any]) -> dict[str, Any]:
            if nid in (state.get("blocked") or []) or nid in (state.get("executed") or []):
                return {}
            with gate.execution(node):
                result = self._execute_node(node, state, max_retries)
            update: dict[str, Any] = {
                "executed": [nid],
                "results": [self._result_dict(result)],
                "node_outputs": {nid: result.output},
                "workflow_trace": [self._trace_entry(result)],
            }
            if result.success:
                update["workflow_status"] = {"state": "running", "last_node": nid}
                # StateSchema writes: only schema-declared keys of a successful
                # node output become graph-state writes. Each original value is
                # validated fail-closed via apply_state_schema (raises ValueError
                # on type/merge mismatch — never silently dropped).
                for key, sf in schema_fields.items():
                    if key in _INTERNAL_CHANNELS or key not in result.output:
                        continue
                    value = result.output[key]
                    apply_state_schema({}, effective_schema, writes={key: value})
                    update[key] = self._contribute(sf, value)
            else:
                # Legacy abort semantics: a failure stops all further scheduling.
                done = set(state.get("executed") or [])
                done.add(nid)
                update["blocked"] = [p for p in plan_node_ids if p not in done]
                update["failure"] = {
                    "node_id": nid,
                    "error": result.error,
                    "recovery_hint": result.recovery_hint,
                }
                update["workflow_status"] = {
                    "state": "failed",
                    "failed_node_id": nid,
                    "message": result.error,
                    "recovery_hint": result.recovery_hint,
                }
            if candidates:
                chosen = self._resolve_successor(node, result.output)
                to_block = [c for c in candidates if c != chosen]
                if to_block:
                    update.setdefault("blocked", [])
                    update["blocked"].extend(c for c in to_block if c not in update["blocked"])
            self._emit_state_update(result)
            return update

        return fn

    # -- node execution ----------------------------------------------------------

    def _execute_node(
        self, node: WorkflowNode, state: dict[str, Any], max_retries: int
    ) -> NodeExecutionResult:
        if node.tool_id == "clarify":
            return self._run_clarify(node, state)
        retryable = bool(node.idempotent) or node.risk == "low"
        attempts_quota = max_retries if retryable else 0
        attempts: list[dict[str, Any]] = []
        last_error = ""
        last_output: dict[str, Any] = {}
        retries = 0
        started = _now_iso()
        begin = time.perf_counter()
        while retries <= attempts_quota:
            params = dict(node.params or {})
            params["_runtime_context"] = state
            try:
                raw = self._dispatch(node.tool_id, node.action, params)
            except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
                last_error = str(exc)
                attempts.append({"error": last_error, "recoverable": True})
                retries += 1
                continue
            output = raw if isinstance(raw, dict) else {"output": raw}
            last_output = output
            if output.get("success", False):
                return NodeExecutionResult(
                    node_id=node.node_id,
                    success=True,
                    tool_id=node.tool_id,
                    action=node.action,
                    params=dict(node.params or {}),
                    output=output,
                    retries=retries,
                    retryable=retryable,
                    started_at=started,
                    finished_at=_now_iso(),
                    duration_ms=int((time.perf_counter() - begin) * 1000),
                    attempts=attempts,
                )
            last_error = str(output.get("message") or output.get("error") or "未知错误")
            attempts.append({"error": last_error, "recoverable": True})
            retries += 1
        return NodeExecutionResult(
            node_id=node.node_id,
            success=False,
            tool_id=node.tool_id,
            action=node.action,
            params=dict(node.params or {}),
            output=last_output,
            error=last_error,
            retries=max(0, retries - 1),
            retryable=retryable,
            recovery_hint=self._recovery_hint(node),
            started_at=started,
            finished_at=_now_iso(),
            duration_ms=int((time.perf_counter() - begin) * 1000),
            attempts=attempts,
        )

    def _run_clarify(self, node: WorkflowNode, state: dict[str, Any]) -> NodeExecutionResult:
        params = node.params or {}
        question = str(params.get("question") or "").strip()
        answer_key = str(params.get("answer_key") or "confirmed").strip() or "confirmed"
        target_node_id = str(params.get("target_node_id") or "").strip()

        answers = state.get("_clarify_answers") or {}
        if not isinstance(answers, dict):
            answers = {}
        node_answers = answers.get(node.node_id)
        has_answer = isinstance(node_answers, dict) and node_answers.get(answer_key) is not None
        confirmed = bool(node_answers.get(answer_key)) if has_answer else False

        if has_answer:
            output: dict[str, Any] = {
                "success": True,
                "answer_confirmed": confirmed,
                "answer_key": answer_key,
            }
        else:
            # No answer: pause and route nowhere — the target/business node stays
            # un-dispatched (branch condition answer_confirmed == True never matches).
            output = {
                "success": True,
                "requires_confirmation": True,
                "answer_key": answer_key,
                "question": question,
                "target_node_id": target_node_id,
            }
        return NodeExecutionResult(
            node_id=node.node_id,
            success=True,
            tool_id=node.tool_id,
            action=node.action,
            params=dict(node.params or {}),
            output=output,
            retryable=False,
            started_at=_now_iso(),
            finished_at=_now_iso(),
            duration_ms=0,
        )

    def _resolve_successor(self, node: WorkflowNode, output: dict[str, Any]) -> str | None:
        target = self.evaluate_branch(node, output)
        if target is not None:
            return target
        return node.next

    @staticmethod
    def evaluate_branch(node: WorkflowNode, output: dict[str, Any]) -> str | None:
        """Return the target of the first matching branch, else ``None``."""
        if not isinstance(output, dict):
            output = {}
        for branch in node.branches or []:
            if XCAGILangGraphRuntime._condition_matches(branch.condition, output):
                return branch.target
        return None

    @staticmethod
    def _condition_matches(condition: dict[str, Any], output: dict[str, Any]) -> bool:
        if not isinstance(condition, dict):
            return False
        key = condition.get("key")
        if key is None or not isinstance(key, str):
            return False
        expected = condition.get("equals", condition.get("value"))
        return output.get(key) == expected

    @staticmethod
    def _recovery_hint(node: WorkflowNode) -> str:
        if node.idempotent:
            return "节点具备幂等性，可在修复后重试"
        if node.risk == "low":
            return "低风险节点，可安全重试"
        return "高风险/非幂等节点，请人工介入确认后再重试"

    # -- result mapping ------------------------------------------------------------

    @staticmethod
    def _trace_entry(result: NodeExecutionResult) -> dict[str, Any]:
        return {
            "node_id": result.node_id,
            "tool_id": result.tool_id,
            "action": result.action,
            "success": result.success,
            "error": result.error,
            "recovery_hint": result.recovery_hint,
        }

    @staticmethod
    def _result_dict(result: NodeExecutionResult) -> dict[str, Any]:
        return {
            "node_id": result.node_id,
            "success": result.success,
            "tool_id": result.tool_id,
            "action": result.action,
            "params": result.params,
            "output": result.output,
            "error": result.error,
            "retries": result.retries,
            "retryable": result.retryable,
            "recovery_hint": result.recovery_hint,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "duration_ms": result.duration_ms,
            "attempts": result.attempts,
        }

    def _to_run_result(self, plan: PlanGraph, state: dict[str, Any]) -> WorkflowRunResult:
        node_results = [NodeExecutionResult(**dict(r)) for r in (state.get("results") or [])]
        failure = state.get("failure")
        if failure:
            state["workflow_status"] = {
                "state": "failed",
                "failed_node_id": failure.get("node_id"),
                "message": failure.get("error"),
                "recovery_hint": failure.get("recovery_hint"),
            }
            return WorkflowRunResult(
                plan_id=plan.plan_id,
                success=False,
                node_results=node_results,
                final_context=state,
                message=f"节点 {failure.get('node_id')} 执行失败: {failure.get('error')}",
            )
        state["workflow_status"] = {
            "state": "completed",
            "executed_nodes": sorted(state.get("executed") or []),
            "message": "工作流执行完成",
        }
        return WorkflowRunResult(
            plan_id=plan.plan_id,
            success=True,
            node_results=node_results,
            final_context=state,
            message="工作流执行完成",
        )

    # -- checkpoint / events -------------------------------------------------------

    def _stream_run(
        self,
        graph: Any,
        plan: PlanGraph,
        initial: dict[str, Any],
        checkpointer: CheckpointStore | None,
        parallel: bool = True,
    ) -> dict[str, Any]:
        """Stream ``stream_mode="values"`` and checkpoint after each successful superstep.

        A checkpoint is saved only when a superstep succeeds (no ``failure``) and the
        count of executed nodes strictly grows — a failed superstep is never persisted.
        The last yielded value is the final graph state (equivalent to ``invoke``).

        When ``parallel=True``, real same-superstep batches containing more than one
        low-risk AND idempotent node are recorded under ``parallel_batches`` in the
        final context.
        """
        last_saved = len(initial.get("executed") or [])
        final = dict(initial)
        reader_ids = {n.node_id for n in plan.nodes if _ReadersWriterGate.is_reader(n)}
        batches: list[list[str]] = []
        prev_executed = set(initial.get("executed") or [])
        for chunk in graph.stream(
            dict(initial),
            config={"recursion_limit": self._recursion_limit(plan)},
            stream_mode="values",
        ):
            final = chunk
            executed = chunk.get("executed") or []
            if not (chunk.get("failure") or {}):
                if len(executed) > last_saved:
                    if checkpointer is not None:
                        self._save_checkpoint(checkpointer, plan, chunk)
                    last_saved = len(executed)
            cur = set(executed)
            batch = sorted(cur - prev_executed)
            prev_executed = cur
            if parallel and len(batch) > 1 and all(nid in reader_ids for nid in batch):
                batches.append(batch)
        if parallel and batches:
            final["parallel_batches"] = batches
        return final

    @staticmethod
    def _save_checkpoint(
        checkpointer: CheckpointStore, plan: PlanGraph, state: dict[str, Any]
    ) -> str:
        return checkpointer.save_checkpoint(
            plan.plan_id,
            len(state.get("executed") or []),
            dict(state),
            sorted(state.get("executed") or []),
            blocked=sorted(state.get("blocked") or []),
        )

    @staticmethod
    def _replay_from_trace(
        traces: list[dict[str, Any]], outputs: dict[str, Any]
    ) -> list[NodeExecutionResult]:
        results: list[NodeExecutionResult] = []
        for t in traces:
            nid = t.get("node_id", "")
            results.append(
                NodeExecutionResult(
                    node_id=nid,
                    success=bool(t.get("success")),
                    tool_id=t.get("tool_id", ""),
                    action=t.get("action", ""),
                    output=dict(outputs.get(nid) or {}),
                    error=t.get("error", ""),
                    recovery_hint=t.get("recovery_hint", ""),
                )
            )
        return results

    def _emit_state_update(self, result: NodeExecutionResult) -> None:
        status = "succeeded" if result.success else "failed"
        event = {
            "type": "state.update",
            "node_id": result.node_id,
            "status": status,
            "output_summary": _summarize_output(result.output),
        }
        if self._callback is not None:
            try:
                self._callback(event)
            except Exception:  # noqa: BLE001
                logger.exception("state callback failed node=%s", result.node_id)
        if self._publisher is not None:
            try:
                self._publisher.publish_state_update(
                    StateUpdateEvent(
                        node_id=result.node_id,
                        status=status,
                        output_summary=_summarize_output(result.output),
                        runtime="xcagi-langgraph",
                        payload=event,
                    )
                )
            except Exception:  # noqa: BLE001
                logger.exception("state publisher failed node=%s", result.node_id)


def _default_dispatcher(tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": False,
        "message": f"未接线 dispatcher: {tool_id}.{action}",
    }
