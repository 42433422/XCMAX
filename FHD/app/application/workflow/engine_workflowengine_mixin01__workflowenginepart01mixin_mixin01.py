# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.engine")


class __WorkflowEnginePart01MixinPart01Mixin:
    def __init__(self, tool_dispatcher, state_event_callback: _facade().Any | None = None) -> None:
        self._dispatch = tool_dispatcher
        self._default_state_schema = _facade().DEFAULT_STATE_SCHEMA
        self._state_event_callback = state_event_callback

    def run(
        self,
        plan: _facade().PlanGraph,
        runtime_context: dict[str, _facade().Any] | None = None,
        max_retries: int = 1,
        agentic_loop: bool = False,
        tool_registry: dict[str, _facade().Any] | None = None,
        user_id: str | None = None,
        state_schema: _facade().StateSchema | None = None,
        parallel: bool = True,
        checkpointer: _facade().Any | None = None,
        state_event_callback: _facade().Any | None = None,
    ) -> _facade().WorkflowRunResult:
        previous_callback = self._state_event_callback
        if state_event_callback is not None:
            self._state_event_callback = state_event_callback
        try:
            if agentic_loop and tool_registry:
                return self._run_agentic_loop(
                    plan, runtime_context, max_retries, tool_registry, user_id, state_schema
                )
            return self._run_batch(
                plan,
                runtime_context,
                max_retries,
                state_schema,
                parallel,
                checkpointer=checkpointer,
            )
        finally:
            self._state_event_callback = previous_callback

    def _run_batch(
        self,
        plan: _facade().PlanGraph,
        runtime_context: dict[str, _facade().Any] | None = None,
        max_retries: int = 1,
        state_schema: _facade().StateSchema | None = None,
        parallel: bool = True,
        checkpointer: _facade().Any | None = None,
        resume_state: dict[str, _facade().Any] | None = None,
    ) -> _facade().WorkflowRunResult:
        if resume_state is not None:
            runtime_context = dict(resume_state.get("runtime_context") or {})
            executed: set[str] = set(resume_state.get("executed", set()))
            blocked: set[str] = set(resume_state.get("blocked", set()))
        else:
            runtime_context = dict(runtime_context or {})
            executed = set()
            blocked = set()
        schema = state_schema or self._default_state_schema
        node_results: list[_facade().NodeExecutionResult] = []
        pending: dict[str, _facade().WorkflowNode] = {
            node.node_id: node for node in plan.nodes if node.node_id not in executed
        }
        stalled_rounds = 0

        def _is_write_node(node: _facade().WorkflowNode) -> bool:
            return node.risk == "high" or not node.idempotent

        def _ready(node: _facade().WorkflowNode) -> bool:
            return node.node_id not in blocked and all(dep in executed for dep in node.depends_on)

        while pending:
            stalled = True
            progressed = False
            while True:
                ready_routers = [
                    node
                    for node in pending.values()
                    if (node.branches or node.next is not None) and _ready(node)
                ]
                if not ready_routers:
                    break
                stalled = False
                progressed = True
                for node in ready_routers:
                    result = self._run_node(node, runtime_context, max_retries=max_retries)
                    self._record_result(
                        result, runtime_context, schema, node_results, executed, pending
                    )
                    if not result.success:
                        return self._fail_run(plan, node_results, runtime_context, result)
                    self._advance_router(node, result.output, pending, blocked)
            ready_non_routers = [
                node
                for node in pending.values()
                if not (node.branches or node.next is not None) and _ready(node)
            ]
            if ready_non_routers:
                stalled = False
                progressed = True
                read_nodes = [n for n in ready_non_routers if not _is_write_node(n)]
                write_nodes = [n for n in ready_non_routers if _is_write_node(n)]
                failed = self._run_ready_batch(
                    read_nodes,
                    write_nodes,
                    runtime_context,
                    max_retries,
                    parallel,
                    schema,
                    node_results,
                    executed,
                    pending,
                )
                if failed is not None:
                    return self._fail_run(plan, node_results, runtime_context, failed)
            if progressed:
                self._maybe_checkpoint(checkpointer, plan, runtime_context, executed, blocked)
            if stalled:
                stalled_rounds += 1
                if stalled_rounds > 1:
                    unresolved = ",".join(pending.keys())
                    runtime_context["workflow_status"] = {
                        "state": "blocked",
                        "unresolved_nodes": list(pending.keys()),
                        "message": f"工作流依赖无法继续解析: {unresolved}",
                    }
                    return _facade().WorkflowRunResult(
                        plan_id=plan.plan_id,
                        success=False,
                        node_results=node_results,
                        final_context=runtime_context,
                        message=f"工作流依赖无法继续解析: {unresolved}",
                    )
            else:
                stalled_rounds = 0
        runtime_context["workflow_status"] = {
            "state": "completed",
            "executed_nodes": list(executed),
            "message": "工作流执行完成",
        }
        self._maybe_checkpoint(checkpointer, plan, runtime_context, executed, blocked)
        return _facade().WorkflowRunResult(
            plan_id=plan.plan_id,
            success=True,
            node_results=node_results,
            final_context=runtime_context,
            message="工作流执行完成",
        )

    @staticmethod
    def _maybe_checkpoint(
        checkpointer: _facade().Any,
        plan: _facade().PlanGraph,
        runtime_context: dict[str, _facade().Any],
        executed: set[str],
        blocked: set[str],
    ) -> str | None:
        """若提供了 checkpointer，记录一次 checkpoint；否则返回 None。"""
        if checkpointer is None:
            return None
        checkpoint_id = checkpointer.save_checkpoint(
            plan.plan_id, len(executed), runtime_context, sorted(executed), blocked=sorted(blocked)
        )
        return str(checkpoint_id) if checkpoint_id is not None else None

    def resume_run(
        self,
        plan: _facade().PlanGraph,
        checkpoint_id: str,
        *,
        checkpointer: _facade().Any,
        max_retries: int = 1,
        state_schema: _facade().StateSchema | None = None,
        parallel: bool = True,
    ) -> _facade().WorkflowRunResult:
        """从指定 checkpoint 断点续跑。

        恢复 ``runtime_context`` 与 ``executed_nodes``，只执行尚未完成的节点，
        不重复执行已完成节点。
        """
        if checkpointer is None:
            return _facade().WorkflowRunResult(
                plan_id=plan.plan_id, success=False, message="resume_run 需要 checkpointer"
            )
        checkpoint = checkpointer.get_checkpoint(plan.plan_id, checkpoint_id)
        if checkpoint is None:
            return _facade().WorkflowRunResult(
                plan_id=plan.plan_id, success=False, message=f"checkpoint 不存在: {checkpoint_id}"
            )
        resume_state: dict[str, _facade().Any] = {
            "runtime_context": checkpoint.get("runtime_context") or {},
            "executed": list(checkpoint.get("executed_nodes") or []),
            "blocked": list(checkpoint.get("blocked") or []),
        }
        return self._run_batch(
            plan,
            max_retries=max_retries,
            state_schema=state_schema,
            parallel=parallel,
            checkpointer=checkpointer,
            resume_state=resume_state,
        )

    def replay_run(
        self, plan_id: str, checkpoint_id: str | None = None, *, checkpointer: _facade().Any
    ) -> _facade().WorkflowRunResult:
        """只读重放 checkpoint 中已执行节点的输出历史（不真正再执行工具）。

        用于审计/回归：重放结果（node_results + final_context）与原始运行一致。
        未指定 ``checkpoint_id`` 时使用最新 checkpoint。
        """
        if checkpointer is None:
            return _facade().WorkflowRunResult(
                plan_id=plan_id, success=False, message="replay_run 需要 checkpointer"
            )
        if checkpoint_id is not None:
            checkpoint = checkpointer.get_checkpoint(plan_id, checkpoint_id)
        else:
            checkpoint = getattr(checkpointer, "latest_checkpoint", lambda p: None)(plan_id)
        if checkpoint is None:
            return _facade().WorkflowRunResult(
                plan_id=plan_id, success=False, message="checkpoint 不存在，无法重放"
            )
        rc = checkpoint.get("runtime_context") or {}
        traces = rc.get("workflow_trace") or []
        outputs = rc.get("node_outputs") or {}
        node_results: list[_facade().NodeExecutionResult] = []
        for tr in traces:
            node_id = str(tr.get("node_id", ""))
            output = outputs.get(node_id, {})
            node_results.append(
                _facade().NodeExecutionResult(
                    node_id=node_id,
                    success=bool(tr.get("success")),
                    tool_id=str(tr.get("tool_id", "")),
                    action=str(tr.get("action", "")),
                    output=output if isinstance(output, dict) else {},
                    error=str(tr.get("error", "")),
                    retries=int(tr.get("retries", 0)),
                    retryable=bool(tr.get("retryable")),
                    recovery_hint=str(tr.get("recovery_hint", "")),
                    duration_ms=int(tr.get("duration_ms", 0)),
                )
            )
        workflow_status = rc.get("workflow_status") or {}
        success = bool(node_results) and workflow_status.get("state") == "completed"
        return _facade().WorkflowRunResult(
            plan_id=plan_id,
            success=success,
            node_results=node_results,
            final_context=dict(rc),
            message="重放自 checkpoint",
        )

    def _run_ready_batch(
        self,
        read_nodes: list[_facade().WorkflowNode],
        write_nodes: list[_facade().WorkflowNode],
        runtime_context: dict[str, _facade().Any],
        max_retries: int,
        parallel: bool,
        schema: _facade().StateSchema,
        node_results: list[_facade().NodeExecutionResult],
        executed: set[str],
        pending: dict[str, _facade().WorkflowNode],
    ) -> _facade().NodeExecutionResult | None:
        """并发/串行执行就绪节点并归并上下文；返回首个失败节点结果，全部成功返回 None。"""
        batch_results: list[_facade().NodeExecutionResult] = []
        if read_nodes and parallel:
            try:
                requested_workers = int(runtime_context.get("max_parallel_workers") or 4)
            except (TypeError, ValueError):
                requested_workers = 4
            max_workers = max(1, min(requested_workers, 8, len(read_nodes)))
            if len(read_nodes) > 1:
                runtime_context.setdefault("parallel_batches", []).append(
                    {"node_ids": [node.node_id for node in read_nodes], "max_workers": max_workers}
                )
            with _facade().ThreadPoolExecutor(max_workers=max_workers) as executor:
                read_map = {node.node_id: node for node in read_nodes}
                future_map = {
                    node_id: executor.submit(
                        self._run_node, node, runtime_context, max_retries=max_retries
                    )
                    for node_id, node in read_map.items()
                }
                for node in read_nodes:
                    batch_results.append(future_map[node.node_id].result())
        else:
            for node in read_nodes:
                batch_results.append(self._run_node(node, runtime_context, max_retries=max_retries))
        for node in write_nodes:
            batch_results.append(self._run_node(node, runtime_context, max_retries=max_retries))
        for result in batch_results:
            self._record_result(result, runtime_context, schema, node_results, executed, pending)
            if not result.success:
                return result
        return None

    def _record_result(
        self,
        result: _facade().NodeExecutionResult,
        runtime_context: dict[str, _facade().Any],
        schema: _facade().StateSchema,
        node_results: list[_facade().NodeExecutionResult],
        executed: set[str],
        pending: dict[str, _facade().WorkflowNode],
    ) -> None:
        """记录节点结果并归并上下文（主线程统一执行，避免并发写冲突）。"""
        node_results.append(result)
        executed.add(result.node_id)
        pending.pop(result.node_id, None)
        runtime_context.setdefault("node_outputs", {})
        runtime_context["node_outputs"][result.node_id] = result.output
        self._append_node_trace(runtime_context, result)
        self._merge_state_schema(runtime_context, result, schema)
        self._emit_state_update(result)

    def _emit_state_update(self, result: _facade().NodeExecutionResult) -> None:
        """节点完成后回调 ``state.update`` 事件（成功与失败均触发；回调异常不影响主流程）。"""
        callback = self._state_event_callback
        if callback is None:
            return
        try:
            callback(
                {
                    "type": "state.update",
                    "node_id": result.node_id,
                    "status": "succeeded" if result.success else "failed",
                    "output_summary": self._summarize_output(result.output),
                }
            )
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.warning(
                "state_event_callback failed node=%s", result.node_id, exc_info=True
            )

    @staticmethod
    def _fail_run(
        plan: _facade().PlanGraph,
        node_results: list[_facade().NodeExecutionResult],
        runtime_context: dict[str, _facade().Any],
        result: _facade().NodeExecutionResult,
    ) -> _facade().WorkflowRunResult:
        runtime_context["workflow_status"] = {
            "state": "failed",
            "failed_node_id": result.node_id,
            "message": result.error,
            "recovery_hint": result.recovery_hint,
        }
        return _facade().WorkflowRunResult(
            plan_id=plan.plan_id,
            success=False,
            node_results=node_results,
            final_context=runtime_context,
            message=f"节点 {result.node_id} 执行失败: {result.error}",
        )
