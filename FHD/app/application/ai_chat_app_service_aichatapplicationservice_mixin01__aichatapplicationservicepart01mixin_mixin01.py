# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat_app_service")


class __AIChatApplicationServicePart01MixinPart01Mixin:
    def __init__(
        self,
        workflow_runtime: _facade().WorkflowRuntime | None = None,
        workflow_checkpointer: _facade().CheckpointStore | None = None,
    ):
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
        normalized = str(source or "").strip().lower().replace("-", "_")
        return normalized in {"pro", "pro_mode", "promode", "professional", "xcagi_pro"}

    @staticmethod
    def _is_pure_casual_chat(text: str) -> bool:
        """纯闲聊判定：无任何业务/工具/实体语义，交给 legacy 单次 LLM。
        全局多步编排仅在槽位路由未命中时回落 legacy 聊天。
        """
        from app.application.normal_chat_dispatch import route_normal_mode_message

        return route_normal_mode_message(str(text or "")).get("intent") == "unknown"

    @staticmethod
    def _merge_tool_runtime_context(
        user_id: str, message: str, context: dict[str, _facade().Any] | None = None
    ) -> dict[str, _facade().Any]:
        runtime_ctx: dict[str, _facade().Any] = {"user_id": user_id, "message": message}
        _facade().AIChatWorkflowResponseMixin._attach_task_tenant(runtime_ctx)
        if isinstance(context, dict):
            for key in ("session_id", "conversation_id", "local_user_id", "actor_id"):
                if key in context and context[key]:
                    runtime_ctx[key] = str(context[key]).strip()
            for key in ("ui_surface", "intent_channel", "tool_execution_profile"):
                if key in context and context[key] is not None:
                    runtime_ctx[key] = context[key]
            for key in ("excel_analysis", "last_excel_analysis_context"):
                if key in context and isinstance(context[key], dict):
                    runtime_ctx[key] = context[key]
        return runtime_ctx

    def process_chat(
        self,
        user_id: str,
        message: str,
        context: dict[str, _facade().Any] | None = None,
        source: str | None = None,
        file_context: dict[str, _facade().Any] | None = None,
    ) -> dict[str, _facade().Any]:
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
            return {"success": False, "message": "消息内容不能为空"}
        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_received

            neuro_notify_chat_received(user_id, message, source)
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("neuro_notify_chat_received skipped", exc_info=True)
        ctx = context or {}
        ctx = self._inject_excel_vector_context(message=message, context=dict(ctx))
        chat_run = None
        chat_run_context: dict[str, _facade().Any] = {}

        def _finalize(resp: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
            if chat_run is not None:
                try:
                    from app.application.agent_orchestrator.chat_trace import (
                        finalize_legacy_chat_run,
                    )

                    resp = finalize_legacy_chat_run(
                        chat_run.run_id,
                        resp,
                        message=message,
                        runtime_context=chat_run_context,
                        user_id=user_id,
                        source=source,
                        channel="ai_chat_main_chain",
                    )
                except _facade().RECOVERABLE_ERRORS:
                    _facade().logger.debug("legacy chat AgentRun finalize skipped", exc_info=True)
            try:
                from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_completed

                neuro_notify_chat_completed(user_id, message, resp)
            except _facade().RECOVERABLE_ERRORS:
                _facade().logger.debug("neuro_notify_chat_completed skipped", exc_info=True)
            try:
                self._persist_chat_turn(user_id, message, ctx, resp)
            except _facade().RECOVERABLE_ERRORS as persist_err:
                _facade().logger.warning("会话落库失败（已返回对话结果）: %s", persist_err)
            try:
                self._persist_recallable_chat_turn(
                    user_id=user_id, message=message, source=source, context=ctx, response_data=resp
                )
            except _facade().RECOVERABLE_ERRORS as memory_err:
                _facade().logger.warning("跨会话记忆写入失败（已返回对话结果）: %s", memory_err)
            return resp

        from app.application.chat_business_safety import try_handle_business_chat_action

        business_payload = try_handle_business_chat_action(
            message, runtime_context=ctx, user_id=user_id
        )
        if business_payload is not None:
            return _finalize(business_payload)
        try:
            from app.application.workflow.chat_deterministic_fast_paths import (
                try_deterministic_chat_reply,
            )

            fhd_root = _facade().resolve_fhd_repo_root(anchor=_facade().Path(__file__).resolve())
            deterministic_reply = try_deterministic_chat_reply(
                message, runtime_context=ctx, workspace_root=str(fhd_root) if fhd_root else None
            )
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("deterministic chat fast path skipped", exc_info=True)
            deterministic_reply = None
        if deterministic_reply is not None:
            reply_text = str(
                deterministic_reply.get("response") or deterministic_reply.get("text") or ""
            ).strip()
            payload = {
                "success": True,
                "message": "处理完成",
                "response": reply_text,
                "data": {
                    "text": reply_text,
                    "action": "deterministic_reply",
                    "data": {
                        "intent": "deterministic_chat_reply",
                        "thinking_steps": deterministic_reply.get("thinking_steps"),
                    },
                },
            }
            return _finalize(
                self._attach_deterministic_workflow_trace(
                    payload,
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=ctx,
                    file_context=file_context or {},
                    intent="deterministic_chat_reply",
                )
            )
        self._handle_confirmation_flow(user_id, message, file_context)
        workflow_result = self._try_handle_dynamic_workflow(
            user_id=user_id,
            message=message,
            source=source,
            context=ctx,
            file_context=file_context or {},
        )
        if workflow_result is not None:
            return _finalize(workflow_result)
        multimodal_result = self._try_handle_multimodal_chat(
            user_id=user_id, message=message, source=source, context=ctx
        )
        if multimodal_result is not None:
            return _finalize(multimodal_result)
        chat_run_context = {
            **(ctx if isinstance(ctx, dict) else {}),
            "route": "ai_chat_main_chain",
            "source": str(source or "").strip(),
        }
        try:
            from app.application.agent_orchestrator.chat_trace import start_legacy_chat_run

            chat_run = start_legacy_chat_run(
                message=message,
                runtime_context=chat_run_context,
                user_id=user_id,
                source=source,
                channel="ai_chat_main_chain",
            )
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("legacy chat AgentRun pre-create skipped", exc_info=True)
        enriched_context = dict(ctx)
        if isinstance(file_context, dict):
            excel_file_path = file_context.get("file_path") or file_context.get(
                "original_file_path"
            )
            if excel_file_path:
                excel_analysis_obj = {"file_path": str(excel_file_path).strip()}
                sheet_name = file_context.get("sheet_name")
                if sheet_name:
                    excel_analysis_obj["sheet_name"] = str(sheet_name).strip()
                enriched_context["excel_analysis"] = excel_analysis_obj
        prepared_context = enriched_context
        loop = _facade().asyncio.new_event_loop()
        _facade().asyncio.set_event_loop(loop)
        try:
            ai_result = loop.run_until_complete(
                self.ai_service.chat(user_id, message, prepared_context, source=source)
            )
        except ConnectionError as conn_err:
            _facade().logger.error("AI 服务连接失败：%s", conn_err)
            loop.close()
            return _finalize(
                self._build_fallback_response(
                    message, "AI 服务连接失败，可能是网络问题或服务未启动"
                )
            )
        except TimeoutError as timeout_err:
            _facade().logger.error("AI 服务请求超时：%s", timeout_err)
            loop.close()
            return _finalize(self._build_fallback_response(message, "AI 服务响应超时，请稍后重试"))
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("AI 服务处理异常")
            loop.close()
            return _finalize(self._build_fallback_response(message, "AI 服务暂时不可用，请稍后重试"))
        finally:
            loop.close()
        _facade().logger.info(
            "用户 %s 消息：%s... -> %s", user_id, message[:50], ai_result.get("action", "unknown")
        )
        response_data = self._build_response(ai_result, source, message)
        return _finalize(response_data)

    @staticmethod
    def _persist_recallable_chat_turn(
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, _facade().Any],
        response_data: dict[str, _facade().Any],
    ) -> None:
        if context.get("memory_capture_enabled") is False or not response_data.get("success"):
            return
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return
        from app.utils.deployment import is_desktop_mode

        trusted_principal = context.get("_dataset_access_context_trusted") is True
        if not trusted_principal and (not is_desktop_mode()):
            return
        raw_inner = response_data.get("data")
        inner: dict[str, _facade().Any] = raw_inner if isinstance(raw_inner, dict) else {}
        action = str(response_data.get("action") or inner.get("action") or "").strip().lower()
        if action in {
            "error",
            "error_fallback",
            "fallback",
            "goodbye",
            "greeting",
            "help",
            "requires_token",
        }:
            return
        sensitive = _facade().re.compile(
            "(?:password|passcode|api[_ -]?key|access[_ -]?token|secret|验证码|密码|密钥)",
            _facade().re.I,
        )
        assistant_text = str(response_data.get("response") or "").strip()
        if not assistant_text:
            if not isinstance(inner, dict):
                inner = {}
            assistant_text = str(inner.get("text") or inner.get("message") or "").strip()
        if not assistant_text or sensitive.search(f"{message}\n{assistant_text}"):
            return
        from app.application.user_memory_vector_app_service import (
            get_user_memory_vector_ingest_app_service,
        )

        service = get_user_memory_vector_ingest_app_service()
        chunk = service.build_chat_turn_chunk(
            user_id=normalized_user_id,
            user_message=message,
            assistant_message=assistant_text,
            session_id=str(context.get("session_id") or context.get("conversation_id") or ""),
            source=str(source or "chat"),
        )
        service.ingest_chunks(normalized_user_id, [chunk])
        access_context = context.get("_dataset_access_context")
        if trusted_principal and isinstance(access_context, dict):
            from app.application.persy_memory_app_service import get_persy_memory_app_service

            get_persy_memory_app_service().capture_conversation_turn(
                access_context=access_context,
                user_message=message,
                assistant_message=assistant_text,
                session_id=str(context.get("session_id") or context.get("conversation_id") or ""),
                source=str(source or "chat"),
                scope="tenant"
                if str(context.get("persy_memory_scope") or "").strip().lower() == "tenant"
                else "user",
            )
