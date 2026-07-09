"""AIChatApplicationService composed from mixins."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.application.workflow import (
    HybridRiskGate,
    LLMWorkflowPlanner,
    WorkflowEngine,
    get_approval_service,
)
from app.di.registry import get_service_registry
from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import resolve_fhd_repo_root

from .excel_import_mixin import AIChatExcelImportMixin
from .helpers import _facade_attr
from .tool_execution_mixin import AIChatToolExecutionMixin
from .workflow_mixin import AIChatWorkflowMixin

logger = logging.getLogger(__name__)


class AIChatApplicationService(
    AIChatExcelImportMixin,
    AIChatWorkflowMixin,
    AIChatToolExecutionMixin,
):
    """
    AI 聊天应用服务

    编排 AI 对话和即时工具执行，负责：
    - 聊天主流程处理
    - 即时工具执行（source=pro 和普通模式）
    - 响应格式构建
    """

    def __init__(self):
        self.ai_service = _facade_attr("get_ai_conversation_service", get_ai_conversation_service)()
        self.workflow_planner = _facade_attr("LLMWorkflowPlanner", LLMWorkflowPlanner)()
        self.risk_gate = _facade_attr("HybridRiskGate", HybridRiskGate)()
        self.workflow_engine = _facade_attr("WorkflowEngine", WorkflowEngine)(
            tool_dispatcher=self._dispatch_workflow_tool
        )
        self.approval_service = _facade_attr("get_approval_service", get_approval_service)()
        self._pending_workflows: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _is_pro_source(source: str | None) -> bool:
        """兼容 pro 来源字段的多种写法（与 fastapi_routes.ai_chat._is_pro_source 对齐）。"""
        normalized = str(source or "").strip().lower().replace("-", "_")
        return normalized in {
            "pro",
            "pro_mode",
            "promode",
            "professional",
            "xcagi_pro",
        }

    @staticmethod
    def _merge_tool_runtime_context(
        user_id: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime_ctx: dict[str, Any] = {"user_id": user_id, "message": message}
        if isinstance(context, dict):
            for key in ("ui_surface", "intent_channel", "tool_execution_profile"):
                if key in context and context[key] is not None:
                    runtime_ctx[key] = context[key]
            # 透传 Excel 分析上下文，支持自然语言按 sheet 入模板库
            for key in ("excel_analysis", "last_excel_analysis_context"):
                if key in context and isinstance(context[key], dict):
                    runtime_ctx[key] = context[key]
        return runtime_ctx

    def process_chat(
        self,
        user_id: str,
        message: str,
        context: dict[str, Any] | None = None,
        source: str | None = None,
        file_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
            return {
                "success": False,
                "message": "消息内容不能为空",
            }

        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_received

            neuro_notify_chat_received(user_id, message, source)
        except RECOVERABLE_ERRORS:
            logger.debug("neuro_notify_chat_received skipped", exc_info=True)

        ctx = context or {}
        # Excel 向量：须在 _try_handle_dynamic_workflow 之前注入，否则「规则导入捷径」提前 return 时永远不会检索索引。
        ctx = self._inject_excel_vector_context(message=message, context=dict(ctx))

        # 收口：自然语言主链路在执行前开一个真实的 AgentRun（前置 run，而非事后 trace）。
        # chat_run / chat_run_context 由下方主链路赋值；workflow 捷径路径保持 None（已自带 run）。
        chat_run = None
        chat_run_context: dict[str, Any] = {}

        def _finalize(resp: dict[str, Any]) -> dict[str, Any]:
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
                except RECOVERABLE_ERRORS:
                    logger.debug("legacy chat AgentRun finalize skipped", exc_info=True)
            try:
                from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_completed

                neuro_notify_chat_completed(user_id, message, resp)
            except RECOVERABLE_ERRORS:
                logger.debug("neuro_notify_chat_completed skipped", exc_info=True)
            try:
                self._persist_chat_turn(user_id, message, ctx, resp)
            except RECOVERABLE_ERRORS as persist_err:
                logger.warning("会话落库失败（已返回对话结果）: %s", persist_err)

            return resp

        try:
            from app.application.workflow.chat_deterministic_fast_paths import (
                try_deterministic_chat_reply,
            )

            fhd_root = resolve_fhd_repo_root(anchor=Path(__file__).resolve())
            deterministic_reply = try_deterministic_chat_reply(
                message,
                runtime_context=ctx,
                workspace_root=str(fhd_root) if fhd_root else None,
            )
        except RECOVERABLE_ERRORS:
            logger.debug("deterministic chat fast path skipped", exc_info=True)
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

        # 多模态主链路收口：聊天携带真实多模态 artifact 时，走 orchestrator 多模态自治 run
        # （而非 legacy 兜底）。护栏内置于 _try_handle_multimodal_chat：无 artifact 不分流。
        multimodal_result = self._try_handle_multimodal_chat(
            user_id=user_id,
            message=message,
            source=source,
            context=ctx,
        )
        if multimodal_result is not None:
            return _finalize(multimodal_result)

        # 自然语言主链路：在调用 legacy 引擎前开真实 run，使 created→running→completed
        # 的生命周期反映真实执行（替代路由层的事后 post_execution trace）。legacy 引擎本身不变。
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
        except RECOVERABLE_ERRORS:
            logger.debug("legacy chat AgentRun pre-create skipped", exc_info=True)

        enriched_context = dict(ctx)
        if isinstance(file_context, dict):
            excel_file_path = file_context.get("file_path") or file_context.get(
                "original_file_path"
            )
            if excel_file_path:
                excel_analysis_obj = {
                    "file_path": str(excel_file_path).strip(),
                }
                sheet_name = file_context.get("sheet_name")
                if sheet_name:
                    excel_analysis_obj["sheet_name"] = str(sheet_name).strip()
                enriched_context["excel_analysis"] = excel_analysis_obj

        # 向量已在 ctx 上注入；enriched_context 由 ctx 浅拷贝而来，无需再次检索。
        prepared_context = enriched_context

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ai_result = loop.run_until_complete(
                self.ai_service.chat(user_id, message, prepared_context, source=source)
            )
        except ConnectionError as conn_err:
            logger.error("AI 服务连接失败：%s", conn_err)
            loop.close()
            return _finalize(
                self._build_fallback_response(
                    message, "AI 服务连接失败，可能是网络问题或服务未启动"
                )
            )
        except TimeoutError as timeout_err:
            logger.error("AI 服务请求超时：%s", timeout_err)
            loop.close()
            return _finalize(self._build_fallback_response(message, "AI 服务响应超时，请稍后重试"))
        except RECOVERABLE_ERRORS as e:
            logger.error("AI 服务处理异常：%s", e, exc_info=True)
            loop.close()
            error_msg = str(e)
            if "api_key" in error_msg.lower() or "apikey" in error_msg.lower():
                return _finalize(
                    self._build_fallback_response(
                        message, "AI 服务 API Key 未配置或无效，请联系管理员"
                    )
                )
            elif "connection" in error_msg.lower():
                return _finalize(
                    self._build_fallback_response(message, "无法连接到 AI 服务，请检查网络设置")
                )
            else:
                return _finalize(
                    self._build_fallback_response(message, f"AI 服务暂时不可用：{error_msg[:100]}")
                )
        finally:
            loop.close()

        logger.info(
            "用户 %s 消息：%s... -> %s", user_id, message[:50], ai_result.get("action", "unknown")
        )

        response_data = self._build_response(ai_result, source, message)

        return _finalize(response_data)

    def _persist_chat_turn(
        self,
        user_id: str,
        message: str,
        context: dict[str, Any],
        response_data: dict[str, Any],
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
        inner_payload = inner.get("data") if isinstance(inner.get("data"), dict) else {}
        tool_call = (
            response_data.get("toolCall") if isinstance(response_data.get("toolCall"), dict) else {}
        )
        intent = str(
            inner_payload.get("intent")
            or inner_payload.get("tool_key")
            or tool_call.get("tool_id")
            or inner.get("action")
            or "",
        ).strip()

        summary = {
            "success": bool(response_data.get("success")),
            "action": inner.get("action"),
            "intent": intent,
            "toolCall": tool_call or None,
            "plan_id": inner_payload.get("plan_id"),
            "document": (
                (inner_payload.get("document") or {}).get("doc_name")
                if isinstance(inner_payload.get("document"), dict)
                else None
            ),
            "excel_import": (
                inner_payload.get("result")
                if inner_payload.get("intent") == "excel_import_to_db"
                else None
            ),
        }

        meta_user = json.dumps({"role_hint": "user", "summary": summary}, ensure_ascii=False)[
            :12000
        ]
        meta_assistant = json.dumps(
            {"role_hint": "assistant", "summary": summary}, ensure_ascii=False
        )[:12000]

        conv = get_conversation_service()
        conv.save_message(
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=str(message)[:8000],
            intent=intent or "chat",
            metadata=meta_user,
        )
        reply = str(response_data.get("response") or inner.get("text") or "")[:8000]
        conv.save_message(
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=reply,
            intent=intent or "assistant_reply",
            metadata=meta_assistant,
        )

    def _inject_excel_vector_context(
        self,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
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
        except RECOVERABLE_ERRORS:
            top_k = 5

        try:
            from app.application import get_excel_vector_search_app_service

            search_service = get_excel_vector_search_app_service()
            result = search_service.query(
                index_id=excel_index_id,
                query_text=message,
                top_k=top_k,
            )
            if result.get("success"):
                enriched = dict(context)
                enriched["excel_vector_context"] = {
                    "index_id": excel_index_id,
                    "query": message,
                    "hits": result.get("hits", []),
                }
                return enriched
        except RECOVERABLE_ERRORS as err:
            logger.warning("注入 Excel 向量上下文失败: %s", err, exc_info=True)

        return context

    @staticmethod
    def _build_fallback_response(message: str, error_reason: str) -> dict[str, Any]:
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




def get_ai_chat_app_service() -> AIChatApplicationService:
    """获取 AI 聊天应用服务单例"""
    return get_service_registry().ai_chat_application_service
