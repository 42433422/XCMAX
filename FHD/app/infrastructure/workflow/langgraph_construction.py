"""Graph construction, invocation, routing, and state-schema mixin."""

from __future__ import annotations

import operator
from collections.abc import Hashable
from typing import TYPE_CHECKING, Annotated, Any, TypedDict, cast

from app.application.workflow.ports.checkpoint import CheckpointStore
from app.application.workflow.types import (
    NodeExecutionResult,
    PlanGraph,
    StateField,
    StateSchema,
    WorkflowNode,
    WorkflowRunResult,
    apply_state_schema,
)
from app.infrastructure.workflow.langgraph_runtime import (
    _INTERNAL_CHANNELS,
    END,
    START,
    StateGraph,
    _merge_dict,
    _ReadersWriterGate,
)


class LangGraphConstructionMixin:
    _state_schema: StateSchema | None
    _callback: Any

    if TYPE_CHECKING:

        def _execute_node(
            self, node: WorkflowNode, state: dict[str, Any], max_retries: int
        ) -> NodeExecutionResult: ...
        def _resolve_successor(self, node: WorkflowNode, output: dict[str, Any]) -> str | None: ...
        @staticmethod
        def _trace_entry(result: NodeExecutionResult) -> dict[str, Any]: ...
        def _result_dict(self, result: NodeExecutionResult) -> dict[str, Any]: ...
        def _emit_state_update(self, result: NodeExecutionResult) -> None: ...
        def _to_run_result(
            self, plan: PlanGraph, final_state: dict[str, Any]
        ) -> WorkflowRunResult: ...
        def _stream_run(
            self,
            graph: Any,
            plan: PlanGraph,
            initial: dict[str, Any],
            checkpointer: CheckpointStore | None,
            parallel: bool = True,
        ) -> dict[str, Any]: ...
        @staticmethod
        def _save_checkpoint(
            checkpointer: CheckpointStore, plan: PlanGraph, state: dict[str, Any]
        ) -> str: ...
        @staticmethod
        def _replay_from_trace(
            traces: list[dict[str, Any]], outputs: dict[str, Any]
        ) -> list[NodeExecutionResult]: ...

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
        return cast(
            "dict[str, Any]",
            graph.invoke(
                self._initial_state(runtime_context),
                config={"recursion_limit": self._recursion_limit(plan)},
                **kwargs,
            ),
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
    ) -> type[Any]:
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
        # The functional TypedDict constructor intentionally accepts runtime fields;
        # expose the resulting class to LangGraph without pretending it is a static
        # TypedDict declaration.
        typed_dict_factory = cast(Any, TypedDict)
        return cast("type[Any]", typed_dict_factory("XCAGIWorkflowState", fields))

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
            path_map: dict[Hashable, str] = {t: t for t in targets}
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
                    if effective_schema is None:  # defensive; schema_fields is empty in this case
                        raise RuntimeError("workflow state schema is unavailable")
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
