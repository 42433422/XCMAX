# -*- coding: utf-8 -*-
"""员工协作编排：``collaboration.depends_on`` 本地依赖图执行。

把 manifest 声明的上游依赖建模为 WorkflowEngine DAG，复用 ``_run_batch`` 做
拓扑执行 + 死锁检测；上游 ``node_outputs`` 注入下游 ``EmployeeAgent.run`` 输入。

仅用于 FHD 本地/桌面单机场景，不回写 MODstore duty_graph。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.application.employee_runtime.loader import (
    list_installed_pack_records,
    parse_employee_config_v2,
)
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import PlanGraph, WorkflowNode
from app.domain.employee.collaboration_graph import CollaborationGraph
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _resolve_depends_on(manifest: dict[str, Any], config: dict[str, Any]) -> list[str]:
    deps: list[str] = []
    collab = config.get("collaboration") if isinstance(config.get("collaboration"), dict) else {}
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


def _employee_dispatcher(
    *,
    tool_id: str,
    action: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """WorkflowEngine 工具分发：tool_id = employee pack_id。"""
    from app.application.employee_runtime.agent import EmployeeAgent

    ctx = params.get("_runtime_context") if isinstance(params.get("_runtime_context"), dict) else {}
    node_outputs = ctx.get("node_outputs") if isinstance(ctx.get("node_outputs"), dict) else {}
    task = str(
        params.get("task")
        or params.get("user_request")
        or ctx.get("task")
        or f"协作步骤：{tool_id}"
    )
    input_data = {
        k: v for k, v in params.items() if k not in ("_runtime_context", "task", "user_request")
    }
    input_data["upstream_outputs"] = node_outputs
    input_data["skip_collaboration"] = True
    user_id = int(params.get("user_id") or ctx.get("user_id") or 0)
    workspace_root = params.get("workspace_root") or ctx.get("workspace_root")
    session_id = params.get("session_id") or ctx.get("session_id")
    try:
        result = EmployeeAgent(tool_id).run(
            task,
            input_data,
            user_id=user_id,
            workspace_root=workspace_root,
            session_id=session_id,
        )
        ok = bool(result.get("success"))
        return {
            "success": ok,
            "message": "员工协作步骤完成" if ok else "员工协作步骤失败",
            "employee_id": tool_id,
            "output": result,
        }
    except RECOVERABLE_ERRORS as exc:
        logger.exception("employee orchestrator step failed emp=%s", tool_id)
        return {"success": False, "error": str(exc)[:400], "employee_id": tool_id}


class EmployeeOrchestrator:
    """本地员工依赖图编排器。"""

    def __init__(self, graph: CollaborationGraph | None = None) -> None:
        self.graph = graph or build_global_collaboration_graph()
        self._engine = WorkflowEngine(tool_dispatcher=lambda **kw: _employee_dispatcher(**kw))

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
            logger.warning("collaboration cycle detected for %s: %s", eid, cycle)

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
                    tool_id=node_eid,
                    action="run",
                    params={
                        "task": (
                            task if include_root and node_eid == eid else f"上游协作：{node_eid}"
                        )
                    },
                    depends_on=direct_deps,
                    description=f"员工协作节点 {node_eid}",
                )
            )
        return PlanGraph(
            plan_id=f"emp-collab-{eid}-{uuid.uuid4().hex[:8]}",
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
        run = self._engine._run_batch(plan, ctx)
        return {
            "skipped": False,
            "employee_id": employee_id,
            "plan_id": plan.plan_id,
            "success": run.success,
            "message": run.message,
            "node_outputs": (run.final_context or {}).get("node_outputs") or {},
            "node_results": [
                {
                    "node_id": nr.node_id,
                    "success": nr.success,
                    "tool_id": nr.tool_id,
                    "error": nr.error,
                }
                for nr in (run.node_results or [])
            ],
        }


__all__ = [
    "EmployeeOrchestrator",
    "build_global_collaboration_graph",
]
