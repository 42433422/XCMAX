"""DAG dependency routing and ordered read/write execution.

Tool execution and state publication are ports. The scheduler owns only graph
progress; completed read results are merged in plan order before any writes.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Any, Protocol

from .engine_checkpoints import save_progress
from .ports import CheckpointStore
from .workflow_types import (
    NodeExecutionResult,
    PlanGraph,
    StateSchema,
    WorkflowNode,
    WorkflowRunResult,
    validate_plan_graph,
)


class NodeRunner(Protocol):
    def __call__(
        self, node: WorkflowNode, runtime_context: dict[str, Any], max_retries: int = 1
    ) -> NodeExecutionResult: ...


ResultRecorder = Callable[[NodeExecutionResult, dict[str, Any], StateSchema], None]
RoutingPolicy = Callable[[WorkflowNode, PlanGraph, set[str], set[str], object], str]
SuccessorResolver = Callable[[WorkflowNode, dict[str, Any]], str | None]


def routing_state(
    node: WorkflowNode,
    plan: PlanGraph,
    executed: set[str],
    blocked: set[str],
    outputs: object,
    *,
    successor: SuccessorResolver | None = None,
) -> str:
    """Data dependencies are AND; incoming control edges select by OR."""
    if node.node_id in blocked or any(dep in blocked for dep in node.depends_on):
        return "skipped"
    routers = [source for source in plan.nodes if node.node_id in branch_candidates(source)]
    if any(dep not in executed for dep in node.depends_on) or any(
        source.node_id not in executed | blocked for source in routers
    ):
        return "waiting"
    if not isinstance(outputs, dict) or any(
        source.node_id in executed and not isinstance(outputs.get(source.node_id), dict)
        for source in routers
    ):
        return "waiting"  # Never guess a decision from an incomplete checkpoint.
    select = successor if successor is not None else resolve_successor
    excluded = routers and all(
        source.node_id in blocked or select(source, outputs[source.node_id]) != node.node_id
        for source in routers
    )
    return "skipped" if excluded else "ready"


def resolve_successor(node: WorkflowNode, output: dict[str, Any]) -> str | None:
    target = evaluate_branch(node, output)
    if target is not None:
        return target
    return node.next


def evaluate_branch(node: WorkflowNode, output: dict[str, Any]) -> str | None:
    """按 output 匹配 node.branches 中第一条成功的 condition，返回 target node_id；无匹配返回 None。"""
    if not isinstance(output, dict):
        output = {}
    for branch in node.branches:
        if condition_matches(branch.condition, output):
            return branch.target
    return None


def condition_matches(condition: dict[str, Any], output: dict[str, Any]) -> bool:
    if not isinstance(condition, dict):
        return False
    key = condition.get("key")
    if key is None or not isinstance(key, str):
        return False
    expected = condition.get("equals", condition.get("value"))
    return output.get(key) == expected


def branch_candidates(node: WorkflowNode) -> list[str]:
    return ([node.next] if node.next is not None else []) + [b.target for b in node.branches]


def fail_run(
    plan: PlanGraph,
    node_results: list[NodeExecutionResult],
    runtime_context: dict[str, Any],
    result: NodeExecutionResult,
) -> WorkflowRunResult:
    runtime_context["workflow_status"] = {
        "state": "failed",
        "failed_node_id": result.node_id,
        "message": result.error,
        "recovery_hint": result.recovery_hint,
    }
    return WorkflowRunResult(
        plan_id=plan.plan_id,
        success=False,
        node_results=node_results,
        final_context=runtime_context,
        message=f"节点 {result.node_id} 执行失败: {result.error}",
    )


class DagScheduler:
    def __init__(
        self,
        run_node: NodeRunner,
        record_result: ResultRecorder,
        default_schema: StateSchema,
        route: RoutingPolicy = routing_state,
    ) -> None:
        self._run_node = run_node
        self._record_result = record_result
        self._default_state_schema = default_schema
        self._route = route

    def _record(
        self,
        result: NodeExecutionResult,
        runtime_context: dict[str, Any],
        schema: StateSchema,
        node_results: list[NodeExecutionResult],
        executed: set[str],
        pending: dict[str, WorkflowNode],
    ) -> None:
        node_results.append(result)
        if result.success:
            executed.add(result.node_id)
        pending.pop(result.node_id, None)
        self._record_result(result, runtime_context, schema)

    def run(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        max_retries: int = 1,
        state_schema: StateSchema | None = None,
        parallel: bool = True,
        checkpointer: CheckpointStore | None = None,
        resume_state: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        if error := validate_plan_graph(plan):
            return WorkflowRunResult(
                plan_id=plan.plan_id,
                success=False,
                final_context={"workflow_status": {"state": "blocked", "message": error}},
                message=error,
            )
        if resume_state is not None:
            runtime_context = dict(resume_state.get("runtime_context") or {})
            executed: set[str] = set(resume_state.get("executed", set()))
            blocked: set[str] = set(resume_state.get("blocked", set()))
        else:
            runtime_context = dict(runtime_context or {})
            executed = set()
            blocked = set()
        schema = state_schema or self._default_state_schema
        node_results: list[NodeExecutionResult] = []
        pending: dict[str, WorkflowNode] = {
            node.node_id: node for node in plan.nodes if node.node_id not in executed | blocked
        }

        def _is_write_node(node: WorkflowNode) -> bool:
            return node.risk == "high" or not node.idempotent

        def _ready(node: WorkflowNode) -> bool:
            state = self._route(
                node, plan, executed, blocked, runtime_context.get("node_outputs", {})
            )
            if state == "skipped":
                blocked.add(node.node_id)
            return bool(state == "ready")

        while pending:
            before = (len(executed), len(blocked))
            ready_routers = [
                node
                for node in pending.values()
                if (node.branches or node.next is not None) and _ready(node)
            ]
            for node in ready_routers:
                if not _ready(node):
                    continue
                result = self._run_node(node, runtime_context, max_retries=max_retries)
                self._record(result, runtime_context, schema, node_results, executed, pending)
                if not result.success:
                    return fail_run(plan, node_results, runtime_context, result)
                save_progress(checkpointer, plan, runtime_context, executed, blocked)
            ready_non_routers = [
                node
                for node in pending.values()
                if not (node.branches or node.next is not None) and _ready(node)
            ]
            if ready_non_routers:
                read_nodes = [n for n in ready_non_routers if not _is_write_node(n)]
                write_nodes = [n for n in ready_non_routers if _is_write_node(n)]
                failed = self.run_ready_batch(
                    read_nodes,
                    write_nodes,
                    runtime_context,
                    max_retries,
                    parallel,
                    schema,
                    node_results,
                    executed,
                    pending,
                    on_progress=lambda: save_progress(
                        checkpointer, plan, runtime_context, executed, blocked
                    ),
                )
                if failed is not None:
                    return fail_run(plan, node_results, runtime_context, failed)
            for node_id in blocked:
                pending.pop(node_id, None)
            if before == (len(executed), len(blocked)):
                message = "工作流依赖无法继续解析: " + ",".join(pending)
                runtime_context["workflow_status"] = {
                    "state": "blocked",
                    "unresolved_nodes": list(pending),
                    "message": message,
                }
                return WorkflowRunResult(
                    plan_id=plan.plan_id,
                    success=False,
                    node_results=node_results,
                    final_context=runtime_context,
                    message=message,
                )
            if not ready_routers and not ready_non_routers:
                save_progress(checkpointer, plan, runtime_context, executed, blocked)
        runtime_context["workflow_status"] = {
            "state": "completed",
            "executed_nodes": list(executed),
            "message": "工作流执行完成",
        }
        save_progress(checkpointer, plan, runtime_context, executed, blocked)
        return WorkflowRunResult(
            plan_id=plan.plan_id,
            success=True,
            node_results=node_results,
            final_context=runtime_context,
            message="工作流执行完成",
        )

    def run_ready_batch(
        self,
        read_nodes: list[WorkflowNode],
        write_nodes: list[WorkflowNode],
        runtime_context: dict[str, Any],
        max_retries: int,
        parallel: bool,
        schema: StateSchema,
        node_results: list[NodeExecutionResult],
        executed: set[str],
        pending: dict[str, WorkflowNode],
        on_progress: Callable[[], object] | None = None,
    ) -> NodeExecutionResult | None:
        """并发/串行执行就绪节点并归并上下文；返回首个失败节点结果，全部成功返回 None。"""
        batch_results: list[NodeExecutionResult] = []
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
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                read_map = {node.node_id: node for node in read_nodes}
                future_map = {
                    node_id: executor.submit(
                        copy_context().run,
                        self._run_node,
                        node,
                        runtime_context,
                        max_retries=max_retries,
                    )
                    for node_id, node in read_map.items()
                }
                for node in read_nodes:
                    batch_results.append(future_map[node.node_id].result())
        else:
            for node in read_nodes:
                batch_results.append(self._run_node(node, runtime_context, max_retries=max_retries))
        first_failure = None
        for result in batch_results:
            self._record(result, runtime_context, schema, node_results, executed, pending)
            if not result.success and first_failure is None:
                first_failure = result
        if on_progress and any(result.success for result in batch_results):
            on_progress()
        if first_failure is not None:
            return first_failure
        for node in write_nodes:
            result = self._run_node(node, runtime_context, max_retries=max_retries)
            self._record(result, runtime_context, schema, node_results, executed, pending)
            if not result.success:
                return result
            if on_progress:
                on_progress()
        return None
