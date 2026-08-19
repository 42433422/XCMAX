# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.ai_chat_app_service')

class _AIChatApplicationServicePart03Mixin:

    @staticmethod
    def _iter_agentic_artifact_payloads(output: dict[str, _facade().Any]) -> list[dict[str, _facade().Any]]:
        if not isinstance(output, dict):
            return []
        artifacts = output.get('artifacts')
        if artifacts is None:
            artifacts = output.get('artifact')
        if isinstance(artifacts, dict):
            return [artifacts]
        if isinstance(artifacts, list):
            return [item for item in artifacts if isinstance(item, dict)]
        return []

    @staticmethod
    def _agent_plan_can_auto_execute(plan) -> bool:
        nodes = getattr(plan, 'nodes', None)
        if not isinstance(nodes, (list, tuple)) or not nodes:
            return False
        try:
            from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        except _facade().RECOVERABLE_ERRORS:
            return False
        for node in nodes:
            spec = get_tool_action_spec(getattr(node, 'tool_id', ''), getattr(node, 'action', ''))
            risk = str(getattr(spec, 'risk', '') or getattr(node, 'risk', '') or '').lower()
            idempotent = bool(getattr(spec, 'idempotent', getattr(node, 'idempotent', False)))
            if risk != 'low' or not idempotent:
                return False
        return True

    def _dispatch_workflow_tool(self, tool_id: str, action: str, params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        try:
            from app.application.facades.tools_facade import execute_registered_workflow_tool
            return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.error('workflow 工具调度失败 tool=%s action=%s err=%s', tool_id, action, err, exc_info=True)
            return {'success': False, 'message': str(err)}

    def _hydrate_pending_workflow(self, user_id: str) -> bool:
        """从 DB 载入用户最近的可续跑计划并水合到内存待确认槽。

        配合 ``WorkflowPlanStore`` 落库的计划，实现进程重启/换会话后仍能恢复长任务。
        水合成 ``kind="workflow"`` 的待确认记录，进入通用确认分支并用 ``resume`` 续跑。
        返回是否成功水合。
        """
        try:
            from app.application.workflow.plan_store import WorkflowPlanStore
            from app.application.workflow.types import plan_from_dict
            active = WorkflowPlanStore().list_active(user_id, limit=1)
            if not active:
                return False
            plan = plan_from_dict(active[0].get('plan') or {})
            if plan is None or not plan.nodes:
                return False
            self._pending_workflows[user_id] = {'plan': plan, 'runtime_context': dict(active[0].get('runtime_context') or {}), 'pending_id': _facade().uuid.uuid4().hex, 'thinking_steps': '', 'kind': 'workflow', 'agent_run_id': '', 'approval_required': False, 'approval_nodes': [], 'hydrated_from_db': True}
            return True
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug('DB 待续跑计划水合失败 user_id=%s', user_id)
            return False

    def _persist_plan_state(self, plan, runtime_context: dict[str, _facade().Any] | None, status: str, message: str | None=None) -> None:
        """把动态工作流计划（含 runtime_context）落库，供跨会话续跑。

        从 ``runtime_context`` 提取 ``user_id``/``session_id``；保存失败仅告警，不阻断主流程。
        """
        try:
            from app.application.workflow.plan_store import WorkflowPlanStore
            rc = dict(runtime_context or {})
            user_id = str(rc.get('user_id') or '').strip() or None
            session_id = str(rc.get('session_id') or rc.get('conversation_id') or '').strip() or None
            WorkflowPlanStore().save(plan=plan, runtime_context=rc, status=status, user_id=user_id, session_id=session_id, message=message)
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.warning('计划持久化失败 plan_id=%s status=%s', getattr(plan, 'plan_id', '?'), status)

    def _run_workflow_with_state_updates(self, *, plan, runtime_context: dict[str, _facade().Any], max_retries: int=1, resume: bool=False, **kwargs: _facade().Any) -> tuple[_facade().Any, list[dict[str, _facade().Any]]]:
        """运行工作流引擎，并收集每步节点完成后的 ``state.update`` 事件。

        ``resume=True`` 时从该计划在 DB 中的最新 checkpoint 断点续跑（不重复执行已完成节点），
        用于跨会话/中断恢复的长任务；返回 ``(run_result, state_updates)``。
        """
        state_updates: list[dict[str, _facade().Any]] = []

        def record_state_event(event: dict[str, _facade().Any]) -> None:
            state_updates.append(event)
        checkpointer = getattr(self, 'workflow_checkpointer', None)
        self._persist_plan_state(plan, runtime_context, status='running')
        if resume and checkpointer is not None:
            latest = checkpointer.latest_checkpoint(plan.plan_id)
            if latest is not None:
                run_result = self.workflow_engine.resume_run(plan, latest['checkpoint_id'], checkpointer=checkpointer, max_retries=max_retries)
            else:
                run_result = self.workflow_engine.run(plan=plan, runtime_context=runtime_context, max_retries=max_retries, state_event_callback=record_state_event, checkpointer=checkpointer, **kwargs)
        else:
            run_result = self.workflow_engine.run(plan=plan, runtime_context=runtime_context, max_retries=max_retries, state_event_callback=record_state_event, checkpointer=checkpointer, **kwargs)
        self._persist_plan_state(plan, runtime_context, status='succeeded' if run_result.success else 'failed', message=str(run_result.message or ''))
        return (run_result, state_updates)

    def _sweep_expired_clarifications(self) -> list[str]:
        """扫描并移除过期的"澄清待确认"记录（TTL 防堆积）。"""
        from app.application.workflow.clarification_node import sweep_expired
        return sweep_expired(self._pending_workflows)

    def _open_clarification_gate(self, *, user_id: str, plan, tool_registry, runtime_context: dict[str, _facade().Any], thinking_steps: str, message: str) -> dict[str, _facade().Any] | None:
        """写/高风险操作参数缺失或多候选歧义时：插入反问节点 → 执行暂停 → 记录待确认。

        返回澄清响应；无需澄清则返回 None（继续正常流程）。
        """
        from app.application.workflow.clarification_node import build_clarify_node, insert_clarify_node, make_pending_entry, needs_clarification
        clarify_items = needs_clarification(plan, tool_registry)
        if not clarify_items:
            return None
        item = clarify_items[0]
        target = next((n for n in plan.nodes if n.node_id == item['node_id']), None)
        if target is None:
            return None
        clarify_node = build_clarify_node(item.get('question') or '请确认目标后再执行写操作。', ambient={'target_node_id': target.node_id, 'answer_key': item.get('field') or 'confirmed'})
        insert_clarify_node(plan, clarify_node)
        runtime_context['_clarify_node_id'] = clarify_node.node_id
        self.workflow_engine.run(plan=plan, runtime_context=runtime_context, max_retries=1, checkpointer=self.workflow_checkpointer)
        self._pending_workflows[user_id] = make_pending_entry(plan=plan, runtime_context=runtime_context, thinking_steps=thinking_steps, clarification=item, clarify_node_id=clarify_node.node_id, target_node_id=target.node_id)
        self._persist_plan_state(plan, runtime_context, status='pending_awaiting')
        question = item.get('question') or '请确认目标后再执行写操作。'
        clarify_inner = {'plan_id': plan.plan_id, 'intent': plan.intent, 'requires_confirmation': True, 'reason': item.get('reason'), 'field': item.get('field'), 'candidates': item.get('candidates') or [], 'missing_fields': item.get('missing_fields') or [], 'target_node_id': target.node_id, 'ttl_seconds': self._pending_workflows[user_id]['ttl_seconds']}
        return {'success': True, 'message': '需要澄清', 'response': question, 'data': {'text': question, 'action': 'clarification_required', 'data': clarify_inner}}

    def _continue_after_clarification(self, user_id: str, pending: dict[str, _facade().Any], message: str) -> dict[str, _facade().Any] | None:
        """处理澄清待确认的回复：取消 / 解析唯一目标后继续执行。

        已处理（取消或继续执行）返回响应；无法唯一确定目标返回 None（保留 pending 继续追问）。
        """
        text = str(message or '').strip()
        cancel_words = {'取消', '否', '不要', '停止', 'no'}
        if text.lower() in cancel_words or text in cancel_words:
            self._pending_workflows.pop(user_id, None)
            return {'success': True, 'message': '处理完成', 'response': '已取消本次待澄清操作。', 'data': {'text': '已取消本次待澄清操作。', 'action': 'workflow_cancelled', 'data': {}}}
        from app.application.workflow.clarification_node import resolve_confirmed_target
        plan = _facade().cast('PlanGraph | None', pending.get('plan'))
        if plan is None:
            self._pending_workflows.pop(user_id, None)
            return None
        runtime_ctx = dict(pending.get('runtime_context') or {})
        item = pending.get('clarification') or {}
        clarify_node_id = pending.get('clarify_node_id')
        target_node_id = pending.get('target_node_id')
        target = next((n for n in plan.nodes if n.node_id == target_node_id), None)
        if target is None:
            self._pending_workflows.pop(user_id, None)
            return None
        candidates = item.get('candidates') or []
        confirmed = resolve_confirmed_target(text, candidates)
        if confirmed is None and target.tool_id == 'business_db' and (not candidates):
            from app.services.tools_workflow_registered import prepare_business_db_write_target
            entity = str(target.params.get('entity') or '')
            selector: dict[str, _facade().Any]
            if text.isdigit():
                selector = {'id': int(text)}
            else:
                natural_fields = {'customers': 'customer_name', 'products': 'product_name', 'materials': 'material_name'}
                natural_field = natural_fields.get(entity)
                selector = {natural_field: text} if natural_field else {}
            payload = dict(target.params.get('payload') or {})
            payload['selector'] = selector
            resolved = prepare_business_db_write_target(entity, str(target.params.get('operation') or ''), payload)
            if resolved.get('success'):
                target.params['payload'] = resolved['payload']
                confirmed = {'id': int(resolved['payload']['id'])}
        if confirmed is None:
            return None
        if target.tool_id == 'business_db':
            payload = dict(target.params.get('payload') or {})
            payload['id'] = int(confirmed['id'])
            target.params['payload'] = payload
        else:
            target.params.update(confirmed)
        target.params.pop('candidates', None)
        target.params.pop('_candidates', None)
        runtime_ctx['_clarify_answers'] = {clarify_node_id: {'confirmed': True, **confirmed}}
        self._pending_workflows.pop(user_id, None)
        (run_result, state_updates) = self._run_workflow_with_state_updates(plan=plan, runtime_context=runtime_ctx, max_retries=1, resume=True)
        return self._format_workflow_run_response(plan, run_result, thinking_steps=str(pending.get('thinking_steps') or ''), user_message=str(runtime_ctx.get('message') or ''), state_updates=state_updates)

    def _handle_confirmation_flow(self, user_id: str, message: str, file_context: dict[str, _facade().Any] | None) -> None:
        """处理确认流程"""
        if not file_context:
            return
        if message not in ('是', '好的', '确认', 'yes', 'ok', '好'):
            return
        saved_name = file_context.get('saved_name')
        unit_name = file_context.get('unit_name_guess') or file_context.get('unit_name', '')
        suggested_use = file_context.get('suggested_use', '')
        if saved_name and suggested_use == 'unit_products_db' and unit_name:
            self.ai_service.set_pending_confirmation(user_id, {'type': 'import_unit_products', 'tool_key': 'sqlite_import_unit_products', 'params': {'saved_name': saved_name, 'unit_name': unit_name}, 'description': f'导入 {unit_name} 的产品'})
            _facade().logger.info('用户 %s 确认导入文件：%s -> %s', user_id, saved_name, unit_name)

    def _build_response(self, ai_result: dict[str, _facade().Any], source: str | None, original_message: str='') -> dict[str, _facade().Any]:
        """构建响应数据"""
        response_data = {'success': True, 'message': '处理完成', 'data': {'text': ai_result.get('text', ''), 'action': ai_result.get('action', ''), 'data': ai_result.get('data', {}) or {}}}
        response_data['response'] = ai_result.get('text', '')
        action = ai_result.get('action')
        result_data = ai_result.get('data') or {}
        if action == 'tool_call' and result_data:
            response_data = self._handle_tool_call(response_data, ai_result, result_data, source, original_message)
        else:
            if action == 'followup':
                response_data['followup'] = result_data
            if action == 'auto_action' and result_data:
                response_data['autoAction'] = result_data
        return response_data

    def _handle_tool_call(self, response_data: dict[str, _facade().Any], ai_result: dict[str, _facade().Any], result_data: dict[str, _facade().Any], source: str | None, original_message: str='') -> dict[str, _facade().Any]:
        """处理工具调用响应"""
        tool_key = result_data.get('tool_key')
        parsed_params = result_data.get('params') or {}
        slots = result_data.get('slots', {})
        if not tool_key:
            response_data['response'] = ai_result.get('text', '')
            response_data['data']['data'] = result_data.get('data', {}) or {}
            return response_data
        if self._is_pro_source(source):
            response_data = self._execute_pro_mode_tools(response_data, tool_key, slots, parsed_params, ai_result, original_message)
        else:
            response_data = self._execute_normal_mode_tools(response_data, tool_key, parsed_params, ai_result, result_data)
        return response_data
