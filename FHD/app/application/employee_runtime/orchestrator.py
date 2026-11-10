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
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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
        order = self.graph.execution_order(eid)
        if len(order) <= 1:
            return None
        cycle = self.graph.detect_cycle()
        if cycle:
            logger.warning("collaboration cycle detected")

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
        plan = self.build_plan(employee_id, task, include_root=include_root)
        if plan is None:
            return {"skipped": True, "reason": "no depends_on", "employee_id": employee_id}

        ctx = dict(runtime_context or {})
        ctx.setdefault("task", task)
        ctx.setdefault("employee_id", employee_id)
        raw_user_id = ctx.get("user_id")
        try:
            user_id = int(raw_user_id)
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
        from app.application.agent_orchestrator.business_action_ledger import canonical_hash
        from app.application.agent_orchestrator import AgentOrchestrator

        stable_id = canonical_hash(
            {
                "employee_id": str(employee_id),
                "task": str(task),
                "dependencies": [node.node_id for node in plan.nodes],
                "user_id": user_id,
                "tenant_id": str(ctx.get("tenant_id") or ""),
                "session_id": str(ctx.get("session_id") or ctx.get("conversation_id") or ""),
                "task_id": str(ctx.get("task_id") or ""),
                "parent_run_id": str(ctx.get("run_id") or ctx.get("agent_run_id") or ""),
                "parent_step_id": str(ctx.get("step_id") or ""),
            }
        )
        plan.plan_id = f"emp-collab-{stable_id[:32]}"
        ctx["employee_collaboration_run"] = True
        parent_run_id = str(ctx.get("run_id") or "").strip()
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
        if parent_run_id:
            orchestrator.attach_child_run(parent_run_id, run)
        outputs = (run.final_output or {}).get("node_outputs")
        outputs = outputs if isinstance(outputs, dict) else {}
        return {
            "skipped": False,
            "employee_id": employee_id,
            "plan_id": run.plan_id,
            "agent_run_id": run.run_id,
            "status": run.status,
            "success": run.status == "completed",
            "message": run.error or str((run.final_output or {}).get("message") or run.status),
            "node_outputs": outputs,
            "node_results": [
                {
                    "node_id": nr.node_id,
                    "success": nr.status == "completed",
                    "tool_id": nr.tool_id,
                    "error": nr.error,
                }
                for nr in run.steps
            ],
        }


__all__ = [
    "EmployeeOrchestrator",
    "build_global_collaboration_graph",
]
