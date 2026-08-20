# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workflow_engine")


class __WorkflowEnginePart01MixinPart01Mixin:
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
        input_data: _facade().Dict[str, _facade().Any] = None,
        *,
        user_id: int = 0,
    ) -> _facade().Dict[str, _facade().Any]:
        """执行工作流（仅运行业务图，不写入 workflow_executions；由 API 层落库）。"""
        SessionFactory = _facade().get_session_factory()
        with SessionFactory() as session:
            workflow = (
                session.query(_facade().Workflow)
                .filter(_facade().Workflow.id == workflow_id)
                .first()
            )
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
        session: _facade().Session,
        workflow: _facade().Workflow,
        input_data: _facade().Dict[str, _facade().Any],
        *,
        mock_employees: bool = True,
        validate_only: bool = False,
        user_id: int = 0,
    ) -> _facade().Dict[str, _facade().Any]:
        """
        沙盒运行：不写入执行表。
        - validate_only：只做静态校验 + 拓扑可达性，不执行节点逻辑。
        - mock_employees：员工节点不调用真实执行器，返回可预测的桩数据。
        """
        errors = _facade().WorkflowValidator.validate_workflow(workflow, session)
        topo_warnings = _facade()._topology_warnings(session, workflow.id)
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
            "output": _facade()._json_safe(output),
        }

    def _run_graph(
        self,
        session: _facade().Session,
        workflow: _facade().Workflow,
        input_data: _facade().Dict[str, _facade().Any],
        *,
        mock_employees: bool,
        collect_trace: bool,
        user_id: int = 0,
    ) -> _facade().Tuple[
        _facade().Dict[str, _facade().Any],
        _facade().List[_facade().Dict[str, _facade().Any]],
        _facade().List[str],
    ]:
        nodes = (
            session.query(_facade().WorkflowNode)
            .filter(_facade().WorkflowNode.workflow_id == workflow.id)
            .all()
        )
        edges = (
            session.query(_facade().WorkflowEdge)
            .filter(_facade().WorkflowEdge.workflow_id == workflow.id)
            .all()
        )
        node_map = {node.id: node for node in nodes}
        source_to_targets: _facade().Dict[int, _facade().List[_facade().WorkflowEdge]] = {}
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
        current_node: _facade().Optional[_facade().WorkflowNode] = start_node
        current_data = _facade().copy.deepcopy(input_data) if input_data else {}
        steps: _facade().List[_facade().Dict[str, _facade().Any]] = []
        run_warnings: _facade().List[str] = []
        order = 0
        total_steps = 0
        visit_count: _facade().Dict[int, int] = {}
        while current_node:
            total_steps += 1
            if total_steps > _facade().MAX_WORKFLOW_STEPS:
                run_warnings.append(
                    f"工作流步数超过上限 {_facade().MAX_WORKFLOW_STEPS}，疑似存在死循环，已强制中止"
                )
                _facade().logger.warning(
                    "workflow %s exceeded MAX_WORKFLOW_STEPS=%s; aborting at node %s",
                    workflow.id,
                    _facade().MAX_WORKFLOW_STEPS,
                    current_node.id,
                )
                break
            visit_count[current_node.id] = visit_count.get(current_node.id, 0) + 1
            if visit_count[current_node.id] > _facade().MAX_NODE_VISITS:
                run_warnings.append(
                    f"节点「{current_node.name}」被重入超过 {_facade().MAX_NODE_VISITS} 次，疑似循环边导致死循环，已强制中止"
                )
                _facade().logger.warning(
                    "workflow %s node %s revisited %s times; aborting (cycle)",
                    workflow.id,
                    current_node.id,
                    visit_count[current_node.id],
                )
                break
            t0 = _facade().time.perf_counter()
            data_before = _facade()._json_safe(current_data) if collect_trace else {}
            config = _facade().json.loads(current_node.config) if current_node.config else {}
            node_output = self._execute_node(
                current_node,
                current_data,
                config,
                session=session,
                workflow_id=workflow.id,
                mock_employee=mock_employees,
                user_id=user_id,
            )
            duration_ms = round((_facade().time.perf_counter() - t0) * 1000, 3)
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
                        "output_delta": _facade()._json_safe(node_output),
                        "mock_employee": bool(
                            mock_employees and current_node.node_type == "employee"
                        ),
                        "edge_taken": None,
                    }
                )
            current_data.update(node_output)
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
            next_node: _facade().Optional[_facade().WorkflowNode] = None
            edge_taken: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
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
        return (current_data, steps, run_warnings)

    def _execute_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
        *,
        session: _facade().Session,
        workflow_id: int,
        mock_employee: bool,
        user_id: int = 0,
    ) -> _facade().Dict[str, _facade().Any]:
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
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
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
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_openapi_operation_mock(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
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
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_knowledge_search_mock(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        out_var = str(config.get("output_var") or "knowledge")
        return {
            out_var: {
                "sandbox": True,
                "message": "沙盒 Mock：未真实查询向量库",
                "items": [],
                "count": 0,
            },
            "knowledge_search_collections": list(config.get("collection_ids") or []),
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_eskill_node_mock(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
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
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_vibe_node_mock(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
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
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
