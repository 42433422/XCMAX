# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat_app_service")


class __AIChatApplicationServicePart01MixinPart02Mixin:
    def _persist_chat_turn(
        self,
        user_id: str,
        message: str,
        context: dict[str, _facade().Any],
        response_data: dict[str, _facade().Any],
    ) -> None:
        """
        在请求携带 session_id / conversation_id 时，将会话与工具结果摘要写入 ai_conversations，
        便于审计与和出货/产品等业务联动检索。
        """
        session_id = str(context.get("session_id") or context.get("conversation_id") or "").strip()
        if not session_id:
            return
        from app.services import get_conversation_service

        inner = response_data.get("data") if isinstance(response_data.get("data"), dict) else {}
        if not isinstance(inner, dict):
            inner = {}
        inner_payload = inner.get("data") if isinstance(inner.get("data"), dict) else {}
        tool_call = (
            response_data.get("toolCall") if isinstance(response_data.get("toolCall"), dict) else {}
        )
        if not isinstance(inner_payload, dict):
            inner_payload = {}
        if not isinstance(tool_call, dict):
            tool_call = {}
        reply = str(
            response_data.get("response")
            or inner.get("text")
            or (response_data.get("message") if not response_data.get("success") else "")
            or ""
        )[:8000]
        intent = str(
            inner_payload.get("intent")
            or inner_payload.get("tool_key")
            or tool_call.get("tool_id")
            or inner.get("action")
            or ""
        ).strip()
        summary = {
            "success": bool(response_data.get("success")),
            "action": inner.get("action"),
            "intent": intent,
            "toolCall": tool_call or None,
            "plan_id": inner_payload.get("plan_id"),
            "document": (inner_payload.get("document") or {}).get("doc_name")
            if isinstance(inner_payload.get("document"), dict)
            else None,
            "excel_import": inner_payload.get("result")
            if inner_payload.get("intent") == "excel_import_to_db"
            else None,
            "task_id": context.get("task_id"),
            "turn_id": context.get("turn_id"),
            "run_id": response_data.get("run_id")
            or response_data.get("agent_run_id")
            or inner.get("run_id")
            or inner.get("agent_run_id"),
        }
        ui_payload = {
            "thinkingSteps": inner_payload.get("thinking_steps")
            or inner.get("thinking_steps")
            or response_data.get("thinking_steps"),
            "todoSteps": inner_payload.get("todo"),
            "workflowAction": inner.get("action"),
            "nodeResults": inner_payload.get("node_results"),
            "approvalCard": inner_payload.get("approval_card"),
            "attachments": inner_payload.get("attachments"),
        }
        ui_payload = {
            key: value for key, value in ui_payload.items() if value not in (None, "", [])
        }
        harness_metadata = {
            "protocol": context.get("business_harness_protocol") or "xcagi.business-harness.v1",
            "task_id": context.get("task_id"),
            "turn_id": context.get("turn_id"),
            "conversation_id": session_id,
            "run_id": summary.get("run_id"),
        }
        turn_id = str(context.get("turn_id") or "").strip()
        user_fingerprint = (
            _facade()
            .uuid.uuid5(
                _facade().uuid.NAMESPACE_URL,
                str(message)[:8000],
            )
            .hex
        )
        assistant_fingerprint = (
            _facade()
            .uuid.uuid5(
                _facade().uuid.NAMESPACE_URL,
                reply,
            )
            .hex
        )
        user_idempotency_key = (
            f"xcagi.business-harness.v1:{turn_id}:user:{user_fingerprint}" if turn_id else ""
        )
        assistant_idempotency_key = (
            f"xcagi.business-harness.v1:{turn_id}:assistant:{assistant_fingerprint}"
            if turn_id
            else ""
        )
        meta_user = _facade().json.dumps(
            {
                "role_hint": "user",
                "summary": summary,
                "business_harness": harness_metadata,
            },
            ensure_ascii=False,
            default=str,
        )[:12000]
        meta_assistant = _facade().json.dumps(
            {
                "role_hint": "assistant",
                "summary": summary,
                "business_harness": harness_metadata,
                "ui": ui_payload,
            },
            ensure_ascii=False,
            default=str,
        )[:12000]
        conv = get_conversation_service()
        conv.save_message(
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=str(message)[:8000],
            intent=intent or "chat",
            metadata=meta_user,
            idempotency_key=user_idempotency_key,
        )
        if not isinstance(response_data, dict):
            response_data = {}
        conv.save_message(
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=reply,
            intent=intent or "assistant_reply",
            metadata=meta_assistant,
            idempotency_key=assistant_idempotency_key,
        )

    def _inject_excel_vector_context(
        self, message: str, context: dict[str, _facade().Any]
    ) -> dict[str, _facade().Any]:
        """
        若请求携带 excel_index_id，则做一次语义检索并将结果写入 excel_vector_context。
        与 context 中已有的 excel_analysis（专用 extract-grid 等）可同时存在，二者一并进入下游提示词。

        注意：本方法在 process_chat 中会先于 _try_handle_dynamic_workflow 调用，以便规则导入捷径
        也能携带 excel_vector_context（供日志/后续扩展；当前列映射仍以 extract-grid 与字段索引为主）。
        若未传 excel_index_id / excel_vector_index_id，则不会检索（前端需在聊天 context 中带上建索引返回的 id）。
        """
        if not isinstance(context, dict):
            return {}
        excel_index_id = str(
            context.get("excel_index_id") or context.get("excel_vector_index_id") or ""
        ).strip()
        if not excel_index_id:
            return context
        top_k_raw = context.get("excel_top_k", 5)
        try:
            top_k = int(top_k_raw)
        except _facade().RECOVERABLE_ERRORS:
            top_k = 5
        try:
            from app.application import get_excel_vector_search_app_service

            search_service = get_excel_vector_search_app_service()
            result = search_service.query(index_id=excel_index_id, query_text=message, top_k=top_k)
            if result.get("success"):
                enriched = dict(context)
                enriched["excel_vector_context"] = {
                    "index_id": excel_index_id,
                    "query": message,
                    "hits": result.get("hits", []),
                }
                return enriched
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.warning("注入 Excel 向量上下文失败: %s", err, exc_info=True)
        return context

    def _inject_wechat_contact_context(
        self, message: str, context: dict[str, _facade().Any]
    ) -> dict[str, _facade().Any]:
        """
        注入微信联系人情报（服务器侧微信同步基建 → 聊天智慧）。

        解析顺序：context.wechat_contact_key 显式指定 > 消息文本自动匹配已同步联系人名。
        命中时写入 ``wechat_contact_context``（由 PromptsMixin 渲染进 system prompt）；
        未命中时显式置 None，避免上一轮残留情报污染本轮（request_context 按 user 跨轮合并）。
        任何异常静默降级，不阻断聊天主链路。
        """
        if not isinstance(context, dict):
            return {}
        try:
            from app.application.wechat_chat_context import resolve_wechat_chat_context

            payload = resolve_wechat_chat_context(message, context)
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.warning("注入微信联系人情报失败: %s", err, exc_info=True)
            return context
        enriched = dict(context)
        enriched["wechat_contact_context"] = payload
        return enriched

    @staticmethod
    def _build_fallback_response(message: str, error_reason: str) -> dict[str, _facade().Any]:
        """
        构建 AI 服务不可用时的降级响应。

        当 AI 服务（LLM API、意图识别等）出现异常时，
        返回友好的错误提示，而不是让用户看到技术性错误信息。
        """
        text = (message or "").strip().lower()
        fallback_responses = {
            "greeting": "您好！我是 XCAGI 智能助手。😊\n\n⚠️ 当前 AI 服务暂时不可用，但我仍可以帮您：\n• 生成发货单\n• 查询产品库\n• 管理客户信息\n\n请尝试使用上述功能，或稍后再试。",
            "default": f"抱歉，AI 助手暂时无法为您提供智能回复。\n\n原因：{error_reason}\n\n您可以：\n1. 稍后重试\n2. 使用其他功能（如产品查询、生成发货单）\n3. 联系管理员检查服务状态",
        }
        if any(k in text for k in ("你好", "您好", "hi", "hello", "嗨")):
            response_text = fallback_responses["greeting"]
        else:
            response_text = fallback_responses["default"]
        return {
            "success": False,
            "message": error_reason,
            "response": response_text,
            "data": {
                "text": response_text,
                "action": "error_fallback",
                "data": {
                    "error_reason": error_reason,
                    "original_message": message[:100],
                    "fallback_mode": True,
                },
            },
        }

    @staticmethod
    def _is_number_text(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        try:
            float(text.replace(",", ""))
            return True
        except _facade().RECOVERABLE_ERRORS:
            return False

    @classmethod
    def _row_values_look_like_table_headers(cls, values: list[str]) -> bool:
        non_empty = [v for v in values if str(v or "").strip()]
        if len(non_empty) < 2:
            return False
        hits = len([v for v in non_empty if cls._HEADER_HINT_RE.search(str(v))])
        return hits >= 2 and hits >= max(2, len(non_empty) // 3)

    def _try_handle_multimodal_chat(
        self, *, user_id: str, message: str, source: str | None, context: dict[str, _facade().Any]
    ) -> dict[str, _facade().Any] | None:
        """多模态主链路收口：聊天上下文携带真实多模态 artifact 且多模态自治规划器能产出
        计划时，走真正的 orchestrator run（Dataset/RAG 入库+检索/确认写库），替代 legacy 兜底。

        护栏：无 artifact 信号键、或规划器返回 None 时不分流，保持 legacy 主链路不变；
        实测纯文本 / excel_vector / 纯 excel_analysis 上下文均不会分流（最热路径零影响）。
        """
        ctx = context if isinstance(context, dict) else {}
        signal_keys = (
            "multimodal_attachments",
            "attachments",
            "files",
            "artifacts",
            "ocr",
            "ocr_result",
            "file_analysis",
            "generated_document",
            "excel_analysis",
        )
        if not any(ctx.get(key) for key in signal_keys):
            return None
        try:
            from app.application.agent_orchestrator.multimodal_planner import (
                build_multimodal_autonomous_plan,
            )
        except _facade().RECOVERABLE_ERRORS:
            return None
        runtime_ctx = dict(ctx)
        runtime_ctx.setdefault("message", message)
        try:
            plan = build_multimodal_autonomous_plan(
                user_id=user_id, message=message, runtime_context=runtime_ctx
            )
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("multimodal autonomous plan probe skipped", exc_info=True)
            return None
        if plan is None:
            return None
        try:
            return self._start_deterministic_import_agent_run(
                user_id=user_id,
                message=message,
                source=source,
                context=ctx,
                file_context={},
                plan=plan,
                thinking_steps="检测到多模态附件，已转入多模态自治工作流",
            )
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception(
                "multimodal autonomous run failed; falling back to legacy chat"
            )
            return None
