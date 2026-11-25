"""员工协作编排：``collaboration.depends_on`` 本地依赖图执行。

把 manifest 声明的上游依赖建模为 LangGraph DAG；上游 ``node_outputs``
注入下游 ``EmployeeAgent.run`` 输入。

仅用于 FHD 本地/桌面单机场景，不回写 MODstore duty_graph。
"""

from __future__ import annotations

import logging
from typing import Any

from app.application.employee_runtime.loader import (
    list_installed_pack_records,
    parse_employee_config_v2,
)
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.domain.employee.collaboration_graph import CollaborationGraph

logger = logging.getLogger(__name__)


class CollaborationPlanError(ValueError):
    """A declared dependency graph cannot safely be admitted."""


def _collaboration_failure(employee_id: str, code: str, message: str) -> dict[str, Any]:
    return {
        "skipped": False,
        "employee_id": employee_id,
        "success": False,
        "error_code": code,
        "message": message,
        "node_outputs": {},
        "node_results": [],
    }


def _resolve_depends_on(manifest: dict[str, Any], config: dict[str, Any]) -> list[str]:
    deps: list[str] = []
    collab = config.get("collaboration") if isinstance(config.get("collaboration"), dict) else {}
    if not isinstance(collab, dict):
        collab = {}
    for item in collab.get("depends_on") or []:
        s = str(item or "").strip()
        if s:
            deps.append(s)
    if not deps:
        for item in manifest.get("depends_on") or []:
            s = str(item or "").strip()
            if s:
                deps.append(s)
    return list(dict.fromkeys(deps))


def build_global_collaboration_graph() -> CollaborationGraph:
    """从已安装员工包构建全局 depends_on 图。"""
    graph = CollaborationGraph()
    for pack in list_installed_pack_records():
        manifest = pack.get("manifest") or {}
        pid = str(pack.get("pack_id") or manifest.get("id") or "").strip()
        if not pid:
            continue
        cfg = parse_employee_config_v2(manifest)
        graph.add(pid, _resolve_depends_on(manifest, cfg))
    return graph


class EmployeeOrchestrator:
    """本地员工依赖图编排器。"""

    def __init__(self, graph: CollaborationGraph | None = None) -> None:
        self.graph = graph or build_global_collaboration_graph()

    def depends_on(
        self, employee_id: str, manifest: dict[str, Any], config: dict[str, Any]
    ) -> list[str]:
        eid = str(employee_id or "").strip()
        local = _resolve_depends_on(manifest, config)
        if local:
            self.graph.add(eid, local)
        return self.graph.edges.get(eid, local)

    def build_plan(
        self, employee_id: str, task: str, *, include_root: bool = True
    ) -> PlanGraph | None:
        eid = str(employee_id or "").strip()
        cycle = self.graph.execution_cycle(eid)
        if cycle:
            logger.warning("employee collaboration cycle rejected")
            raise CollaborationPlanError("员工协作依赖存在环，未执行任何节点")
        order = self.graph.execution_order(eid)
        if len(order) <= 1:
            return None

        exec_order = order if include_root else [n for n in order if n != eid]
        if not exec_order:
            return None

        nodes: list[WorkflowNode] = []
        for node_eid in exec_order:
            direct_deps = [
                d for d in self.graph.edges.get(node_eid, []) if d in exec_order and d != node_eid
            ]
            nodes.append(
                WorkflowNode(
                    node_id=node_eid,
                    tool_id="employee",
                    action="context",
                    params={
                        "employee_id": node_eid,
                        "task": (
                            task if include_root and node_eid == eid else f"上游协作：{node_eid}"
                        ),
                        "input": {
                            "invoke_mode": "collaboration_context",
                            "source": "employee_collaboration",
                            "client_surface": "employee_runtime",
                            "root_employee_id": eid,
                        },
                    },
                    depends_on=direct_deps,
                    description=f"员工协作节点 {node_eid}",
                )
            )
        return PlanGraph(
            plan_id=f"emp-collab-{eid}",
            intent=f"员工 {eid} 协作编排",
            todo_steps=[f"执行 {n}" for n in exec_order],
            nodes=nodes,
            metadata={"root_employee_id": eid, "include_root": include_root},
        )

    def run_upstream(
        self,
        employee_id: str,
        task: str,
        *,
        manifest: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """仅执行 root 的 depends_on 上游链（不含 root 自身），供 EmployeeAgent 注入 context。"""
        return self.run_with_dependencies(
            employee_id,
            task,
            manifest=manifest,
            config=config,
            runtime_context=runtime_context,
            include_root=False,
        )

    def run_with_dependencies(
        self,
        employee_id: str,
        task: str,
        *,
        manifest: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        runtime_context: dict[str, Any] | None = None,
        include_root: bool = True,
    ) -> dict[str, Any]:
        """执行 depends_on 链并返回 WorkflowRunResult 摘要。"""
        manifest = manifest or {}
        config = config or {}
        self.depends_on(employee_id, manifest, config)
        try:
            plan = self.build_plan(employee_id, task, include_root=include_root)
        except CollaborationPlanError as exc:
            return _collaboration_failure(employee_id, "employee_dependency_cycle", str(exc))
        if plan is None:
            return {"skipped": True, "reason": "no depends_on", "employee_id": employee_id}

        ctx = dict(runtime_context or {})
        ctx.setdefault("task", task)
        ctx.setdefault("employee_id", employee_id)
        raw_user_id = ctx.get("user_id")
        try:
            user_id = int(raw_user_id) if raw_user_id is not None else 0
        except (TypeError, ValueError):
            user_id = 0
        if user_id <= 0:
            return {
                "skipped": False,
                "employee_id": employee_id,
                "success": False,
                "error_code": "employee_actor_required",
                "message": "员工协作缺少已认证的账号，已阻止执行",
                "node_outputs": {},
                "node_results": [],
            }
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.agent_orchestrator.business_action_ledger import canonical_hash
        from app.infrastructure.tenant_scope import current_tenant_id

        # Inherit the server's tenant scope, never infer it from node inputs.
        current_tenant = current_tenant_id()
        declared_tenant = ctx.get("tenant_id")
        if (
            isinstance(declared_tenant, bool)
            or (current_tenant is None and not declared_tenant)
            or (
                current_tenant is not None
                and declared_tenant is not None
                and str(declared_tenant) != str(current_tenant)
            )
        ):
            return _collaboration_failure(
                employee_id, "employee_tenant_scope_invalid", "员工协作租户范围缺失或不一致"
            )
        if current_tenant is not None:
            ctx["tenant_id"] = current_tenant
        stable_id = canonical_hash(
            {
                "employee_id": str(employee_id),
                "task": str(task),
                "include_root": include_root,
                "dependencies": [
                    {
                        "node_id": node.node_id,
                        "depends_on": list(node.depends_on),
                        "tool_id": node.tool_id,
                        "action": node.action,
                    }
                    for node in plan.nodes
                ],
                "user_id": user_id,
                "tenant_id": str(ctx.get("tenant_id") or ""),
                "mod_id": str(ctx.get("mod_id") or ""),
                "session_id": str(ctx.get("session_id") or ctx.get("conversation_id") or ""),
                "task_id": str(ctx.get("task_id") or ""),
                "parent_run_id": str(ctx.get("run_id") or ctx.get("agent_run_id") or ""),
                "parent_step_id": str(ctx.get("step_id") or ""),
            }
        )
        plan.plan_id = f"emp-collab-{stable_id[:32]}"
        ctx["employee_collaboration_run"] = True
        parent_run_id = str(ctx.get("run_id") or ctx.get("agent_run_id") or "").strip()
        if parent_run_id:
            ctx["parent_run_id"] = parent_run_id
            ctx["parent_task_id"] = str(ctx.get("task_id") or parent_run_id)
        orchestrator = AgentOrchestrator()
        run = orchestrator.start_run_from_plan(
            user_id=str(user_id),
            message=str(task),
            plan=plan,
            runtime_context=ctx,
            auto_execute=True,
        )
        run_context = run.metadata.get("runtime_context") or {}
        if (
            str(run.user_id) != str(user_id)
            or str(run_context.get("tenant_id") or "") != str(ctx["tenant_id"])
            or str(run_context.get("mod_id") or "") != str(ctx.get("mod_id") or "")
        ):
            return _collaboration_failure(
                employee_id, "employee_collaboration_scope_changed", "协作回执不属于当前授权范围"
            )
        if parent_run_id and not orchestrator.attach_child_run(parent_run_id, run):
            return {
                **_collaboration_failure(
                    employee_id,
                    "employee_child_receipt_unbound",
                    "协作回执未能绑定原父任务，须核对后恢复；未放行下游",
                ),
                "agent_run_id": run.run_id,
                "status": "recovering",
                "requires_reconciliation": True,
                "retryable": False,
            }
        return _project_collaboration_result(employee_id, plan, run)


def _project_collaboration_result(employee_id: str, plan: PlanGraph, run: Any) -> dict[str, Any]:
    """The original AgentRun steps, not a group status or model text, decide completion."""
    from app.domain.task_lifecycle.results import (
        execution_result_error,
        execution_result_pending_state,
    )

    expected = {node.node_id: node for node in plan.nodes}
    seen: set[str] = set()
    exact = run.plan_id == plan.plan_id and len(run.steps) == len(expected)
    node_results = []
    outputs = (run.final_output or {}).get("node_outputs")
    outputs = outputs if isinstance(outputs, dict) else {}
    for step in run.steps:
        node = expected.get(step.node_id)
        bound = (
            node is not None
            and step.node_id not in seen
            and step.tool_id == node.tool_id
            and step.action == node.action
            and list(step.depends_on) == list(node.depends_on)
            and step.params.get("employee_id") == node.params.get("employee_id")
        )
        exact = exact and bound
        seen.add(step.node_id)
        output = step.output
        published = outputs.get(step.node_id)
        # AgentOrchestrator unwraps a business_outcome when collecting graph results.
        outcome = output.get("business_outcome") if isinstance(output, dict) else None
        projected = outcome if isinstance(outcome, dict) else output
        completed = bool(
            bound
            and step.status == "completed"
            and isinstance(output, dict)
            and isinstance(published, dict)
            and projected == published
            and all(
                receipt.get("employee_id", step.node_id) == step.node_id
                for receipt in (output, published)
            )
            and not execution_result_error(output)
            and not execution_result_pending_state(output)
            and not execution_result_error(published)
            and not execution_result_pending_state(published)
        )
        node_results.append(
            {
                "node_id": step.node_id,
                "step_id": step.step_id,
                "status": step.status,
                "success": completed,
                "tool_id": step.tool_id,
                "error": step.error,
            }
        )
    success = bool(
        run.status == "completed"
        and exact
        and set(expected) == seen == set(outputs)
        and node_results
        and all(row["success"] for row in node_results)
    )
    result = {
        "skipped": False,
        "employee_id": employee_id,
        "plan_id": run.plan_id,
        "agent_run_id": run.run_id,
        "status": run.status if success or run.status != "completed" else "incomplete",
        "success": success,
        # This is a context execution receipt, not independent business acceptance.
        "validation_scope": "agent_run_execution_receipt",
        "independent_verified": False,
        "message": run.error
        or (
            str((run.final_output or {}).get("message") or run.status)
            if success
            else "协作节点未全部完成或回执不一致，未放行下游"
        ),
        "node_outputs": outputs if success else {},
        "node_results": node_results,
    }
    if not success:
        result["error_code"] = "employee_collaboration_incomplete"
    return result


__all__ = [
    "CollaborationPlanError",
    "EmployeeOrchestrator",
    "build_global_collaboration_graph",
]
