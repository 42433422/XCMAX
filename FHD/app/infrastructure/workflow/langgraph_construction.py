"""Graph construction, invocation, routing, and state-schema mixin."""

from __future__ import annotations

import operator
from collections.abc import Hashable
from copy import deepcopy
from typing import TYPE_CHECKING, Annotated, Any, TypedDict, cast

from app.application.workflow.ports import CheckpointStore
from app.application.workflow.workflow_types import (
    NodeExecutionResult,
    PlanGraph,
    StateField,
    StateSchema,
    WorkflowNode,
    WorkflowRunResult,
    apply_state_schema,
    normalize_workflow_risk,
    plan_fingerprint,
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
        from app.application.workflow.workflow_types import validate_plan_graph

        if error := validate_plan_graph(plan):
            raise ValueError(f"工作流计划无效：{error}")
        # LangGraph's parallel edge triggers do not express an AND-join when a
        # child also sits behind a conditional route. Use the explicit ready
        # scheduler whenever routing or multiple prerequisites are present.
        serial_scheduler = not parallel or any(
            node.branches or node.next or len(node.depends_on) > 1 for node in plan.nodes
        )
        if serial_scheduler and "__xcagi_schedule__" in {node.node_id for node in plan.nodes}:
            raise ValueError("计划节点占用了 LangGraph 调度保留标识")
        gate = _ReadersWriterGate(parallel)
        effective = state_schema or self._state_schema
        graph = StateGraph(self._schema(runtime_context, effective))
        for node in plan.nodes:
            graph.add_node(
                node.node_id,
                self._make_node_fn(
                    node,
                    max_retries,
                    [n.node_id for n in plan.nodes],
                    gate,
                    effective,
                    block_unselected=parallel,
                ),
            )
        if serial_scheduler:
            self._add_serial_scheduler(graph, plan)
        else:
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
        tool_registry: dict[str, Any] | None = None,
        user_id: str | None = None,
        state_schema: StateSchema | None = None,
        parallel: bool = True,
        checkpointer: CheckpointStore | None = None,
        state_event_callback: Any | None = None,
    ) -> WorkflowRunResult:
        submitted_plan_sha256 = plan_fingerprint(plan)
        registry_validated = tool_registry is not None
        if tool_registry is not None:
            from app.application.workflow.planning_graph_policy import validate_required_params

            plan = deepcopy(plan)
            for node in plan.nodes:
                if node.tool_id == "clarify":
                    continue
                spec = tool_registry.get(node.tool_id)
                actions = spec.get("actions") if isinstance(spec, dict) else None
                if not isinstance(actions, dict) or node.action not in actions:
                    raise ValueError(
                        f"工作流计划包含未注册的工具动作：{node.tool_id}.{node.action}"
                    )
                action_spec = actions[node.action]
                if not isinstance(action_spec, dict):
                    raise ValueError(f"工具动作配置无效：{node.tool_id}.{node.action}")
                node.risk = normalize_workflow_risk(action_spec.get("risk"), default="high")
                node.idempotent = action_spec.get("idempotent") is True
            if error := validate_required_params(plan, tool_registry):
                raise ValueError(f"工作流计划无效：{error}")
        self._callback = state_event_callback
        try:
            initial = self._initial_state(runtime_context)
            initial["plan_audit"] = self._plan_audit_record(
                plan, submitted_plan_sha256, registry_validated
            )
            graph = self.compile_graph(
                plan,
                runtime_context=initial,
                state_schema=state_schema,
                max_retries=max_retries,
                parallel=parallel,
            )
            final = self._stream_run(graph, plan, dict(initial), checkpointer, parallel=parallel)
            result = self._to_run_result(plan, final)
            # Persist terminal completion and interaction pauses. Failed-node
            # supersteps remain excluded so recovery cannot mistake a failed call
            # for completed work.
            final_status = (final.get("workflow_status") or {}).get("state")
            if checkpointer is not None and (
                result.success or final_status in {"waiting_user", "waiting_approval", "blocked"}
            ):
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
        prior_audit = initial.get("plan_audit")
        if (
            not isinstance(prior_audit, dict)
            or prior_audit.get("passed") is not True
            or prior_audit.get("submitted_plan_sha256") != plan_fingerprint(plan)
        ):
            return WorkflowRunResult(
                plan_id=plan.plan_id,
                success=False,
                message="工作流检查点未绑定当前审批计划，拒绝恢复；请重新规划并审批",
            )
        resume_plan = deepcopy(plan)
        if prior_audit.get("registry_validated") is True:
            from app.application.workflow.planning_graph_policy import validate_required_params
            from app.application.workflow_registry_app import get_workflow_tool_registry

            registry = get_workflow_tool_registry()
            for node in resume_plan.nodes:
                if node.tool_id == "clarify":
                    continue
                spec = registry.get(node.tool_id)
                actions = spec.get("actions") if isinstance(spec, dict) else None
                action = actions.get(node.action) if isinstance(actions, dict) else None
                if not isinstance(action, dict):
                    return WorkflowRunResult(
                        plan_id=plan.plan_id,
                        success=False,
                        message=f"恢复计划中的工具动作已失效：{node.tool_id}.{node.action}",
                    )
                node.risk = normalize_workflow_risk(action.get("risk"), default="high")
                node.idempotent = action.get("idempotent") is True
            if error := validate_required_params(resume_plan, registry):
                return WorkflowRunResult(
                    plan_id=plan.plan_id, success=False, message=f"恢复计划复核失败：{error}"
                )
        if plan_fingerprint(resume_plan) != prior_audit.get("plan_sha256"):
            return WorkflowRunResult(
                plan_id=plan.plan_id,
                success=False,
                message="工作流检查点计划版本已变化，拒绝恢复；请重新规划并审批",
            )
        initial["plan_audit"] = self._plan_audit_record(
            resume_plan,
            str(prior_audit.get("submitted_plan_sha256") or ""),
            prior_audit.get("registry_validated") is True,
        )
        graph = self.compile_graph(
            resume_plan,
            runtime_context=initial,
            state_schema=state_schema,
            max_retries=max_retries,
            parallel=parallel,
        )
        final = self._stream_run(graph, resume_plan, dict(initial), checkpointer, parallel=parallel)
        result = self._to_run_result(resume_plan, final)
        final_status = (final.get("workflow_status") or {}).get("state")
        if result.success or final_status in {"waiting_user", "waiting_approval", "blocked"}:
            self._save_checkpoint(checkpointer, resume_plan, final)
        return result

    @staticmethod
    def _plan_audit_record(
        plan: PlanGraph, submitted_plan_sha256: str, registry_validated: bool
    ) -> dict[str, Any]:
        """Structured, deterministic evidence that the graph was audited before dispatch."""
        return {
            "passed": True,
            "plan_sha256": plan_fingerprint(plan),
            "submitted_plan_sha256": submitted_plan_sha256,
            "registry_validated": registry_validated,
            "node_count": len(plan.nodes),
            "actions": [
                {"node_id": node.node_id, "tool_id": node.tool_id, "action": node.action}
                for node in plan.nodes
            ],
        }

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
            "next_node": str,
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

    def _add_serial_scheduler(self, graph: StateGraph, plan: PlanGraph) -> None:
        """Schedule one ready node per graph turn, preserving AND deps and OR routes."""
        schedule_id = "__xcagi_schedule__"
        nodes = list(plan.nodes)
        node_ids = {node.node_id for node in nodes}

        def schedule(state: dict[str, Any]) -> dict[str, Any]:
            executed = set(state.get("executed") or [])
            blocked = set(state.get("blocked") or [])
            outputs = state.get("node_outputs") or {}
            if any(
                isinstance(outputs.get(nid), dict)
                and (
                    outputs[nid].get("requires_confirmation")
                    or outputs[nid].get("requires_approval")
                )
                for nid in executed
            ):
                return {"next_node": "__end__"}
            newly_blocked: list[str] = []
            while True:
                progressed = False
                for node in nodes:
                    nid = node.node_id
                    if nid in executed or nid in blocked or nid in newly_blocked:
                        continue
                    if any(dep in blocked or dep in newly_blocked for dep in node.depends_on):
                        newly_blocked.append(nid)
                        progressed = True
                        continue
                    if any(dep not in executed for dep in node.depends_on):
                        continue
                    routers = [source for source in nodes if nid in self._candidates(source)]
                    if any(
                        source.node_id not in executed | blocked | set(newly_blocked)
                        for source in routers
                    ):
                        continue
                    if any(
                        source.node_id in executed
                        and source.node_id not in blocked
                        and not isinstance(outputs.get(source.node_id), dict)
                        for source in routers
                    ):
                        return {
                            "next_node": "__end__",
                            "blocked": newly_blocked,
                            "failure": {
                                "node_id": nid,
                                "error": "条件路由缺少已执行节点的结果证据",
                                "recovery_hint": "检查 checkpoint 中的路由输出后再恢复。",
                            },
                            "workflow_status": {"state": "blocked", "message": "路由证据不完整"},
                        }
                    selected_by_router = any(
                        source.node_id in executed
                        and self._resolve_successor(source, outputs.get(source.node_id, {})) == nid
                        for source in routers
                    )
                    if routers and not selected_by_router:
                        newly_blocked.append(nid)
                        progressed = True
                        continue
                    return {"next_node": nid, "blocked": newly_blocked}
                if not progressed:
                    break
            remaining = node_ids - executed - blocked - set(newly_blocked)
            if remaining:
                return {
                    "next_node": "__end__",
                    "blocked": newly_blocked,
                    "failure": {
                        "node_id": schedule_id,
                        "error": "LangGraph 无法找到满足依赖与路由条件的后续节点",
                        "recovery_hint": "计划已暂停；请检查依赖和分支证据后重新规划。",
                    },
                    "workflow_status": {"state": "blocked", "message": "计划执行进入死端"},
                }
            return {"next_node": "__end__", "blocked": newly_blocked}

        def route(state: dict[str, Any]) -> str:
            target = str(state.get("next_node") or "__end__")
            return target if target in node_ids else "__end__"

        graph.add_node(schedule_id, schedule)
        graph.add_edge(START, schedule_id)
        for node in nodes:
            graph.add_edge(node.node_id, schedule_id)
        graph.add_conditional_edges(
            schedule_id,
            route,
            {**{node_id: node_id for node_id in node_ids}, "__end__": END},
        )

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
            # Clarification and approval are durable interaction checkpoints. The
            # graph must stop at them; following a normal edge could execute a
            # dependent write before the user has answered or approved it.
            output = (state.get("node_outputs") or {}).get(nid, {})
            if isinstance(output, dict) and (
                output.get("requires_confirmation") or output.get("requires_approval")
            ):
                return "__end__"
            if candidates:
                chosen = self._resolve_successor(node, output)
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
        block_unselected: bool = True,
    ) -> Any:
        nid = node.node_id
        candidates = set(self._candidates(node))
        schema_fields = effective_schema.fields if effective_schema is not None else {}

        def fn(state: dict[str, Any]) -> dict[str, Any]:
            if nid in (state.get("blocked") or []) or nid in (state.get("executed") or []):
                return {}
            with gate.execution(node):
                node_state = {**state, "_langgraph_node_id": nid}
                result = self._execute_node(node, node_state, max_retries)
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
            if candidates and block_unselected:
                chosen = self._resolve_successor(node, result.output)
                to_block = [c for c in candidates if c != chosen]
                if to_block:
                    update.setdefault("blocked", [])
                    update["blocked"].extend(c for c in to_block if c not in update["blocked"])
            self._emit_state_update(result)
            return update

        return fn

    # -- node execution ----------------------------------------------------------
