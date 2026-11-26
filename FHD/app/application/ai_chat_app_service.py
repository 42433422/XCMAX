"""Unified chat lifecycle around the fixed Xiaox runtime and business evidence."""

from __future__ import annotations

import logging
from typing import Any

from app.di.registry import get_service_registry
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

from app.application.ai_chat.context_enrichment import (
    inject_excel_vector_context,
    inject_wechat_contact_context,
)
from app.application.ai_chat.conversation_history import (
    persist_chat_turn,
    persist_recallable_chat_turn,
)


class AIChatApplicationService:
    """Chat identity, context and history around the single Xiaox agent runtime."""

    def process_chat(
        self,
        user_id: str,
        message: str,
        context: dict[str, Any] | None = None,
        source: str | None = None,
        file_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not message:
            return {"success": False, "message": "消息内容不能为空"}
        from app.application.agent_task_context import scoped_conversation_user_id
        from app.application.ai_feature_isolation import (
            BUSINESS_DOCKING,
            SMART_CHAT,
            ai_feature_channel,
            normalize_channel,
            tag_mapping,
        )

        context = dict(context or {})
        context.setdefault("conversation_id", context.get("session_id") or user_id)
        user_id = scoped_conversation_user_id(user_id, context)
        channel = normalize_channel(context.get("ai_feature_channel") or source) or SMART_CHAT
        if str(source or "").strip().lower() in {
            "office_docking",
            "chat_office_docking",
            "business_docking",
            "elt",
        }:
            channel = BUSINESS_DOCKING
        context = tag_mapping(context, channel=channel)
        from app.application.agent_orchestrator.runtime_context import RuntimeContextOwnershipError
        from app.infrastructure.auth.agent_mod_scope import validate_actor_context
        from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope

        tenant_id = current_tenant_id()
        if context.get("_actor_authorization") is not None:
            if validate_actor_context(context) is not None:
                raise RuntimeContextOwnershipError("聊天请求的原登录身份已失效")
            tenant_id = context.get("tenant_id")
        from app.infrastructure.llm.model_admission import model_rate_limit_scope

        with tenant_scope(tenant_id), ai_feature_channel(channel), model_rate_limit_scope(context):
            from app.application.chat_turn_guard import admit_chat_turn

            guard_reply = admit_chat_turn(message, context)
            if guard_reply is not None:
                return guard_reply
            from app.application.ai_chat.dialogue_memory import (
                prepare_chat_turn,
                settle_chat_turn,
            )

            prepared = prepare_chat_turn(message, context)
            if prepared is not None:
                return prepared
            from app.infrastructure.chat_stream_lifetime import publish_stream_note

            publish_stream_note("正在分析你的需求…")
            try:
                return self._process_chat_impl(user_id, message, context, source, file_context)
            except RECOVERABLE_ERRORS:
                settle_chat_turn(message, context, None, "failed")
                raise

    def _process_chat_impl(
        self,
        user_id: str,
        message: str,
        context: dict[str, Any],
        source: str | None,
        file_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_received

            neuro_notify_chat_received(user_id, message, source)
        except RECOVERABLE_ERRORS:
            logger.debug("neuro_notify_chat_received skipped", exc_info=True)
        from app.application.agent_orchestrator.business_harness import (
            business_write_requested,
            ensure_business_harness_context,
        )

        ctx = ensure_business_harness_context(context, message=message)

        def _finalize(resp: dict[str, Any]) -> dict[str, Any]:
            def unknown_result(payload: dict[str, Any]) -> dict[str, Any]:
                text = "业务结果暂时无法核实，请核对处理状态后再操作。"
                data = (
                    dict(payload.get("data") or {}) if isinstance(payload.get("data"), dict) else {}
                )
                data.update(text=text, response=text, requires_reconciliation=True)
                return {
                    **payload,
                    "success": False,
                    "execution_state": "unknown",
                    "requires_reconciliation": True,
                    "message": text,
                    "response": text,
                    "data": data,
                }

            if not (resp.get("run_id") or resp.get("agent_run_id")):
                try:
                    from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run

                    resp = attach_chat_trace_run(
                        resp,
                        message=message,
                        runtime_context=ctx,
                        user_id=user_id,
                        source=source,
                        channel="ai_chat_mainline",
                        intent=str((resp.get("data") or {}).get("action") or "chat_reply"),
                    )
                except RECOVERABLE_ERRORS:
                    logger.warning("chat trace attach failed", exc_info=True)
                    if business_write_requested(message):
                        resp = unknown_result(resp)
            try:
                from app.application.agent_orchestrator.business_harness import (
                    attach_visible_business_result_to_chat_payload,
                )

                resp = attach_visible_business_result_to_chat_payload(resp)
            except RECOVERABLE_ERRORS:
                logger.debug("visible business result attach skipped", exc_info=True)
            try:
                from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_completed

                neuro_notify_chat_completed(user_id, message, resp)
            except RECOVERABLE_ERRORS:
                logger.debug("neuro_notify_chat_completed skipped", exc_info=True)
            from app.domain.shared_services.conversation_service import ConversationRevisionError

            try:
                resp["history_persistence"] = self._persist_chat_turn(user_id, message, ctx, resp)
            except ConversationRevisionError:
                resp["history_persistence"] = {"status": "invalidated", "retry": "none"}
            except RECOVERABLE_ERRORS as persist_err:
                resp["history_persistence"] = {
                    "status": "failed",
                    "retry": "save_only",
                    "turn_id": ctx.get("turn_id"),
                    "revision": ctx.get("_conversation_revision", 0),
                    "conversation_id": ctx.get("session_id") or ctx.get("conversation_id"),
                    "message": "本轮结果已返回，但历史尚未保存，请仅重试保存。",
                }
                logger.warning("会话落库失败（业务结果保持原状）: %s", persist_err)
            try:
                if (resp.get("history_persistence") or {}).get("status") != "invalidated":
                    self._persist_recallable_chat_turn(
                        user_id=user_id,
                        message=message,
                        source=source,
                        context=ctx,
                        response_data=resp,
                    )
            except RECOVERABLE_ERRORS as memory_err:
                logger.warning("跨会话记忆写入失败（已返回对话结果）: %s", memory_err)
            try:
                from app.application.agent_orchestrator.trace_payloads import _payload_status
                from app.application.ai_chat.dialogue_memory import settle_chat_turn
                from app.domain.task_lifecycle.results import (
                    execution_result_requires_reconciliation,
                    execution_result_wait_reason,
                )

                status: str = _payload_status(resp)
                if status == "waiting_user":
                    status = (
                        "waiting_approval"
                        if execution_result_wait_reason(resp) in {"authorization", "approval"}
                        else "waiting_user"
                    )
                elif status == "blocked" and execution_result_requires_reconciliation(resp):
                    status = "unknown"
                settle_chat_turn(message, ctx, resp, status)
            except RECOVERABLE_ERRORS:
                logger.warning("dialogue turn settle failed", exc_info=True)
            return resp

        from app.application.agent_runtime.chat import run_runtime_chat

        ctx = self._inject_excel_vector_context(message=message, context=ctx)
        ctx = self._inject_wechat_contact_context(message=message, context=ctx)
        runtime_result = run_runtime_chat(
            user_id=user_id,
            message=message,
            context=ctx,
            file_context=file_context or {},
        )
        return _finalize(runtime_result)

    # These operations only consume explicit request/record inputs; no inheritance
    # or mutable application-service state is required to persist or enrich a turn.
    _persist_chat_turn = staticmethod(persist_chat_turn)
    _persist_recallable_chat_turn = staticmethod(persist_recallable_chat_turn)
    _inject_excel_vector_context = staticmethod(inject_excel_vector_context)
    _inject_wechat_contact_context = staticmethod(inject_wechat_contact_context)


def get_ai_chat_app_service() -> AIChatApplicationService:
    """获取 AI 聊天应用服务单例"""
    return get_service_registry().ai_chat_application_service
