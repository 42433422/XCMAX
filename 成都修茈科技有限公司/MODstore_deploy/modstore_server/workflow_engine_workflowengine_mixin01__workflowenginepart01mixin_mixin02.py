# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workflow_engine")


class __WorkflowEnginePart01MixinPart02Mixin:
    def _execute_vibe_skill_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
        *,
        user_id: int = 0,
    ) -> _facade().Dict[str, _facade().Any]:
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
        _facade().logger.info("执行 vibe_skill 节点: %s", node.name)
        try:
            from modstore_server.integrations.vibe_eskill_adapter import (
                execute_vibe_code_kind,
            )
        except ImportError as exc:
            raise RuntimeError(f"integrations 未导入: {exc}") from exc
        brief = str(config.get("brief") or "").strip()
        if not brief:
            raise ValueError("vibe_skill 节点缺少 brief")
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        run_input_mapping = config.get("run_input_mapping") or {}
        run_input = (
            _facade().resolve_value(run_input_mapping, ctx)
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
        result.setdefault(
            "execution_time", _facade().datetime.now(_facade().timezone.utc).isoformat()
        )
        return result

    def _execute_vibe_workflow_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
        *,
        user_id: int = 0,
    ) -> _facade().Dict[str, _facade().Any]:
        """``vibe_workflow`` 节点:NL → VibeWorkflowGraph → execute。

        节点配置:
            brief: str (required)
            output_var: str (default "vibe_workflow_result")
            provider/model: str (可选覆盖)
        """
        _facade().logger.info("执行 vibe_workflow 节点: %s", node.name)
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
        result.setdefault(
            "execution_time", _facade().datetime.now(_facade().timezone.utc).isoformat()
        )
        return result

    def _execute_knowledge_search_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
        *,
        user_id: int = 0,
    ) -> _facade().Dict[str, _facade().Any]:
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
        _facade().logger.info("执行知识检索节点: %s", node.name)
        from modstore_server import rag_service

        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        raw_query = config.get("query_template") or config.get("query") or ""
        query_text = ""
        if isinstance(raw_query, str):
            try:
                query_text = str(_facade().resolve_value(raw_query, ctx) or "").strip()
            except RECOVERABLE_ERRORS:
                query_text = raw_query.strip()
        else:
            query_text = str(_facade().resolve_value(raw_query, ctx) or "")
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
        except RECOVERABLE_ERRORS:
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
        except RECOVERABLE_ERRORS as e:
            _facade().logger.warning("knowledge_search 节点执行失败: %s", e)
            return {
                out_var: {"items": [], "count": 0, "error": str(e)},
                "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
            }
        items = [c.to_dict() for c in chunks or []]
        return {
            out_var: {"items": items, "count": len(items), "query": query_text},
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_start_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        _facade().logger.info("执行开始节点")
        return {}

    def _execute_end_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        _facade().logger.info("执行结束节点")
        return {}

    def _execute_employee_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
        *,
        user_id: int = 0,
    ) -> _facade().Dict[str, _facade().Any]:
        _facade().logger.info("执行员工节点: %s", node.name)
        employee_id = config.get("employee_id")
        task = config.get("task")
        if not employee_id or not task:
            raise ValueError("员工节点缺少必要的配置: employee_id 和 task")
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        tmpl_ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        input_data = _facade().resolve_value(config.get("input_mapping") or data, tmpl_ctx)
        timeout_seconds = int(config.get("timeout_seconds") or 30)
        retry_count = int(config.get("retry_count") or 0)
        output_mapping = config.get("output_mapping") or {}
        last_err = None
        try:
            from modstore_server.services.employee import get_default_employee_client

            result = None
            for _ in range(max(1, retry_count + 1)):
                with _facade().ThreadPoolExecutor(max_workers=1) as ex:
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
                    except _facade().FutureTimeout as e:
                        last_err = e
                    except RECOVERABLE_ERRORS as e:
                        last_err = e
            if result is None:
                raise RuntimeError(f"employee node failed: {last_err}")
            mapped = _facade().resolve_value(
                output_mapping, {"result": result, "nodes": nodes_ctx, "global": data}
            )
            base = {
                "employee_result": result,
                "employee_id": employee_id,
                "task": task,
                "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
            }
            if isinstance(mapped, dict):
                base.update(mapped)
            return base
        except RECOVERABLE_ERRORS as e:
            _facade().logger.error("员工执行失败: %s", e)
            raise

    def _execute_eskill_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
        *,
        session: _facade().Session,
        workflow_id: int,
        user_id: int = 0,
    ) -> _facade().Dict[str, _facade().Any]:
        _facade().logger.info("执行 ESkill 节点: %s", node.name)
        skill_id = config.get("skill_id") or config.get("eskill_id")
        if not skill_id:
            raise ValueError("ESkill 节点缺少 skill_id 配置")
        try:
            eskill_id = int(skill_id)
        except RECOVERABLE_ERRORS as exc:
            raise ValueError("ESkill 节点 skill_id 必须是数字") from exc
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        tmpl_ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        input_data = _facade().resolve_value(config.get("input_mapping") or data, tmpl_ctx)
        if not isinstance(input_data, dict):
            input_data = {"value": input_data}
        logic_overrides: _facade().Dict[str, _facade().Any] = {}
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
        mapped = _facade().resolve_value(
            output_mapping,
            {
                "result": result,
                "output": runtime_output,
                "nodes": nodes_ctx,
                "global": data,
            },
        )
        base: _facade().Dict[str, _facade().Any] = {
            "eskill_result": result,
            "eskill_id": eskill_id,
            "eskill_stage": result.get("stage"),
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
        if output_var:
            base[output_var] = runtime_output
        if isinstance(mapped, dict):
            base.update(mapped)
        return base

    def _execute_openapi_operation_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
        *,
        user_id: int = 0,
    ) -> _facade().Dict[str, _facade().Any]:
        _facade().logger.info("执行 OpenAPI operation 节点: %s", node.name)
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
        params = _facade().resolve_value(config.get("input_mapping") or {}, ctx) or {}
        body = (
            _facade().resolve_value(config.get("body") or None, ctx)
            if config.get("body") is not None
            else None
        )
        headers = _facade().resolve_value(config.get("headers") or {}, ctx) or {}
        timeout_seconds = max(1, min(60, int(config.get("timeout_seconds") or 30)))
        retry_count = max(0, min(5, int(config.get("retry_count") or 0)))
        output_mapping = config.get("output_mapping") or {}
        try:
            from modstore_server.openapi_connector_runtime import (
                call_generated_operation,
            )
        except RECOVERABLE_ERRORS as exc:
            raise RuntimeError(f"openapi connector runtime 不可用: {exc}") from exc
        last_result: _facade().Dict[str, _facade().Any] = {}
        last_err: _facade().Optional[str] = None
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
        mapped = _facade().resolve_value(
            output_mapping, {"result": last_result, "nodes": nodes_ctx, "global": data}
        )
        base = {
            "openapi_result": last_result,
            "connector_id": connector_id_int,
            "operation_id": operation_id,
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
        if isinstance(mapped, dict):
            base.update(mapped)
        if last_err and (not last_result.get("ok")):
            base["error"] = last_err
        return base

    def _execute_condition_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        _facade().logger.info("执行条件节点: %s", node.name)
        return {}

    def _execute_webhook_trigger_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        """触发器节点：运行时由 HTTP/cron 调度；图内执行仅保证 payload 变量存在。"""
        _facade().logger.info("执行 Webhook 触发器节点（图内占位）: %s", node.name)
        payload_var = (
            str(config.get("payload_var") or "webhook_payload").strip() or "webhook_payload"
        )
        return {payload_var: data.get(payload_var, {})}

    def _execute_cron_trigger_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        """定时触发器：调度由 workflow_scheduler 负责；图内执行为空增量。"""
        _facade().logger.info("执行 Cron 触发器节点（图内占位）: %s", node.name)
        return {}
