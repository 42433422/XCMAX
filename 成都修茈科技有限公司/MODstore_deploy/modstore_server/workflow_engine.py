# mypy: disable-error-code="arg-type, assignment, call-overload"
# ruff: noqa: E402, F401
"""Skill 组（画布）执行引擎：执行、沙盒追踪、拓扑校验。

`workflow_id` 参数在存储层对应 ``workflows.id`` 行；产品侧同义称 **skill_group_id**
（见 ``workbench_api`` 的 artifact 别名）。本模块保留历史参数名以兼容外键与调用栈。
"""

from __future__ import annotations

import copy
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, cast

from sqlalchemy.orm import Session

from modstore_server.eventing.contracts import WORKFLOW_SANDBOX_COMPLETED
from modstore_server.eventing.events import new_event
from modstore_server.eventing.global_bus import neuro_bus
from modstore_server.models import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    get_session_factory,
)
from modstore_server.workflow_variables import eval_condition, resolve_value

logger = logging.getLogger(__name__)

# Hard cap for one ``_run_graph`` invocation. Protects against cycles or
# pathological condition expressions that would otherwise loop forever.
# Tuned generously (a complex sandboxed run shouldn't exceed ~200 steps).
MAX_WORKFLOW_STEPS = 1000

# A single node hit this many times in one run is treated as a soft cycle:
# the loop aborts and a warning is reported. Counts re-entries, not edge fires.
MAX_NODE_VISITS = 50


def _json_safe(value: Any, max_depth: int = 6, max_str: int = 8000) -> Any:
    """将上下文快照转为可 JSON 序列化的结构（沙盒报告用）。"""
    if max_depth <= 0:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > max_str:
            return value[: max_str - 1] + "…"
        return value
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 80:
                out["__truncated__"] = True
                break
            sk = str(k)[:128]
            out[sk] = _json_safe(v, max_depth - 1, max_str)
        return out
    if isinstance(value, (list, tuple)):
        lim = 40
        return [_json_safe(v, max_depth - 1, max_str) for v in value[:lim]] + (
            [f"<{len(value) - lim} more>"] if len(value) > lim else []
        )
    return str(type(value).__name__) + ":<non-serializable>"


from modstore_server.workflow_engine_workflowengine_mixin01 import (
    _WorkflowEnginePart01Mixin,
)
from modstore_server.workflow_engine_workflowengine_mixin02 import (
    _WorkflowEnginePart02Mixin,
)


class WorkflowEngine(_WorkflowEnginePart01Mixin, _WorkflowEnginePart02Mixin):
    """工作流引擎：支持生产执行与沙盒（全链路追踪、Mock 员工）。"""

    # ── New node executors ──────────────────────────────────────


def _topology_warnings(session: Session, workflow_id: int) -> List[str]:
    """可达性、孤立节点等（不改变执行语义，仅提示）。"""
    warnings: List[str] = []
    nodes = session.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()
    edges = session.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).all()
    if not nodes:
        return ["工作流没有任何节点"]
    node_ids = {int(str(n.id)) for n in nodes}
    start_ids = [int(str(n.id)) for n in nodes if n.node_type == "start"]
    end_ids = {int(str(n.id)) for n in nodes if n.node_type == "end"}
    if len(start_ids) != 1:
        return warnings
    adj: Dict[int, List[int]] = {nid: [] for nid in node_ids}
    for e in edges:
        if e.source_node_id in node_ids and e.target_node_id in node_ids:
            adj.setdefault(e.source_node_id, []).append(e.target_node_id)
    reachable: set[int] = set()
    stack = [start_ids[0]]
    while stack:
        u = stack.pop()
        if u in reachable:
            continue
        reachable.add(u)
        for v in adj.get(u, []):
            if v not in reachable:
                stack.append(v)
    unreached_end = end_ids - reachable
    if unreached_end:
        warnings.append("存在无法从开始节点到达的结束节点")
    for n in nodes:
        if n.id not in reachable and n.node_type != "start":
            warnings.append(f"孤立节点（从开始不可达）: {n.name} (id={n.id})")
            break

    # Static cycle detection (DFS three-coloring). Surface cycles as warnings
    # rather than errors — some users may intentionally loop with break
    # conditions; the runtime ``MAX_NODE_VISITS`` guard caps damage.
    cycle = _detect_cycle(adj, start_ids[0])
    if cycle:
        path = " -> ".join(_format_node(nid, nodes) for nid in cycle)
        warnings.append(f"工作流存在循环路径: {path}（运行时会触发死循环保护）")
    return warnings


def _detect_cycle(adj: Dict[int, List[int]], start: int) -> List[int]:
    """Return one cycle (as a list of node ids ending at the re-entry point)
    if the graph reachable from ``start`` contains any cycle, else ``[]``.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[int, int] = dict.fromkeys(adj, WHITE)
    parent: Dict[int, int] = {}
    cycle: List[int] = []

    def dfs(u: int) -> bool:
        color[u] = GRAY
        for v in adj.get(u, []):
            if v not in color:
                continue
            if color[v] == GRAY:
                # Found a back-edge u -> v; reconstruct cycle.
                node = u
                while node != v and node in parent:
                    cycle.append(node)
                    node = parent[node]
                cycle.append(v)
                cycle.reverse()
                cycle.append(v)
                return True
            if color[v] == WHITE:
                parent[v] = u
                if dfs(v):
                    return True
        color[u] = BLACK
        return False

    if start in color:
        dfs(start)
    return cycle


def _format_node(nid: int, nodes: List[WorkflowNode]) -> str:
    for n in nodes:
        if n.id == nid:
            return f"{n.name or '?'}#{nid}"
    return f"#{nid}"


class WorkflowValidator:
    """工作流静态校验。"""

    @staticmethod
    def validate_workflow(workflow: Workflow, session: Session) -> List[str]:
        errors: List[str] = []
        nodes = session.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).all()
        edges = session.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).all()
        start_nodes = [node for node in nodes if node.node_type == "start"]
        if len(start_nodes) != 1:
            errors.append("工作流必须有且只有一个开始节点")
        end_nodes = [node for node in nodes if node.node_type == "end"]
        if len(end_nodes) == 0:
            errors.append("工作流至少需要一个结束节点")
        for node in nodes:
            if node.node_type == "employee":
                config = json.loads(node.config) if node.config else {}
                if "employee_id" not in config:
                    errors.append(f"员工节点 {node.name} 缺少 employee_id 配置")
                if "task" not in config:
                    errors.append(f"员工节点 {node.name} 缺少 task 配置")
            elif node.node_type == "openapi_operation":
                try:
                    config = json.loads(node.config) if node.config else {}
                except (TypeError, ValueError):
                    config = {}
                if not config.get("connector_id"):
                    errors.append(f"OpenAPI 节点 {node.name} 缺少 connector_id 配置")
                if not config.get("operation_id"):
                    errors.append(f"OpenAPI 节点 {node.name} 缺少 operation_id 配置")
            elif node.node_type == "knowledge_search":
                try:
                    config = json.loads(node.config) if node.config else {}
                except (TypeError, ValueError):
                    config = {}
                has_query = bool(
                    str(config.get("query") or "").strip()
                    or str(config.get("query_template") or "").strip()
                )
                if not has_query:
                    errors.append(f"知识检索节点 {node.name} 缺少 query 或 query_template 配置")
                cids = config.get("collection_ids")
                if cids is not None and not isinstance(cids, list):
                    errors.append(f"知识检索节点 {node.name} 的 collection_ids 必须是数组")
            elif node.node_type == "variable_set":
                try:
                    config = json.loads(node.config) if node.config else {}
                except (TypeError, ValueError):
                    config = {}
                if not str(config.get("name") or "").strip():
                    errors.append(f"变量赋值节点 {node.name} 缺少 name 配置")
            elif node.node_type == "eskill":
                try:
                    config = json.loads(node.config) if node.config else {}
                except (TypeError, ValueError):
                    config = {}
                if not str(config.get("skill_id") or config.get("eskill_id") or "").strip():
                    errors.append(f"ESkill 节点 {node.name} 缺少 skill_id 配置")
            elif node.node_type in ("vibe_skill", "vibe_workflow"):
                try:
                    config = json.loads(node.config) if node.config else {}
                except (TypeError, ValueError):
                    config = {}
                if not str(config.get("brief") or "").strip():
                    errors.append(f"vibe-coding 节点 {node.name} 缺少 brief 配置")
            elif node.node_type == "cron_trigger":
                try:
                    config = json.loads(node.config) if node.config else {}
                except (TypeError, ValueError):
                    config = {}
                if not str(config.get("cron") or "").strip():
                    errors.append(f"定时触发器节点 {node.name} 缺少 cron 配置")
        node_ids = {node.id for node in nodes}
        for edge in edges:
            if edge.source_node_id not in node_ids:
                errors.append(f"边引用了不存在的源节点: {edge.source_node_id}")
            if edge.target_node_id not in node_ids:
                errors.append(f"边引用了不存在的目标节点: {edge.target_node_id}")
        return errors


def execute_workflow(
    workflow_id: int, input_data: Optional[Dict[str, Any]] = None, *, user_id: int = 0
) -> Dict[str, Any]:
    return cast(
        Dict[str, Any],
        workflow_engine.execute_workflow(workflow_id, input_data or {}, user_id=user_id),
    )


def validate_workflow(workflow_id: int) -> List[str]:
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            return [f"工作流不存在: {workflow_id}"]
        return WorkflowValidator.validate_workflow(workflow, session)


def run_workflow_sandbox(
    workflow_id: int,
    input_data: Dict[str, Any],
    *,
    mock_employees: bool = True,
    validate_only: bool = False,
    user_id: int = 0,
) -> Dict[str, Any]:
    SessionFactory = get_session_factory()
    t0 = time.perf_counter()
    with SessionFactory() as session:
        workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            return {
                "ok": False,
                "errors": [f"工作流不存在: {workflow_id}"],
                "warnings": [],
                "steps": [],
                "output": {},
                "validate_only": validate_only,
            }
        result = workflow_engine.run_sandbox(
            session,
            workflow,
            input_data or {},
            mock_employees=mock_employees,
            validate_only=validate_only,
            user_id=user_id,
        )
        duration_ms = round((time.perf_counter() - t0) * 1000, 3)
        status = "success" if result.get("ok") else "failed"
        neuro_bus.publish(
            new_event(
                WORKFLOW_SANDBOX_COMPLETED,
                producer="workflow",
                subject_id=str(workflow_id),
                payload={
                    "workflow_id": workflow_id,
                    "user_id": user_id,
                    "status": status,
                    "duration_ms": duration_ms,
                    "ok": bool(result.get("ok")),
                    "validate_only": validate_only,
                },
                idempotency_key=f"{WORKFLOW_SANDBOX_COMPLETED}:{workflow_id}:{duration_ms}",
            )
        )
        return cast(Dict[str, Any], result)


workflow_engine = WorkflowEngine()
