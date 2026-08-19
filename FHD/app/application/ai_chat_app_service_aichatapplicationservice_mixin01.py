# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.application.workflow.ports.checkpoint import CheckpointStore
    from app.application.workflow.ports.runtime import WorkflowRuntime

def _facade():
    return importlib.import_module('app.application.ai_chat_app_service')

class _AIChatApplicationServicePart01Mixin:

    def __init__(self, workflow_runtime: WorkflowRuntime | None=None, workflow_checkpointer: CheckpointStore | None=None):
        _self = _facade()
        self.ai_service = _facade().get_ai_conversation_service()
        self.workflow_planner = _self.LLMWorkflowPlanner()
        self.risk_gate = _self.HybridRiskGate()
        if workflow_runtime is None:
            from app.bootstrap import get_workflow_runtime
            workflow_runtime = get_workflow_runtime()
        self.workflow_engine = workflow_runtime
        if workflow_checkpointer is None:
            from app.bootstrap import get_workflow_checkpointer
            workflow_checkpointer = get_workflow_checkpointer()
        self.workflow_checkpointer = workflow_checkpointer
        self.approval_service = _self.get_approval_service()
        self._pending_workflows: dict[str, dict[str, _facade().Any]] = {}

    @staticmethod
    def _is_pro_source(source: str | None) -> bool:
        """兼容 pro 来源字段的多种写法（与 fastapi_routes.ai_chat._is_pro_source 对齐）。"""
        normalized = str(source or '').strip().lower().replace('-', '_')
        return normalized in {'pro', 'pro_mode', 'promode', 'professional', 'xcagi_pro'}

    @staticmethod
    def _is_pure_casual_chat(text: str) -> bool:
        """纯闲聊判定：无任何业务/工具/实体语义，交给 legacy 单次 LLM。
        全局多步编排仅在槽位路由未命中时回落 legacy 聊天。
        """
        from app.application.normal_chat_dispatch import route_normal_mode_message
        return route_normal_mode_message(str(text or '')).get('intent') == 'unknown'

    @staticmethod
    def _merge_tool_runtime_context(user_id: str, message: str, context: dict[str, _facade().Any] | None=None) -> dict[str, _facade().Any]:
        runtime_ctx: dict[str, _facade().Any] = {'user_id': user_id, 'message': message}
        _facade().AIChatWorkflowResponseMixin._attach_task_tenant(runtime_ctx)
        if isinstance(context, dict):
            for key in ('session_id', 'conversation_id', 'local_user_id', 'actor_id'):
                if key in context and context[key]:
                    runtime_ctx[key] = str(context[key]).strip()
            for key in ('ui_surface', 'intent_channel', 'tool_execution_profile'):
                if key in context and context[key] is not None:
                    runtime_ctx[key] = context[key]
            for key in ('excel_analysis', 'last_excel_analysis_context'):
                if key in context and isinstance(context[key], dict):
                    runtime_ctx[key] = context[key]
        return runtime_ctx

    def process_chat(self, user_id: str, message: str, context: dict[str, _facade().Any] | None=None, source: str | None=None, file_context: dict[str, _facade().Any] | None=None) -> dict[str, _facade().Any]:
        """
        处理聊天请求

        Args:
            user_id: 用户 ID
            message: 用户消息
            context: 额外上下文
            source: 来源标识（pro 表示专业模式）
            file_context: 文件上下文（用于确认流程）

        Returns:
            处理结果字典
        """
        if not message:
            return {'success': False, 'message': '消息内容不能为空'}
        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_received
            neuro_notify_chat_received(user_id, message, source)
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug('neuro_notify_chat_received skipped', exc_info=True)
        ctx = context or {}
        ctx = self._inject_excel_vector_context(message=message, context=dict(ctx))
        chat_run = None
        chat_run_context: dict[str, _facade().Any] = {}

        def _finalize(resp: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
            if chat_run is not None:
                try:
                    from app.application.agent_orchestrator.chat_trace import finalize_legacy_chat_run
                    resp = finalize_legacy_chat_run(chat_run.run_id, resp, message=message, runtime_context=chat_run_context, user_id=user_id, source=source, channel='ai_chat_main_chain')
                except _facade().RECOVERABLE_ERRORS:
                    _facade().logger.debug('legacy chat AgentRun finalize skipped', exc_info=True)
            try:
                from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_completed
                neuro_notify_chat_completed(user_id, message, resp)
            except _facade().RECOVERABLE_ERRORS:
                _facade().logger.debug('neuro_notify_chat_completed skipped', exc_info=True)
            try:
                self._persist_chat_turn(user_id, message, ctx, resp)
            except _facade().RECOVERABLE_ERRORS as persist_err:
                _facade().logger.warning('会话落库失败（已返回对话结果）: %s', persist_err)
            try:
                self._persist_recallable_chat_turn(user_id=user_id, message=message, source=source, context=ctx, response_data=resp)
            except _facade().RECOVERABLE_ERRORS as memory_err:
                _facade().logger.warning('跨会话记忆写入失败（已返回对话结果）: %s', memory_err)
            return resp
        from app.application.chat_business_safety import try_handle_business_chat_action
        business_payload = try_handle_business_chat_action(message, runtime_context=ctx, user_id=user_id)
        if business_payload is not None:
            return _finalize(business_payload)
        try:
            from app.application.workflow.chat_deterministic_fast_paths import try_deterministic_chat_reply
            fhd_root = _facade().resolve_fhd_repo_root(anchor=_facade().Path(__file__).resolve())
            deterministic_reply = try_deterministic_chat_reply(message, runtime_context=ctx, workspace_root=str(fhd_root) if fhd_root else None)
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug('deterministic chat fast path skipped', exc_info=True)
            deterministic_reply = None
        if deterministic_reply is not None:
            reply_text = str(deterministic_reply.get('response') or deterministic_reply.get('text') or '').strip()
            payload = {'success': True, 'message': '处理完成', 'response': reply_text, 'data': {'text': reply_text, 'action': 'deterministic_reply', 'data': {'intent': 'deterministic_chat_reply', 'thinking_steps': deterministic_reply.get('thinking_steps')}}}
            return _finalize(self._attach_deterministic_workflow_trace(payload, user_id=user_id, message=message, source=source, context=ctx, file_context=file_context or {}, intent='deterministic_chat_reply'))
        self._handle_confirmation_flow(user_id, message, file_context)
        workflow_result = self._try_handle_dynamic_workflow(user_id=user_id, message=message, source=source, context=ctx, file_context=file_context or {})
        if workflow_result is not None:
            return _finalize(workflow_result)
        multimodal_result = self._try_handle_multimodal_chat(user_id=user_id, message=message, source=source, context=ctx)
        if multimodal_result is not None:
            return _finalize(multimodal_result)
        chat_run_context = {**(ctx if isinstance(ctx, dict) else {}), 'route': 'ai_chat_main_chain', 'source': str(source or '').strip()}
        try:
            from app.application.agent_orchestrator.chat_trace import start_legacy_chat_run
            chat_run = start_legacy_chat_run(message=message, runtime_context=chat_run_context, user_id=user_id, source=source, channel='ai_chat_main_chain')
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug('legacy chat AgentRun pre-create skipped', exc_info=True)
        enriched_context = dict(ctx)
        if isinstance(file_context, dict):
            excel_file_path = file_context.get('file_path') or file_context.get('original_file_path')
            if excel_file_path:
                excel_analysis_obj = {'file_path': str(excel_file_path).strip()}
                sheet_name = file_context.get('sheet_name')
                if sheet_name:
                    excel_analysis_obj['sheet_name'] = str(sheet_name).strip()
                enriched_context['excel_analysis'] = excel_analysis_obj
        prepared_context = enriched_context
        loop = _facade().asyncio.new_event_loop()
        _facade().asyncio.set_event_loop(loop)
        try:
            ai_result = loop.run_until_complete(self.ai_service.chat(user_id, message, prepared_context, source=source))
        except ConnectionError as conn_err:
            _facade().logger.error('AI 服务连接失败：%s', conn_err)
            loop.close()
            return _finalize(self._build_fallback_response(message, 'AI 服务连接失败，可能是网络问题或服务未启动'))
        except TimeoutError as timeout_err:
            _facade().logger.error('AI 服务请求超时：%s', timeout_err)
            loop.close()
            return _finalize(self._build_fallback_response(message, 'AI 服务响应超时，请稍后重试'))
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.error('AI 服务处理异常：%s', e, exc_info=True)
            loop.close()
            error_msg = str(e)
            if 'api_key' in error_msg.lower() or 'apikey' in error_msg.lower():
                return _finalize(self._build_fallback_response(message, 'AI 服务 API Key 未配置或无效，请联系管理员'))
            elif 'connection' in error_msg.lower():
                return _finalize(self._build_fallback_response(message, '无法连接到 AI 服务，请检查网络设置'))
            else:
                return _finalize(self._build_fallback_response(message, f'AI 服务暂时不可用：{error_msg[:100]}'))
        finally:
            loop.close()
        _facade().logger.info('用户 %s 消息：%s... -> %s', user_id, message[:50], ai_result.get('action', 'unknown'))
        response_data = self._build_response(ai_result, source, message)
        return _finalize(response_data)

    @staticmethod
    def _persist_recallable_chat_turn(*, user_id: str, message: str, source: str | None, context: dict[str, _facade().Any], response_data: dict[str, _facade().Any]) -> None:
        if context.get('memory_capture_enabled') is False or not response_data.get('success'):
            return
        normalized_user_id = str(user_id or '').strip()
        if not normalized_user_id:
            return
        from app.utils.deployment import is_desktop_mode
        trusted_principal = context.get('_dataset_access_context_trusted') is True
        if not trusted_principal and (not is_desktop_mode()):
            return
        raw_inner = response_data.get('data')
        inner: dict[str, _facade().Any] = raw_inner if isinstance(raw_inner, dict) else {}
        action = str(response_data.get('action') or inner.get('action') or '').strip().lower()
        if action in {'error', 'error_fallback', 'fallback', 'goodbye', 'greeting', 'help', 'requires_token'}:
            return
        sensitive = _facade().re.compile('(?:password|passcode|api[_ -]?key|access[_ -]?token|secret|验证码|密码|密钥)', _facade().re.I)
        assistant_text = str(response_data.get('response') or '').strip()
        if not assistant_text:
            if not isinstance(inner, dict):
                inner = {}
            assistant_text = str(inner.get('text') or inner.get('message') or '').strip()
        if not assistant_text or sensitive.search(f'{message}\n{assistant_text}'):
            return
        from app.application.user_memory_vector_app_service import get_user_memory_vector_ingest_app_service
        service = get_user_memory_vector_ingest_app_service()
        chunk = service.build_chat_turn_chunk(user_id=normalized_user_id, user_message=message, assistant_message=assistant_text, session_id=str(context.get('session_id') or context.get('conversation_id') or ''), source=str(source or 'chat'))
        service.ingest_chunks(normalized_user_id, [chunk])
        access_context = context.get('_dataset_access_context')
        if trusted_principal and isinstance(access_context, dict):
            from app.application.persy_memory_app_service import get_persy_memory_app_service
            get_persy_memory_app_service().capture_conversation_turn(access_context=access_context, user_message=message, assistant_message=assistant_text, session_id=str(context.get('session_id') or context.get('conversation_id') or ''), source=str(source or 'chat'), scope='tenant' if str(context.get('persy_memory_scope') or '').strip().lower() == 'tenant' else 'user')

    def _persist_chat_turn(self, user_id: str, message: str, context: dict[str, _facade().Any], response_data: dict[str, _facade().Any]) -> None:
        """
        在请求携带 session_id / conversation_id 时，将会话与工具结果摘要写入 ai_conversations，
        便于审计与和出货/产品等业务联动检索。
        """
        session_id = str(context.get('session_id') or context.get('conversation_id') or '').strip()
        if not session_id:
            return
        from app.services import get_conversation_service
        inner = response_data.get('data') if isinstance(response_data.get('data'), dict) else {}
        if not isinstance(inner, dict):
            inner = {}
        inner_payload = inner.get('data') if isinstance(inner.get('data'), dict) else {}
        tool_call = response_data.get('toolCall') if isinstance(response_data.get('toolCall'), dict) else {}
        if not isinstance(inner_payload, dict):
            inner_payload = {}
        if not isinstance(tool_call, dict):
            tool_call = {}
        intent = str(inner_payload.get('intent') or inner_payload.get('tool_key') or tool_call.get('tool_id') or inner.get('action') or '').strip()
        summary = {'success': bool(response_data.get('success')), 'action': inner.get('action'), 'intent': intent, 'toolCall': tool_call or None, 'plan_id': inner_payload.get('plan_id'), 'document': (inner_payload.get('document') or {}).get('doc_name') if isinstance(inner_payload.get('document'), dict) else None, 'excel_import': inner_payload.get('result') if inner_payload.get('intent') == 'excel_import_to_db' else None}
        meta_user = _facade().json.dumps({'role_hint': 'user', 'summary': summary}, ensure_ascii=False)[:12000]
        meta_assistant = _facade().json.dumps({'role_hint': 'assistant', 'summary': summary}, ensure_ascii=False)[:12000]
        conv = get_conversation_service()
        conv.save_message(session_id=session_id, user_id=user_id, role='user', content=str(message)[:8000], intent=intent or 'chat', metadata=meta_user)
        if not isinstance(response_data, dict):
            response_data = {}
        reply = str(response_data.get('response') or inner.get('text') or '')[:8000]
        conv.save_message(session_id=session_id, user_id=user_id, role='assistant', content=reply, intent=intent or 'assistant_reply', metadata=meta_assistant)

    def _inject_excel_vector_context(self, message: str, context: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        """
        若请求携带 excel_index_id，则做一次语义检索并将结果写入 excel_vector_context。
        与 context 中已有的 excel_analysis（专用 extract-grid 等）可同时存在，二者一并进入下游提示词。

        注意：本方法在 process_chat 中会先于 _try_handle_dynamic_workflow 调用，以便规则导入捷径
        也能携带 excel_vector_context（供日志/后续扩展；当前列映射仍以 extract-grid 与字段索引为主）。
        若未传 excel_index_id / excel_vector_index_id，则不会检索（前端需在聊天 context 中带上建索引返回的 id）。
        """
        if not isinstance(context, dict):
            return {}
        excel_index_id = str(context.get('excel_index_id') or context.get('excel_vector_index_id') or '').strip()
        if not excel_index_id:
            return context
        top_k_raw = context.get('excel_top_k', 5)
        try:
            top_k = int(top_k_raw)
        except _facade().RECOVERABLE_ERRORS:
            top_k = 5
        try:
            from app.application import get_excel_vector_search_app_service
            search_service = get_excel_vector_search_app_service()
            result = search_service.query(index_id=excel_index_id, query_text=message, top_k=top_k)
            if result.get('success'):
                enriched = dict(context)
                enriched['excel_vector_context'] = {'index_id': excel_index_id, 'query': message, 'hits': result.get('hits', [])}
                return enriched
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.warning('注入 Excel 向量上下文失败: %s', err, exc_info=True)
        return context

    @staticmethod
    def _build_fallback_response(message: str, error_reason: str) -> dict[str, _facade().Any]:
        """
        构建 AI 服务不可用时的降级响应。

        当 AI 服务（LLM API、意图识别等）出现异常时，
        返回友好的错误提示，而不是让用户看到技术性错误信息。
        """
        text = (message or '').strip().lower()
        fallback_responses = {'greeting': '您好！我是 XCAGI 智能助手。😊\n\n⚠️ 当前 AI 服务暂时不可用，但我仍可以帮您：\n• 生成发货单\n• 查询产品库\n• 管理客户信息\n\n请尝试使用上述功能，或稍后再试。', 'default': f'抱歉，AI 助手暂时无法为您提供智能回复。\n\n原因：{error_reason}\n\n您可以：\n1. 稍后重试\n2. 使用其他功能（如产品查询、生成发货单）\n3. 联系管理员检查服务状态'}
        if any((k in text for k in ('你好', '您好', 'hi', 'hello', '嗨'))):
            response_text = fallback_responses['greeting']
        else:
            response_text = fallback_responses['default']
        return {'success': False, 'message': error_reason, 'response': response_text, 'data': {'text': response_text, 'action': 'error_fallback', 'data': {'error_reason': error_reason, 'original_message': message[:100], 'fallback_mode': True}}}

    @staticmethod
    def _is_number_text(value: str) -> bool:
        text = str(value or '').strip()
        if not text:
            return False
        try:
            float(text.replace(',', ''))
            return True
        except _facade().RECOVERABLE_ERRORS:
            return False

    @classmethod
    def _row_values_look_like_table_headers(cls, values: list[str]) -> bool:
        non_empty = [v for v in values if str(v or '').strip()]
        if len(non_empty) < 2:
            return False
        hits = sum((1 for v in non_empty if cls._HEADER_HINT_RE.search(str(v))))
        return hits >= 2 and hits >= max(2, len(non_empty) // 3)

    def _try_handle_multimodal_chat(self, *, user_id: str, message: str, source: str | None, context: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
        """多模态主链路收口：聊天上下文携带真实多模态 artifact 且多模态自治规划器能产出
        计划时，走真正的 orchestrator run（Dataset/RAG 入库+检索/确认写库），替代 legacy 兜底。

        护栏：无 artifact 信号键、或规划器返回 None 时不分流，保持 legacy 主链路不变；
        实测纯文本 / excel_vector / 纯 excel_analysis 上下文均不会分流（最热路径零影响）。
        """
        ctx = context if isinstance(context, dict) else {}
        signal_keys = ('multimodal_attachments', 'attachments', 'files', 'artifacts', 'ocr', 'ocr_result', 'file_analysis', 'generated_document', 'excel_analysis')
        if not any((ctx.get(key) for key in signal_keys)):
            return None
        try:
            from app.application.agent_orchestrator.multimodal_planner import build_multimodal_autonomous_plan
        except _facade().RECOVERABLE_ERRORS:
            return None
        runtime_ctx = dict(ctx)
        runtime_ctx.setdefault('message', message)
        try:
            plan = build_multimodal_autonomous_plan(user_id=user_id, message=message, runtime_context=runtime_ctx)
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug('multimodal autonomous plan probe skipped', exc_info=True)
            return None
        if plan is None:
            return None
        try:
            return self._start_deterministic_import_agent_run(user_id=user_id, message=message, source=source, context=ctx, file_context={}, plan=plan, thinking_steps='检测到多模态附件，已转入多模态自治工作流')
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception('multimodal autonomous run failed; falling back to legacy chat')
            return None
