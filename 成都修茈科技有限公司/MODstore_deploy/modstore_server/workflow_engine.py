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
from typing import Any, Dict, List, Optional, Tuple

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


class WorkflowEngine:
    """工作流引擎：支持生产执行与沙盒（全链路追踪、Mock 员工）。"""

    def __init__(self):
        self.executors = {
            "start": self._execute_start_node,
            "end": self._execute_end_node,
            "employee": self._execute_employee_node,
            "condition": self._execute_condition_node,
            "openapi_operation": self._execute_openapi_operation_node,
            "knowledge_search": self._execute_knowledge_search_node,
            "webhook_trigger": self._execute_webhook_trigger_node,
            "cron_trigger": self._execute_cron_trigger_node,
            "variable_set": self._execute_variable_set_node,
            "eskill": self._execute_eskill_node,
            "vibe_skill": self._execute_vibe_skill_node,
            "vibe_workflow": self._execute_vibe_workflow_node,
            "http_request": self._execute_http_request_node,
            "code_execute": self._execute_code_execute_node,
            "data_transform": self._execute_data_transform_node,
            "loop": self._execute_loop_node,
            "parallel": self._execute_parallel_node,
            "sub_workflow": self._execute_sub_workflow_node,
        }

    def register_executor(self, node_type: str, executor):
        self.executors[node_type] = executor

    def execute_workflow(
        self,
        workflow_id: int,
        input_data: Dict[str, Any] = None,
        *,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        """执行工作流（仅运行业务图，不写入 workflow_executions；由 API 层落库）。"""
        SessionFactory = get_session_factory()
        with SessionFactory() as session:
            workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
            if not workflow:
                raise ValueError(f"工作流不存在: {workflow_id}")
            output, _steps, _warn = self._run_graph(
                session,
                workflow,
                input_data or {},
                mock_employees=False,
                collect_trace=False,
                user_id=user_id,
            )
            return output

    def run_sandbox(
        self,
        session: Session,
        workflow: Workflow,
        input_data: Dict[str, Any],
        *,
        mock_employees: bool = True,
        validate_only: bool = False,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        """
        沙盒运行：不写入执行表。
        - validate_only：只做静态校验 + 拓扑可达性，不执行节点逻辑。
        - mock_employees：员工节点不调用真实执行器，返回可预测的桩数据。
        """
        errors = WorkflowValidator.validate_workflow(workflow, session)
        topo_warnings = _topology_warnings(session, workflow.id)
        if validate_only:
            return {
                "ok": len(errors) == 0,
                "validate_only": True,
                "errors": errors,
                "warnings": topo_warnings,
                "steps": [],
                "output": {},
            }
        if errors:
            return {
                "ok": False,
                "validate_only": False,
                "errors": errors,
                "warnings": topo_warnings,
                "steps": [],
                "output": {},
            }
        output, steps, run_warn = self._run_graph(
            session,
            workflow,
            input_data or {},
            mock_employees=mock_employees,
            collect_trace=True,
            user_id=user_id,
        )
        return {
            "ok": True,
            "validate_only": False,
            "errors": [],
            "warnings": topo_warnings + run_warn,
            "steps": steps,
            "output": _json_safe(output),
        }

    def _run_graph(
        self,
        session: Session,
        workflow: Workflow,
        input_data: Dict[str, Any],
        *,
        mock_employees: bool,
        collect_trace: bool,
        user_id: int = 0,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[str]]:
        nodes = session.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).all()
        edges = session.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).all()
        node_map = {node.id: node for node in nodes}
        source_to_targets: Dict[int, List[WorkflowEdge]] = {}
        for edge in edges:
            source_to_targets.setdefault(edge.source_node_id, []).append(edge)
        for k in source_to_targets:
            source_to_targets[k].sort(key=lambda e: e.id)

        start_node = None
        for node in nodes:
            if node.node_type == "start":
                start_node = node
                break
        if not start_node:
            raise ValueError("工作流没有开始节点")

        current_node: Optional[WorkflowNode] = start_node
        current_data = copy.deepcopy(input_data) if input_data else {}
        steps: List[Dict[str, Any]] = []
        run_warnings: List[str] = []
        order = 0
        # Cycle / runaway protection: bound total steps and per-node revisits.
        # See module-level ``MAX_WORKFLOW_STEPS`` / ``MAX_NODE_VISITS``.
        total_steps = 0
        visit_count: Dict[int, int] = {}

        while current_node:
            total_steps += 1
            if total_steps > MAX_WORKFLOW_STEPS:
                run_warnings.append(
                    f"工作流步数超过上限 {MAX_WORKFLOW_STEPS}，疑似存在死循环，已强制中止"
                )
                logger.warning(
                    "workflow %s exceeded MAX_WORKFLOW_STEPS=%s; aborting at node %s",
                    workflow.id,
                    MAX_WORKFLOW_STEPS,
                    current_node.id,
                )
                break
            visit_count[current_node.id] = visit_count.get(current_node.id, 0) + 1
            if visit_count[current_node.id] > MAX_NODE_VISITS:
                run_warnings.append(
                    f"节点「{current_node.name}」被重入超过 {MAX_NODE_VISITS} 次，"
                    "疑似循环边导致死循环，已强制中止"
                )
                logger.warning(
                    "workflow %s node %s revisited %s times; aborting (cycle)",
                    workflow.id,
                    current_node.id,
                    visit_count[current_node.id],
                )
                break
            t0 = time.perf_counter()
            data_before = _json_safe(current_data) if collect_trace else {}
            config = json.loads(current_node.config) if current_node.config else {}

            node_output = self._execute_node(
                current_node,
                current_data,
                config,
                session=session,
                workflow_id=workflow.id,
                mock_employee=mock_employees,
                user_id=user_id,
            )
            duration_ms = round((time.perf_counter() - t0) * 1000, 3)

            if collect_trace:
                order += 1
                steps.append(
                    {
                        "order": order,
                        "node_id": current_node.id,
                        "node_type": current_node.node_type,
                        "node_name": current_node.name,
                        "duration_ms": duration_ms,
                        "input_snapshot": data_before,
                        "output_delta": _json_safe(node_output),
                        "mock_employee": bool(
                            mock_employees and current_node.node_type == "employee"
                        ),
                        "edge_taken": None,
                    }
                )

            current_data.update(node_output)

            # 支持模板如 {{nodes.prev.output.phone}}：保留扁平字段兼容，并挂载结构化 nodes.*
            node_blob = {
                "id": current_node.id,
                "name": current_node.name,
                "type": current_node.node_type,
                "output": node_output,
            }
            nb = current_data.get("nodes")
            if not isinstance(nb, dict):
                nb = {}
            nb[str(current_node.id)] = node_blob
            nm = (current_node.name or "").strip()
            if nm:
                nb[nm] = node_blob
            nb["prev"] = node_blob
            current_data["nodes"] = nb

            if current_node.node_type == "end":
                break

            next_edges = source_to_targets.get(current_node.id, [])
            if not next_edges:
                run_warnings.append(f"节点「{current_node.name}」无出边，流程提前结束")
                break

            next_node: Optional[WorkflowNode] = None
            edge_taken: Optional[Dict[str, Any]] = None
            ambiguous = [e for e in next_edges if not (e.condition or "").strip()]
            if len(ambiguous) > 1:
                run_warnings.append(
                    f"节点「{current_node.name}」存在多条无条件出边，已按边 id 最小优先（{ambiguous[0].id}）"
                )

            for edge in next_edges:
                cond_raw = (edge.condition or "").strip()
                if not cond_raw:
                    next_node = node_map.get(edge.target_node_id)
                    edge_taken = {
                        "edge_id": edge.id,
                        "condition": None,
                        "matched": True,
                    }
                    break
                matched = self._evaluate_condition(cond_raw, current_data)
                if collect_trace and steps:
                    steps[-1].setdefault("condition_branches", []).append(
                        {
                            "edge_id": edge.id,
                            "target_node_id": edge.target_node_id,
                            "condition": cond_raw,
                            "matched": matched,
                        }
                    )
                if matched:
                    next_node = node_map.get(edge.target_node_id)
                    edge_taken = {
                        "edge_id": edge.id,
                        "condition": cond_raw,
                        "matched": True,
                    }
                    break

            if collect_trace and steps:
                steps[-1]["edge_taken"] = edge_taken
            if next_node is None and next_edges:
                run_warnings.append(f"节点「{current_node.name}」无有向边条件命中，流程停止")
            current_node = next_node

        return current_data, steps, run_warnings

    def _execute_node(
        self,
        node: WorkflowNode,
        data: Dict[str, Any],
        config: Dict[str, Any],
        *,
        session: Session,
        workflow_id: int,
        mock_employee: bool,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        executor = self.executors.get(node.node_type)
        if not executor:
            raise ValueError(f"未知的节点类型: {node.node_type}")
        if node.node_type == "employee" and mock_employee:
            return self._execute_employee_node_mock(node, data, config)
        if node.node_type == "openapi_operation" and mock_employee:
            return self._execute_openapi_operation_mock(node, data, config)
        if node.node_type == "knowledge_search" and mock_employee:
            return self._execute_knowledge_search_mock(node, data, config)
        if node.node_type == "eskill" and mock_employee:
            return self._execute_eskill_node_mock(node, data, config)
        if node.node_type in ("vibe_skill", "vibe_workflow") and mock_employee:
            return self._execute_vibe_node_mock(node, data, config)
        if node.node_type == "http_request" and mock_employee:
            return self._execute_http_request_mock(node, data, config)
        if node.node_type == "code_execute" and mock_employee:
            return self._execute_code_execute_mock(node, data, config)
        if node.node_type == "data_transform" and mock_employee:
            return self._execute_data_transform_mock(node, data, config)
        if node.node_type == "loop" and mock_employee:
            return self._execute_loop_mock(node, data, config)
        if node.node_type == "parallel" and mock_employee:
            return self._execute_parallel_mock(node, data, config)
        if node.node_type == "sub_workflow" and mock_employee:
            return self._execute_sub_workflow_mock(node, data, config)
        if node.node_type in ("employee", "openapi_operation", "knowledge_search"):
            return executor(node, data, config, user_id=user_id)
        if node.node_type == "eskill":
            return executor(
                node,
                data,
                config,
                session=session,
                workflow_id=workflow_id,
                user_id=user_id,
            )
        if node.node_type in ("vibe_skill", "vibe_workflow"):
            return executor(node, data, config, user_id=user_id)
        return executor(node, data, config)

    def _execute_employee_node_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        employee_id = config.get("employee_id", "")
        task = config.get("task", "")
        return {
            "employee_result": {
                "sandbox": True,
                "message": "沙盒 Mock：未调用真实员工执行器",
                "employee_id": employee_id,
                "task": task,
                "echo_keys": list(data.keys())[:24],
            },
            "employee_id": employee_id,
            "task": task,
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_openapi_operation_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "openapi_result": {
                "sandbox": True,
                "message": "沙盒 Mock：未触发真实第三方 API 调用",
                "connector_id": config.get("connector_id"),
                "operation_id": config.get("operation_id"),
                "echo_keys": list(data.keys())[:24],
            },
            "connector_id": config.get("connector_id"),
            "operation_id": config.get("operation_id"),
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_knowledge_search_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        out_var = str(config.get("output_var") or "knowledge")
        return {
            out_var: {
                "sandbox": True,
                "message": "沙盒 Mock：未真实查询向量库",
                "items": [],
                "count": 0,
            },
            "knowledge_search_collections": list(config.get("collection_ids") or []),
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_eskill_node_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        out_var = str(config.get("output_var") or "eskill_result")
        return {
            out_var: {
                "sandbox": True,
                "message": "沙盒 Mock：未触发真实 ESkill 运行时",
                "skill_id": config.get("skill_id"),
                "task": config.get("task") or "",
                "echo_keys": list(data.keys())[:24],
            },
            "eskill_id": config.get("skill_id"),
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_vibe_node_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        out_var = str(
            config.get("output_var")
            or ("vibe_result" if node.node_type == "vibe_skill" else "vibe_workflow_result")
        )
        return {
            out_var: {
                "sandbox": True,
                "message": f"沙盒 Mock：未调用真实 vibe-coding（{node.node_type}）",
                "brief": str(config.get("brief") or "")[:240],
                "echo_keys": list(data.keys())[:24],
            },
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_vibe_skill_node(
        self,
        node: WorkflowNode,
        data: Dict[str, Any],
        config: Dict[str, Any],
        *,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        """``vibe_skill`` 节点:NL → CodeSkill → 用 input 跑一次。

        节点配置:
            brief: str (required)
            skill_id: str (optional, 同名复用 PatchLedger)
            mode: "brief_first"|"direct"
            run_immediately: bool (default True)
            run_input_mapping: dict (可选,把 data 抽子集)
            output_var: str (default "vibe_result")
            provider/model: str (可选覆盖)
        """
        logger.info("执行 vibe_skill 节点: %s", node.name)
        try:
            from modstore_server.integrations.vibe_eskill_adapter import execute_vibe_code_kind
        except ImportError as exc:
            raise RuntimeError(f"integrations 未导入: {exc}") from exc

        brief = str(config.get("brief") or "").strip()
        if not brief:
            raise ValueError("vibe_skill 节点缺少 brief")
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        run_input_mapping = config.get("run_input_mapping") or {}
        run_input = (
            resolve_value(run_input_mapping, ctx)
            if isinstance(run_input_mapping, dict) and run_input_mapping
            else dict(data)
        )
        if not isinstance(run_input, dict):
            run_input = {"value": run_input}
        logic = {
            "type": "vibe_code",
            "brief": brief,
            "skill_id": config.get("skill_id"),
            "mode": str(config.get("mode") or "brief_first"),
            "run_immediately": bool(config.get("run_immediately", True)),
            "output_var": str(config.get("output_var") or "vibe_result"),
            "provider": config.get("provider") or "",
            "model": config.get("model") or "",
        }
        result = execute_vibe_code_kind(logic, run_input, user_id=int(user_id or 0))
        if not result.get("ok") and result.get("error"):
            raise RuntimeError(result.get("error"))
        result.setdefault("execution_time", datetime.now(timezone.utc).isoformat())
        return result

    def _execute_vibe_workflow_node(
        self,
        node: WorkflowNode,
        data: Dict[str, Any],
        config: Dict[str, Any],
        *,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        """``vibe_workflow`` 节点:NL → VibeWorkflowGraph → execute。

        节点配置:
            brief: str (required)
            output_var: str (default "vibe_workflow_result")
            provider/model: str (可选覆盖)
        """
        logger.info("执行 vibe_workflow 节点: %s", node.name)
        try:
            from modstore_server.integrations.vibe_eskill_adapter import (
                execute_vibe_workflow_kind,
            )
        except ImportError as exc:
            raise RuntimeError(f"integrations 未导入: {exc}") from exc

        brief = str(config.get("brief") or "").strip()
        if not brief:
            raise ValueError("vibe_workflow 节点缺少 brief")
        logic = {
            "type": "vibe_workflow",
            "brief": brief,
            "output_var": str(config.get("output_var") or "vibe_workflow_result"),
            "provider": config.get("provider") or "",
            "model": config.get("model") or "",
        }
        result = execute_vibe_workflow_kind(logic, dict(data), user_id=int(user_id or 0))
        if not result.get("ok") and result.get("error"):
            raise RuntimeError(result.get("error"))
        result.setdefault("execution_time", datetime.now(timezone.utc).isoformat())
        return result

    def _execute_knowledge_search_node(
        self,
        node: WorkflowNode,
        data: Dict[str, Any],
        config: Dict[str, Any],
        *,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        """``knowledge_search`` 节点：跨多个集合做 RAG 检索，写入 ``output_var``。

        Config:
            - collection_ids: list[int]    显式指定要查询的集合（可见性仍受权限校验）
            - query_template: str          支持 ``${var}`` 模板，从 ``data`` 取变量
            - query: str                   query_template 不存在时的默认文本
            - top_k: int                   返回数量
            - min_score: float             1 - distance 最低分阈值
            - employee_id: str             带上某 employee 上下文（包含其拥有的集合）
            - workflow_id: int             带上 workflow 上下文
            - output_var: str              结果写入 data 的键名（默认 'knowledge'）
        """
        logger.info("执行知识检索节点: %s", node.name)
        from modstore_server import rag_service

        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        raw_query = config.get("query_template") or config.get("query") or ""
        query_text = ""
        if isinstance(raw_query, str):
            try:
                query_text = str(resolve_value(raw_query, ctx) or "").strip()
            except Exception:  # noqa: BLE001
                query_text = raw_query.strip()
        else:
            query_text = str(resolve_value(raw_query, ctx) or "")

        top_k = int(config.get("top_k") or 6)
        min_score = float(config.get("min_score") or 0.0)
        out_var = str(config.get("output_var") or "knowledge")
        collection_ids_raw = config.get("collection_ids") or []
        if not isinstance(collection_ids_raw, list):
            collection_ids_raw = [collection_ids_raw]
        collection_ids = [int(x) for x in collection_ids_raw if x is not None]

        employee_id = str(config.get("employee_id") or "") or None
        workflow_id_cfg = config.get("workflow_id")
        try:
            workflow_id_int = int(workflow_id_cfg) if workflow_id_cfg is not None else None
        except Exception:  # noqa: BLE001
            workflow_id_int = None

        async def _run():
            return await rag_service.retrieve(
                user_id=int(user_id or 0),
                query=query_text,
                employee_id=employee_id,
                workflow_id=workflow_id_int,
                extra_collection_ids=collection_ids or None,
                top_k=top_k,
                min_score=min_score,
            )

        try:
            from modstore_server.runtime_async import run_coro_sync

            chunks = run_coro_sync(_run())
        except Exception as e:  # noqa: BLE001
            logger.warning("knowledge_search 节点执行失败: %s", e)
            return {
                out_var: {"items": [], "count": 0, "error": str(e)},
                "execution_time": datetime.now(timezone.utc).isoformat(),
            }

        items = [c.to_dict() for c in (chunks or [])]
        return {
            out_var: {"items": items, "count": len(items), "query": query_text},
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_start_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("执行开始节点")
        return {}

    def _execute_end_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("执行结束节点")
        return {}

    def _execute_employee_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any], *, user_id: int = 0
    ) -> Dict[str, Any]:
        logger.info("执行员工节点: %s", node.name)
        employee_id = config.get("employee_id")
        task = config.get("task")
        if not employee_id or not task:
            raise ValueError("员工节点缺少必要的配置: employee_id 和 task")
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        tmpl_ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        input_data = resolve_value(config.get("input_mapping") or data, tmpl_ctx)
        timeout_seconds = int(config.get("timeout_seconds") or 30)
        retry_count = int(config.get("retry_count") or 0)
        output_mapping = config.get("output_mapping") or {}
        last_err = None
        try:
            from modstore_server.services.employee import get_default_employee_client

            result = None
            for _ in range(max(1, retry_count + 1)):
                with ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(
                        get_default_employee_client().execute_task,
                        employee_id=employee_id,
                        task=task,
                        input_data=input_data,
                        user_id=user_id,
                    )
                    try:
                        result = future.result(timeout=timeout_seconds)
                        break
                    except FutureTimeout as e:
                        last_err = e
                    except Exception as e:  # noqa: PERF203
                        last_err = e
            if result is None:
                raise RuntimeError(f"employee node failed: {last_err}")
            mapped = resolve_value(
                output_mapping, {"result": result, "nodes": nodes_ctx, "global": data}
            )
            base = {
                "employee_result": result,
                "employee_id": employee_id,
                "task": task,
                "execution_time": datetime.now(timezone.utc).isoformat(),
            }
            if isinstance(mapped, dict):
                base.update(mapped)
            return base
        except Exception as e:
            logger.error("员工执行失败: %s", e)
            raise

    def _execute_eskill_node(
        self,
        node: WorkflowNode,
        data: Dict[str, Any],
        config: Dict[str, Any],
        *,
        session: Session,
        workflow_id: int,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        logger.info("执行 ESkill 节点: %s", node.name)
        skill_id = config.get("skill_id") or config.get("eskill_id")
        if not skill_id:
            raise ValueError("ESkill 节点缺少 skill_id 配置")
        try:
            eskill_id = int(skill_id)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("ESkill 节点 skill_id 必须是数字") from exc

        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        tmpl_ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        input_data = resolve_value(config.get("input_mapping") or data, tmpl_ctx)
        if not isinstance(input_data, dict):
            input_data = {"value": input_data}
        logic_overrides: Dict[str, Any] = {}
        task = str(config.get("task") or "").strip()
        if task:
            logic_overrides["task_template"] = task
            logic_overrides["task"] = task
        output_var = str(config.get("output_var") or "").strip()
        if output_var:
            logic_overrides["output_var"] = output_var

        from modstore_server.eskill_runtime import default_eskill_runtime

        result = default_eskill_runtime.run(
            session,
            eskill_id=eskill_id,
            user_id=user_id,
            input_data=input_data,
            workflow_id=workflow_id,
            workflow_node_id=node.id,
            logic_overrides=logic_overrides,
            trigger_policy_override=config.get("trigger_policy") or {},
            quality_gate_override=config.get("quality_gate") or {},
            force_dynamic=bool(config.get("force_dynamic")),
            solidify=bool(config.get("solidify", True)),
        )
        runtime_output = result.get("output") if isinstance(result, dict) else {}
        if not isinstance(runtime_output, dict):
            runtime_output = {"value": runtime_output}

        output_mapping = config.get("output_mapping") or {}
        mapped = resolve_value(
            output_mapping,
            {"result": result, "output": runtime_output, "nodes": nodes_ctx, "global": data},
        )
        base: Dict[str, Any] = {
            "eskill_result": result,
            "eskill_id": eskill_id,
            "eskill_stage": result.get("stage"),
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }
        if output_var:
            base[output_var] = runtime_output
        if isinstance(mapped, dict):
            base.update(mapped)
        return base

    def _execute_openapi_operation_node(
        self,
        node: WorkflowNode,
        data: Dict[str, Any],
        config: Dict[str, Any],
        *,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        logger.info("执行 OpenAPI operation 节点: %s", node.name)
        connector_id = config.get("connector_id")
        operation_id = config.get("operation_id")
        if not connector_id or not operation_id:
            raise ValueError("openapi_operation 节点缺少 connector_id 或 operation_id")
        try:
            connector_id_int = int(connector_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"connector_id 必须为整数: {connector_id!r}") from exc
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        params = resolve_value(config.get("input_mapping") or {}, ctx) or {}
        body = (
            resolve_value(config.get("body") or None, ctx)
            if config.get("body") is not None
            else None
        )
        headers = resolve_value(config.get("headers") or {}, ctx) or {}
        timeout_seconds = max(1, min(60, int(config.get("timeout_seconds") or 30)))
        retry_count = max(0, min(5, int(config.get("retry_count") or 0)))
        output_mapping = config.get("output_mapping") or {}

        try:
            from modstore_server.openapi_connector_runtime import call_generated_operation
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"openapi connector runtime 不可用: {exc}") from exc

        last_result: Dict[str, Any] = {}
        last_err: Optional[str] = None
        for _ in range(retry_count + 1):
            last_result = call_generated_operation(
                connector_id=connector_id_int,
                user_id=int(user_id or 0),
                operation_id=str(operation_id),
                params=params if isinstance(params, dict) else {},
                body=body,
                headers=headers if isinstance(headers, dict) else {},
                timeout=float(timeout_seconds),
                source="workflow",
            )
            if last_result.get("ok"):
                last_err = None
                break
            last_err = str(last_result.get("error") or "")
        mapped = resolve_value(
            output_mapping, {"result": last_result, "nodes": nodes_ctx, "global": data}
        )
        base = {
            "openapi_result": last_result,
            "connector_id": connector_id_int,
            "operation_id": operation_id,
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }
        if isinstance(mapped, dict):
            base.update(mapped)
        if last_err and not last_result.get("ok"):
            base["error"] = last_err
        return base

    def _execute_condition_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("执行条件节点: %s", node.name)
        return {}

    def _execute_webhook_trigger_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """触发器节点：运行时由 HTTP/cron 调度；图内执行仅保证 payload 变量存在。"""
        logger.info("执行 Webhook 触发器节点（图内占位）: %s", node.name)
        payload_var = (
            str(config.get("payload_var") or "webhook_payload").strip() or "webhook_payload"
        )
        return {payload_var: data.get(payload_var, {})}

    def _execute_cron_trigger_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """定时触发器：调度由 workflow_scheduler 负责；图内执行为空增量。"""
        logger.info("执行 Cron 触发器节点（图内占位）: %s", node.name)
        return {}

    def _execute_variable_set_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """向上下文写入变量（支持 ``{{ var }}`` 模板）。"""
        logger.info("执行变量赋值节点: %s", node.name)
        name = str(config.get("name") or "").strip()
        if not name:
            raise ValueError("variable_set 节点缺少 name")
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        resolved = resolve_value(config.get("value"), ctx)
        return {name: resolved}

    def _evaluate_condition(self, condition: str, data: Dict[str, Any]) -> bool:
        return eval_condition(condition, data)

    # ── New node executors ──────────────────────────────────────

    def _execute_http_request_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        import httpx

        method = str(config.get("method") or "GET").upper()
        url_template = str(config.get("url") or "")
        if not url_template:
            raise ValueError("http_request 节点缺少 url 配置")
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        url = resolve_value(url_template, ctx)
        headers_raw = config.get("headers") or {}
        headers = (
            {k: str(resolve_value(v, ctx)) for k, v in headers_raw.items()}
            if isinstance(headers_raw, dict)
            else {}
        )
        body_raw = config.get("body")
        body = resolve_value(body_raw, ctx) if body_raw else None
        timeout_s = max(1, min(float(config.get("timeout") or 30), 120))
        retries = max(0, min(int(config.get("retries") or 0), 5))
        allow_http = [
            h.strip() for h in str(config.get("allow_http_domains") or "").split(",") if h.strip()
        ]
        if str(url).startswith("http://"):
            from urllib.parse import urlparse as _urlparse

            domain = _urlparse(str(url)).hostname or ""
            if not any(domain.endswith(d) for d in allow_http):
                url = str(url).replace("http://", "https://", 1)
        output_var = str(config.get("output_var") or f"http_response_{node.id}")
        last_exc = None
        for attempt in range(retries + 1):
            try:

                async def _do():
                    async with httpx.AsyncClient(timeout=timeout_s) as client:
                        r = await client.request(method, str(url), headers=headers, json=body)
                        r.raise_for_status()
                        return r

                import asyncio

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        resp = pool.submit(
                            lambda: httpx.request(
                                method, str(url), headers=headers, json=body, timeout=timeout_s
                            )
                        ).result(timeout_s + 5)
                else:
                    resp = loop.run_until_complete(_do())
                result_data = (
                    resp.json() if "json" in (resp.headers.get("content-type") or "") else resp.text
                )
                return {
                    output_var: result_data,
                    "http_status": resp.status_code if hasattr(resp, "status_code") else 200,
                    "execution_time": datetime.now(timezone.utc).isoformat(),
                }
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    import time as _t

                    _t.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"http_request 节点执行失败（重试 {retries} 次）: {last_exc}")

    def _execute_http_request_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        output_var = str(config.get("output_var") or f"http_response_{node.id}")
        return {
            output_var: {"sandbox": True, "message": "沙盒 Mock：未发送真实 HTTP 请求"},
            "http_status": 200,
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_code_execute_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        code = str(config.get("code") or "")
        if not code:
            raise ValueError("code_execute 节点缺少 code 配置")
        output_var = str(config.get("output_var") or "code_result")
        timeout_s = max(5, min(float(config.get("timeout") or 60), 300))
        local_ns: Dict[str, Any] = {
            "input": dict(data),
            "json": __import__("json"),
            "math": __import__("math"),
            "re": __import__("re"),
        }
        try:
            exec(
                compile(code, f"<workflow_code_{node.id}>", "exec"), {"__builtins__": {}}, local_ns
            )
            result = local_ns.get("result", local_ns.get("output", None))
            return {
                output_var: result,
                "execution_time": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            raise RuntimeError(f"code_execute 节点执行失败: {exc}") from exc

    def _execute_code_execute_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        output_var = str(config.get("output_var") or "code_result")
        return {
            output_var: {"sandbox": True, "message": "沙盒 Mock：未执行真实代码"},
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_data_transform_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        transforms = config.get("transforms") or []
        output_var = str(config.get("output_var") or "transform_result")
        result = dict(data)
        for t in transforms:
            t_type = str(t.get("type") or "")
            if t_type == "jsonpath":
                import jsonpath_ng.ext as jp

                expr = jp.parse(str(t.get("path") or "$"))
                matches = [m.value for m in expr.find(result)]
                result = matches[0] if len(matches) == 1 else matches
            elif t_type == "field_map":
                mapping = t.get("mapping") or {}
                result = {
                    str(k): result.get(str(v))
                    for k, v in mapping.items()
                    if result.get(str(v)) is not None
                }
            elif t_type == "type_cast":
                field = str(t.get("field") or "")
                target_type = str(t.get("cast_to") or "string")
                val = result.get(field)
                if val is not None:
                    if target_type == "string":
                        result[field] = str(val)
                    elif target_type == "number":
                        result[field] = float(val)
                    elif target_type == "integer":
                        result[field] = int(float(val))
                    elif target_type == "boolean":
                        result[field] = bool(val)
            elif t_type == "array_filter":
                field = str(t.get("field") or "")
                condition = str(t.get("condition") or "")
                arr = result.get(field)
                if isinstance(arr, list) and condition:
                    filtered = []
                    for item in arr:
                        if not isinstance(item, dict):
                            continue
                        try:
                            if eval_condition(condition, item):
                                filtered.append(item)
                        except Exception:
                            pass
                    result[field] = filtered
        if not isinstance(result, dict):
            result = {"value": result}
        return {
            output_var: result,
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_data_transform_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        output_var = str(config.get("output_var") or "transform_result")
        return {
            output_var: {"sandbox": True, "message": "沙盒 Mock：未执行真实数据转换"},
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_loop_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        loop_type = str(config.get("loop_type") or "for_each")
        max_iterations = max(1, min(int(config.get("max_iterations") or 100), 1000))
        output_var = str(config.get("output_var") or "loop_result")
        results: list = []
        if loop_type == "for_each":
            items_path = str(config.get("items_path") or "")
            nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
            ctx = {**data, "nodes": nodes_ctx, "global": data, "result": data}
            items = resolve_value(items_path, ctx) if items_path else data.get("items", [])
            if not isinstance(items, list):
                items = list(items) if items else []
            for idx, item in enumerate(items[:max_iterations]):
                results.append({"loop_index": idx, "loop_item": item})
        elif loop_type == "while":
            condition = str(config.get("condition") or "")
            iteration = 0
            while iteration < max_iterations:
                nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
                ctx = {
                    **data,
                    "nodes": nodes_ctx,
                    "global": data,
                    "result": data,
                    "loop_index": iteration,
                    "loop_item": results[-1] if results else None,
                }
                if condition and not eval_condition(condition, ctx):
                    break
                results.append({"loop_index": iteration, "loop_item": None})
                iteration += 1
        return {
            output_var: results,
            "loop_count": len(results),
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_loop_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        output_var = str(config.get("output_var") or "loop_result")
        return {
            output_var: [{"sandbox": True, "message": "沙盒 Mock：未执行真实循环"}],
            "loop_count": 1,
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_parallel_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        branches = config.get("branches") or []
        output_var = str(config.get("output_var") or "parallel_result")
        results: Dict[str, Any] = {}
        for branch in branches:
            branch_name = str(branch.get("name") or f"branch_{len(results)}")
            branch_type = str(branch.get("type") or "pass")
            if branch_type == "pass":
                results[branch_name] = {"status": "completed", "data": dict(data)}
            elif branch_type == "http_request":
                try:
                    sub_result = self._execute_http_request_node(node, data, branch)
                    results[branch_name] = {"status": "completed", "data": sub_result}
                except Exception as exc:
                    results[branch_name] = {"status": "failed", "error": str(exc)}
            elif branch_type == "data_transform":
                try:
                    sub_result = self._execute_data_transform_node(node, data, branch)
                    results[branch_name] = {"status": "completed", "data": sub_result}
                except Exception as exc:
                    results[branch_name] = {"status": "failed", "error": str(exc)}
            else:
                results[branch_name] = {
                    "status": "skipped",
                    "message": f"未知分支类型: {branch_type}",
                }
        return {
            output_var: results,
            "parallel_count": len(results),
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_parallel_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        output_var = str(config.get("output_var") or "parallel_result")
        return {
            output_var: {
                "sandbox": {"status": "completed", "message": "沙盒 Mock：未执行真实并行"}
            },
            "parallel_count": 1,
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_sub_workflow_node(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        sub_workflow_id = config.get("workflow_id")
        if not sub_workflow_id:
            raise ValueError("sub_workflow 节点缺少 workflow_id 配置")
        input_mapping = config.get("input_mapping") or {}
        output_var = str(config.get("output_var") or "sub_workflow_result")
        max_depth = max(1, min(int(config.get("max_depth") or 3), 5))
        current_depth = int(data.get("_sub_workflow_depth") or 0) + 1
        if current_depth > max_depth:
            raise RuntimeError(f"子工作流递归深度超过 {max_depth} 层，已中止")
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        sub_input = (
            resolve_value(input_mapping, ctx)
            if isinstance(input_mapping, dict) and input_mapping
            else dict(data)
        )
        if not isinstance(sub_input, dict):
            sub_input = {"value": sub_input}
        sub_input["_sub_workflow_depth"] = current_depth
        sub_result = execute_workflow(int(sub_workflow_id), sub_input)
        return {
            output_var: sub_result,
            "sub_workflow_id": int(sub_workflow_id),
            "sub_depth": current_depth,
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }

    def _execute_sub_workflow_mock(
        self, node: WorkflowNode, data: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        output_var = str(config.get("output_var") or "sub_workflow_result")
        return {
            output_var: {"sandbox": True, "message": "沙盒 Mock：未执行真实子工作流"},
            "sub_workflow_id": config.get("workflow_id"),
            "execution_time": datetime.now(timezone.utc).isoformat(),
        }


def _topology_warnings(session: Session, workflow_id: int) -> List[str]:
    """可达性、孤立节点等（不改变执行语义，仅提示）。"""
    warnings: List[str] = []
    nodes = session.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()
    edges = session.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).all()
    if not nodes:
        return ["工作流没有任何节点"]
    node_ids = {n.id for n in nodes}
    start_ids = [n.id for n in nodes if n.node_type == "start"]
    end_ids = {n.id for n in nodes if n.node_type == "end"}
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
    color: Dict[int, int] = {nid: WHITE for nid in adj}
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
    workflow_id: int, input_data: Dict[str, Any] = None, *, user_id: int = 0
) -> Dict[str, Any]:
    return workflow_engine.execute_workflow(workflow_id, input_data, user_id=user_id)


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
        return result


workflow_engine = WorkflowEngine()
