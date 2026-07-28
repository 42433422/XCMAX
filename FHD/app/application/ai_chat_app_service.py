"""
AI 聊天应用服务

编排 AI 聊天业务逻辑：
- 处理即时工具执行（products/customers/shipments/shipment_generate）
- 构建统一响应格式
- 处理确认流程

说明：专业版下若请求已带 excel_analysis 且用户话术中命中「导入/入库」等关键词，
``_try_handle_dynamic_workflow`` 可能走「规则映射 + 写库」捷径（见 ``import_pipeline``）。

**决策权**：默认由前端随请求附带 ``excel_import_ai_decides: true``，此时**不**走规则捷径，
入库映射与执行交给主对话 / Planner 与工具链（与「AI 拥有决策权」一致）。若需恢复极速规则入库，
可在设置中开启「Excel 入库走规则捷径」，或请求体 ``context.excel_import_use_deterministic_shortcut: true``。

服务端还可设 ``XCAGI_EXCEL_IMPORT_AI_DECIDES=1``（全局倾向 AI 路径）或
``XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT=1`` / ``context.excel_import_skip_deterministic_shortcut``（等价跳过捷径）。
"""

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import httpx  # noqa: F401 - compatibility patch point for legacy tests/callers

from app.di.registry import get_service_registry
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import resolve_fhd_repo_root

logger = logging.getLogger(__name__)

from app.application.ai_chat.excel_import_pipeline import AIChatExcelImportMixin
from app.application.ai_chat.excel_import_policy import (
    _EXCEL_IMPORT_MEASURE_UNIT_TOKENS as _EXCEL_IMPORT_MEASURE_UNIT_TOKENS,
)
from app.application.ai_chat.excel_import_policy import (
    _enrich_confirmation_inner,
    _skip_pro_excel_deterministic_import,
)
from app.application.ai_chat.instant_tools import AIChatInstantToolsMixin
from app.application.ai_chat.workflow_response_builder import AIChatWorkflowResponseMixin


def _import_workflow_components():
    from app.application.workflow import (
        HybridRiskGate,
        LLMWorkflowPlanner,
        WorkflowEngine,
        get_approval_service,
    )

    return HybridRiskGate, LLMWorkflowPlanner, WorkflowEngine, get_approval_service


def _import_ai_conversation_service():
    from app.services import get_ai_conversation_service as _get

    return _get


def get_ai_conversation_service():
    """Lazy re-export so unit tests can patch this module attribute."""
    return _import_ai_conversation_service()()


# 单测通过 ``patch("app.application.ai_chat_app_service.LLMWorkflowPlanner")`` 等方式
# 替换工作流组件；这些符号不能在模块顶层 ``from app.application.workflow import``，
# 否则会重新引入与 ``app.application.workflow.planner`` 的循环 import（见 commit
# ed1f6e7e0）。PEP 562 模块级 ``__getattr__`` 在属性未在 ``__dict__`` 时才触发，
# 既能让 ``mock.patch`` 取到原始值，又不会在 import 期触发循环。
_LAZY_WORKFLOW_RE_EXPORTS = (
    "HybridRiskGate",
    "LLMWorkflowPlanner",
    "WorkflowEngine",
    "get_approval_service",
)


def __getattr__(name: str):
    if name in _LAZY_WORKFLOW_RE_EXPORTS:
        HybridRiskGate, LLMWorkflowPlanner, WorkflowEngine, get_approval_service = (
            _import_workflow_components()
        )
        globals().update(
            HybridRiskGate=HybridRiskGate,
            LLMWorkflowPlanner=LLMWorkflowPlanner,
            WorkflowEngine=WorkflowEngine,
            get_approval_service=get_approval_service,
        )
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class AIChatApplicationService(
    AIChatExcelImportMixin,
    AIChatWorkflowResponseMixin,
    AIChatInstantToolsMixin,
):
    """
    AI 聊天应用服务

    编排 AI 对话和即时工具执行，负责：
    - 聊天主流程处理
    - 即时工具执行（source=pro 和普通模式）
    - 响应格式构建
    """

    def __init__(self):
        # PEP 562 模块级 ``__getattr__`` 仅在 ``module.attr`` 访问时触发，不在
        # 普通名字查找时触发；通过 ``_self`` 显式走属性访问，既能让
        # ``mock.patch("app.application.ai_chat_app_service.LLMWorkflowPlanner")``
        # 替换的 MagicMock 生效，也能在无 mock 时触发 lazy 解析并缓存到
        # ``__dict__``，避免 ``NameError``。
        import sys as _sys

        _self = _sys.modules[__name__]
        self.ai_service = get_ai_conversation_service()
        self.workflow_planner = _self.LLMWorkflowPlanner()
        self.risk_gate = _self.HybridRiskGate()
        self.workflow_engine = _self.WorkflowEngine(tool_dispatcher=self._dispatch_workflow_tool)
        self.approval_service = _self.get_approval_service()
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
            try:
                self._persist_recallable_chat_turn(
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=ctx,
                    response_data=resp,
                )
            except RECOVERABLE_ERRORS as memory_err:
                logger.warning("跨会话记忆写入失败（已返回对话结果）: %s", memory_err)

            return resp

        # Direct callers of AIChatApplicationService (outside the compat
        # routes) receive the same receipt-enforced behavior.  The route layer
        # also invokes this policy so legacy-mode deployments are protected.
        from app.application.chat_business_safety import try_handle_business_chat_action

        business_payload = try_handle_business_chat_action(
            message,
            runtime_context=ctx,
            user_id=user_id,
        )
        if business_payload is not None:
            return _finalize(business_payload)

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

    @staticmethod
    def _persist_recallable_chat_turn(
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        response_data: dict[str, Any],
    ) -> None:
        if context.get("memory_capture_enabled") is False or not response_data.get("success"):
            return
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return
        from app.utils.deployment import is_desktop_mode

        trusted_principal = context.get("_dataset_access_context_trusted") is True
        if not trusted_principal and not is_desktop_mode():
            return
        inner = response_data.get("data") if isinstance(response_data.get("data"), dict) else {}
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
        sensitive = re.compile(
            r"(?:password|passcode|api[_ -]?key|access[_ -]?token|secret|验证码|密码|密钥)",
            re.I,
        )
        assistant_text = str(response_data.get("response") or "").strip()
        if not assistant_text:
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
                scope=(
                    "tenant"
                    if str(context.get("persy_memory_scope") or "").strip().lower() == "tenant"
                    else "user"
                ),
            )

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

    @staticmethod
    def _is_number_text(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        try:
            float(text.replace(",", ""))
            return True
        except RECOVERABLE_ERRORS:
            return False

    _HEADER_HINT_RE = re.compile(
        r"(产品|名称|规格|型号|编号|单价|价格|调价|金额|单位|客户|厂名|品名)"
    )

    @classmethod
    def _row_values_look_like_table_headers(cls, values: list[str]) -> bool:
        non_empty = [v for v in values if str(v or "").strip()]
        if len(non_empty) < 2:
            return False
        hits = sum(1 for v in non_empty if cls._HEADER_HINT_RE.search(str(v)))
        return hits >= 2 and hits >= max(2, len(non_empty) // 3)

    def _try_handle_multimodal_chat(
        self,
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
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
        except RECOVERABLE_ERRORS:
            return None
        runtime_ctx = dict(ctx)
        runtime_ctx.setdefault("message", message)
        try:
            plan = build_multimodal_autonomous_plan(
                user_id=user_id,
                message=message,
                runtime_context=runtime_ctx,
            )
        except RECOVERABLE_ERRORS:
            logger.debug("multimodal autonomous plan probe skipped", exc_info=True)
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
        except RECOVERABLE_ERRORS:
            logger.exception("multimodal autonomous run failed; falling back to legacy chat")
            return None

    def _try_handle_dynamic_workflow(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        file_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        text = str(message or "").strip()
        if not text:
            return None
        explicit_workflow_tool_intent = self._looks_like_explicit_workflow_tool_intent(text)
        smart_workflow_intent = self._looks_like_smart_workflow_intent(text, context)
        has_pending_workflow = user_id in self._pending_workflows
        if (
            not self._is_pro_source(source)
            and not smart_workflow_intent
            and not has_pending_workflow
        ):
            return None

        merged_file_ctx = {}
        if isinstance(context, dict):
            merged_file_ctx.update(context.get("file_analysis") or {})
            merged_file_ctx.update(context.get("file_context") or {})
        if isinstance(file_context, dict):
            merged_file_ctx.update(file_context)

        import_intent = any(k in text for k in ("导入", "入库", "添加到数据库", "写入数据库"))
        if import_intent and (merged_file_ctx.get("suggested_use") == "unit_products_db"):
            saved_name = str(merged_file_ctx.get("saved_name") or "").strip()
            unit_name = str(
                merged_file_ctx.get("unit_name") or merged_file_ctx.get("unit_name_guess") or ""
            ).strip()
            if not saved_name:
                payload = {
                    "success": True,
                    "message": "处理完成",
                    "response": "已识别导入意图，但缺少源文件上下文。请先上传并分析 .db 文件。",
                    "data": {"text": "请先上传并分析 .db 文件。", "action": "followup", "data": {}},
                }
                return self._attach_deterministic_workflow_trace(
                    payload,
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=context,
                    file_context=merged_file_ctx,
                    intent="import_unit_products_db",
                )
            if not unit_name:
                payload = {
                    "success": True,
                    "message": "处理完成",
                    "response": "已识别导入意图，请补充客户名称后继续导入。",
                    "data": {
                        "text": "请补充客户名称后继续导入。",
                        "action": "followup",
                        "data": {"missing_fields": ["unit_name"]},
                    },
                }
                return self._attach_deterministic_workflow_trace(
                    payload,
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=context,
                    file_context=merged_file_ctx,
                    intent="import_unit_products_db",
                )

            todo_lines = [
                "检查客户是否存在，不存在则自动创建",
                "读取源库 products 表并映射字段",
                "按单位+型号/名称去重后导入产品",
                "返回导入结果（新增/跳过/失败）",
            ]
            from app.application.workflow.types import PlanGraph, WorkflowNode

            plan = PlanGraph(
                plan_id=f"plan_unit_products_import_{uuid.uuid4().hex[:12]}",
                intent="import_unit_products_db",
                todo_steps=todo_lines,
                nodes=[
                    WorkflowNode(
                        node_id="import_unit_products",
                        tool_id="unit_products_import",
                        action="execute_import",
                        params={
                            "saved_name": saved_name,
                            "unit_name": unit_name,
                            "create_purchase_unit": True,
                            "skip_duplicates": True,
                        },
                        risk="medium",
                        idempotent=False,
                        description="从已分析 .db 文件导入单位和产品",
                    )
                ],
                risk_level="medium",
                metadata={
                    "source": "deterministic_file_import",
                    "artifacts": [
                        {
                            "artifact_type": "database_file",
                            "name": saved_name,
                            "source": "file_analysis",
                            "summary": f"unit_products_db 导入源文件，目标客户：{unit_name}",
                            "fields": [
                                {"name": "saved_name", "value": saved_name},
                                {"name": "unit_name", "value": unit_name},
                                {
                                    "name": "suggested_use",
                                    "value": merged_file_ctx.get("suggested_use"),
                                },
                            ],
                            "metadata": {
                                "suggested_use": merged_file_ctx.get("suggested_use"),
                                "unit_name_guess": merged_file_ctx.get("unit_name_guess"),
                            },
                        }
                    ],
                },
            )
            thinking_steps = self._build_workflow_thinking_steps(
                plan,
                "unit_products 导入会写入客户和产品数据库，需用户确认",
            )
            return self._start_deterministic_import_agent_run(
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                file_context=merged_file_ctx,
                plan=plan,
                thinking_steps=thinking_steps,
            )

        # 无分析结果时短指令勿走 LLM（混合 normal 画像下否则会长时间阻塞在 DeepSeek）
        if (
            not self._excel_analysis_payload_present(context)
            and self._looks_like_short_excel_import_command(text)
            and not explicit_workflow_tool_intent
        ):
            payload = {
                "success": True,
                "message": "处理完成",
                "response": (
                    "未检测到 Excel 分析上下文。请先点击工具栏「分析 Excel」上传并分析表格，再发送「加入数据库」等指令。\n"
                    "若已分析过，可能是会话切换或页面刷新导致上下文丢失——请重新分析一次。"
                ),
                "data": {
                    "text": "未检测到 Excel 分析上下文，请先分析 Excel。",
                    "action": "followup",
                    "data": {"intent": "excel_import_missing_context"},
                },
            }
            return self._attach_deterministic_workflow_trace(
                payload,
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                file_context=merged_file_ctx,
                intent="excel_import_missing_context",
            )

        # 下列分支为「规则入库捷径」：关键词 + excel_analysis 即写库，不经过本轮主对话模型的端到端推理。
        # 默认由前端 context.excel_import_ai_decides 跳过本分支，改走主链路使模型/Planner 拥有入库决策权。
        excel_analysis = (
            (context or {}).get("excel_analysis") if isinstance(context, dict) else None
        )
        if (
            isinstance(excel_analysis, dict)
            and any(k in text for k in ("数据库", "入库", "导入", "添加到库"))
            and not _skip_pro_excel_deterministic_import(context)
        ):
            fields = excel_analysis.get("fields") or []
            field_names = []
            for item in fields[:10]:
                if isinstance(item, dict):
                    field_names.append(str(item.get("label") or item.get("name") or "").strip())
                else:
                    field_names.append(str(item).strip())
            field_names = [x for x in field_names if x]
            summary = str(excel_analysis.get("summary") or "").strip()
            todo_lines = [
                "按内容指纹识别送货单表（标题含送货单+购货单位+产品明细）",
                "解析抬头客户与明细行",
                "写入客户、产品，并生成发货单",
                "返回闭环结果（发货单数/产品数）",
            ]
            file_path = str(
                excel_analysis.get("file_path")
                or (
                    (excel_analysis.get("preview_data") or {})
                    if isinstance(excel_analysis.get("preview_data"), dict)
                    else {}
                ).get("file_path")
                or ""
            ).strip()
            delivery_notes: list = []
            if file_path:
                try:
                    from app.application.shipment_excel_etl_app_service import (
                        parse_delivery_notes,
                    )

                    parsed_notes = parse_delivery_notes(file_path)
                    if parsed_notes.get("success") and parsed_notes.get("notes"):
                        delivery_notes = list(parsed_notes.get("notes") or [])
                except RECOVERABLE_ERRORS as parse_err:
                    logger.warning("shipment etl detect failed: %s", parse_err)

            if delivery_notes:
                from app.application.workflow.types import PlanGraph, WorkflowNode

                note_summary = "；".join(
                    f"{n.get('sheet')}→{n.get('unit_name')}({n.get('item_count')}行)"
                    for n in delivery_notes[:5]
                )
                plan = PlanGraph(
                    plan_id=f"plan_shipment_etl_{uuid.uuid4().hex[:12]}",
                    intent="excel_import_to_db",
                    todo_steps=todo_lines,
                    nodes=[
                        WorkflowNode(
                            node_id="import_delivery_notes",
                            tool_id="excel_import",
                            action="import_delivery_notes",
                            params={
                                "file_path": file_path,
                                "notes": delivery_notes,
                                "import_products": True,
                                "import_shipments": True,
                                "source": "deterministic_shipment_etl",
                            },
                            risk="medium",
                            idempotent=False,
                            description="将送货单写入客户/产品/发货单（闭环）",
                        )
                    ],
                    risk_level="medium",
                    metadata={
                        "source": "deterministic_shipment_excel_etl",
                        "artifacts": [
                            {
                                "artifact_type": "shipment_delivery_notes",
                                "name": str(
                                    excel_analysis.get("file_name")
                                    or excel_analysis.get("template_name")
                                    or "shipment_etl"
                                ),
                                "source": "excel_analysis",
                                "uri": file_path,
                                "summary": note_summary or f"送货单 {len(delivery_notes)} 张",
                                "preview": {
                                    "note_count": len(delivery_notes),
                                    "sample_notes": [
                                        {
                                            "sheet": n.get("sheet"),
                                            "unit_name": n.get("unit_name"),
                                            "item_count": n.get("item_count"),
                                            "total_amount": n.get("total_amount"),
                                        }
                                        for n in delivery_notes[:3]
                                    ],
                                },
                                "metadata": {
                                    "import_pipeline": "shipment_delivery_etl",
                                    "closed_loop": True,
                                },
                            }
                        ],
                    },
                )
                thinking_steps = self._build_workflow_thinking_steps(
                    plan,
                    "检测到送货单版式，将写入客户/产品/发货单，需用户确认",
                )
                return self._start_deterministic_import_agent_run(
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=context,
                    file_context=merged_file_ctx,
                    plan=plan,
                    thinking_steps=thinking_steps,
                )

            todo_lines = [
                "解析 Excel 数据并映射单位/产品/型号/价格字段",
                "检查客户是否存在，不存在则创建",
                "检查产品是否存在，缺失则创建并绑定单位",
                "返回导入结果（新增单位/新增产品/跳过重复）",
            ]
            records, extract_err = self._extract_excel_import_records(
                excel_analysis, context, user_message=text
            )
            if extract_err == "ambiguous_price_columns":
                cols_preview = "、".join(field_names[:24]) if field_names else "（见上文字段列表）"
                followup_text = (
                    "已检测到多个「价格」相关列（例如同时存在「调价前…价」与「调价后…价」），"
                    "为避免入错库，已暂停自动写入。\n"
                    "请在下一条消息中明确指定，例如：「导入数据库，价格用调价前列」或「…单价取调价后那一列」。\n"
                    f"当前识别到的部分列名：{cols_preview}"
                )
                payload = {
                    "success": True,
                    "message": "处理完成",
                    "response": followup_text,
                    "data": {
                        "text": followup_text,
                        "action": "followup",
                        "data": {
                            "intent": "excel_import_to_db",
                            "import_pipeline": "deterministic_shortcut",
                            "import_pipeline_zh": "服务端规则入库（非本轮大模型端到端决策）",
                            "thinking_steps": "价格列存在歧义，需用户明确选用调价前或调价后",
                            "todo": todo_lines,
                            "blocked_reason": extract_err,
                        },
                    },
                }
                return self._attach_deterministic_workflow_trace(
                    payload,
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=context,
                    file_context=merged_file_ctx,
                    intent="excel_import_to_db",
                )
            if not records:
                followup_text = (
                    "我已读取到 Excel 上下文，但未解析到可入库的单位/产品记录。\n"
                    f"已识别字段: {'、'.join(field_names) if field_names else '未识别到字段'}"
                )
                if summary:
                    followup_text += f"\n上下文摘要:\n{summary[:500]}"
                payload = {
                    "success": True,
                    "message": "处理完成",
                    "response": followup_text,
                    "data": {
                        "text": followup_text,
                        "action": "followup",
                        "data": {
                            "intent": "excel_import_to_db",
                            "import_pipeline": "deterministic_shortcut",
                            "import_pipeline_zh": "服务端规则入库（非本轮大模型端到端决策）",
                            "thinking_steps": "已完成字段识别，但记录提取为空",
                            "todo": todo_lines,
                        },
                    },
                }
                return self._attach_deterministic_workflow_trace(
                    payload,
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=context,
                    file_context=merged_file_ctx,
                    intent="excel_import_to_db",
                )

            from app.application.workflow.types import PlanGraph, WorkflowNode

            plan = PlanGraph(
                plan_id=f"plan_excel_import_{uuid.uuid4().hex[:12]}",
                intent="excel_import_to_db",
                todo_steps=todo_lines,
                nodes=[
                    WorkflowNode(
                        node_id="import_excel_records",
                        tool_id="excel_import",
                        action="import_records",
                        params={
                            "records": records,
                            "source": "deterministic_shortcut",
                        },
                        risk="medium",
                        idempotent=False,
                        description="将 Excel 解析记录写入客户和产品数据库",
                    )
                ],
                risk_level="medium",
                metadata={
                    "source": "deterministic_excel_import",
                    "artifacts": [
                        {
                            "artifact_type": "excel_records",
                            "name": str(
                                excel_analysis.get("file_name")
                                or excel_analysis.get("template_name")
                                or "excel_import_records"
                            ),
                            "source": "excel_analysis",
                            "uri": str(excel_analysis.get("file_path") or ""),
                            "summary": summary or f"Excel 入库记录 {len(records)} 条",
                            "fields": [
                                {"name": name}
                                for name in field_names[:40]
                                if str(name or "").strip()
                            ],
                            "preview": {
                                "record_count": len(records),
                                "sample_records": records[:3],
                            },
                            "metadata": {
                                "import_pipeline": "deterministic_shortcut",
                                "sheet_name": excel_analysis.get("sheet_name"),
                            },
                        }
                    ],
                },
            )
            thinking_steps = self._build_workflow_thinking_steps(
                plan,
                "Excel 入库会写入客户和产品数据库，需用户确认",
            )
            return self._start_deterministic_import_agent_run(
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                file_context=merged_file_ctx,
                plan=plan,
                thinking_steps=thinking_steps,
            )

        from app.application.normal_chat_dispatch import (
            build_customers_query_response_dict,
            build_inventory_alert_response_dict,
            build_label_print_response_dict,
            build_product_query_response_dict,
            resolve_tool_execution_profile,
            route_normal_mode_message,
            run_normal_slot_shipment_preview,
        )

        profile = resolve_tool_execution_profile(context if isinstance(context, dict) else {})
        if profile == "normal" and not explicit_workflow_tool_intent:
            rr = route_normal_mode_message(text)
            if rr.get("intent") == "product_query":
                pq = build_product_query_response_dict(rr)
                if pq:
                    return pq
            if rr.get("intent") == "shipment":
                ship = run_normal_slot_shipment_preview(text)
                if ship.get("success"):
                    ship.pop("normal_slot_dispatch", None)
                    return ship
            if rr.get("intent") == "customers_query":
                cq = build_customers_query_response_dict(rr)
                if cq:
                    return cq
            if rr.get("intent") == "inventory_alert":
                ia = build_inventory_alert_response_dict(rr)
                if ia:
                    return ia
            if rr.get("intent") == "label_print":
                lp = build_label_print_response_dict(rr)
                if lp:
                    return lp
            if rr.get("intent") == "price_list":
                customer_name_match = re.search(
                    r"([^\s，,。]{2,}(?:有限公司|集团有限公司|实业有限公司|公司\s|单位|客户|厂|店))",
                    text,
                )
                keyword_match = re.search(r"[的的]\s*([^\s，,。]+)", text)
                slots = {}
                if customer_name_match:
                    slots["customer_name"] = customer_name_match.group(1)
                if keyword_match:
                    slots["keyword"] = keyword_match.group(1)

                if not slots.get("customer_name"):
                    return {
                        "success": False,
                        "message": "缺少客户名称",
                        "response": "请告诉我您要生成哪家客户的价格表？例如：「打印某某公司的价格表」",
                    }

                # 直接调用价格表生成 API，而不是返回 tool_call
                try:
                    fhd_root = resolve_fhd_repo_root(anchor=Path(__file__).resolve())
                    from app.application.tools import handle_price_list_export

                    logger.info("价格表生成 - FHD根目录: %s", fhd_root)

                    result = handle_price_list_export(
                        {
                            "customer_name": slots.get("customer_name", ""),
                            "keyword": slots.get("keyword"),
                            "export_date": None,
                        },
                        workspace_root=str(fhd_root) if fhd_root else None,
                    )

                    logger.info("价格表生成结果: %s", result)

                    if result.get("success"):
                        product_count = len(result.get("products", []))
                        file_path = result.get("file_path", "")
                        filename = (
                            file_path.split("/")[-1].split("\\")[-1] if file_path else "价格表.docx"
                        )

                        return {
                            "success": True,
                            "message": result.get("message", "价格表已生成"),
                            "response": f"好的，价格表已生成成功！\n\n{result.get('message', '')}\n\n📄 文件名：{filename}\n💡 已在右侧任务面板中添加下载和打印按钮。",
                            "data": {
                                "file_path": file_path,
                                "download_url": result.get("download_url"),
                                "filename": filename,
                                "product_count": product_count,
                                "intent": "price_list",
                                "action": "tool_call",
                                "tool_key": "price_list",
                            },
                        }
                    else:
                        return {
                            "success": False,
                            "message": result.get("error", "价格表生成失败"),
                            "response": f"抱歉，价格表生成失败：{result.get('error', '未知错误')}",
                        }
                except RECOVERABLE_ERRORS as e:
                    logger.error("价格表生成异常：%s", e, exc_info=True)
                    return {
                        "success": False,
                        "message": f"价格表生成异常：{str(e)}",
                        "response": f"抱歉，价格表生成时出现错误：{str(e)}",
                    }

        # 处理混合模式下的确认/取消
        pending = self._pending_workflows.get(user_id)
        if pending:
            confirm_words = {"确认", "是", "好的", "继续", "执行", "ok", "yes"}
            cancel_words = {"取消", "否", "不要", "停止", "no"}
            if text.lower() in confirm_words or text in confirm_words:
                plan = pending.get("plan")
                runtime_ctx = pending.get("runtime_context", {})
                approval_required = pending.get("approval_required", False)
                approval_nodes = pending.get("approval_nodes", [])

                if approval_required and approval_nodes:
                    for node_info in approval_nodes:
                        node = None
                        for n in plan.nodes:
                            if n.node_id == node_info.get("node_id"):
                                node = n
                                break
                        if node:
                            self.approval_service.create_approval_request(
                                plan_id=plan.plan_id,
                                node=node,
                                runtime_context=runtime_ctx,
                                plan=plan,
                            )

                    approval_inner = {
                        "plan_id": plan.plan_id,
                        "approval_required": True,
                        "approval_nodes": approval_nodes,
                    }
                    return {
                        "success": True,
                        "message": "处理完成",
                        "response": "已提交审批请求，请等待审批完成后继续。",
                        "data": {
                            "text": "已提交审批请求，请等待审批完成后继续。",
                            "action": "approval_pending",
                            "data": _enrich_confirmation_inner(
                                approval_inner, action="approval_pending"
                            ),
                        },
                    }

                agent_run_id = str(pending.get("agent_run_id") or "").strip()
                if agent_run_id:
                    from app.application.agent_orchestrator import AgentOrchestrator

                    agent_run = AgentOrchestrator().continue_run(
                        agent_run_id,
                        approved_by=user_id,
                        runtime_context=runtime_ctx,
                    )
                    self._pending_workflows.pop(user_id, None)
                    if agent_run is not None:
                        return self._format_agent_run_response(
                            plan,
                            agent_run,
                            thinking_steps=str(pending.get("thinking_steps") or ""),
                            user_message=str(runtime_ctx.get("message") or ""),
                        )

                run_result = self.workflow_engine.run(
                    plan=plan, runtime_context=runtime_ctx, max_retries=1
                )
                self._pending_workflows.pop(user_id, None)
                return self._format_workflow_run_response(
                    plan,
                    run_result,
                    user_message=str(runtime_ctx.get("message") or ""),
                )
            if text.lower() in cancel_words or text in cancel_words:
                self._pending_workflows.pop(user_id, None)
                return {
                    "success": True,
                    "message": "处理完成",
                    "response": "已取消本次工作流执行。",
                    "data": {
                        "text": "已取消本次工作流执行。",
                        "action": "workflow_cancelled",
                        "data": {},
                    },
                }

        # 普通工具画像（含「普通界面 + 专业意图」）：未命中槽位时勿走 LLM 工作流规划，避免长时间阻塞在 plan()；
        # 交给下方主对话链路（DeepSeek 等），体验与普通聊天一致。
        if profile == "normal" and not explicit_workflow_tool_intent and not smart_workflow_intent:
            return None

        # 专业界面默认画像：发货单/开单句式与普通版槽位路由一致时，勿让 LLM 工作流规划抢先返回
        # 「我已根据语义生成动态工作流计划…节点 products.query / products.create…」，
        # 否则 Jarvis 收不到主链路里的 shipment_generate / toolCall，用户只看到冗长计划文案。
        if profile == "pro_default":
            rr_pro_ship = route_normal_mode_message(text)
            if rr_pro_ship.get("intent") == "shipment":
                # 订单句若能被 _parse_order_text 结构化，直接下发 shipment_generate / toolCall，
                # 避免再走意图识别（槽位空→追问）或主模型只回文本导致前端从不调用 /api/tools/execute。
                try:
                    from app.application.facades.tools_facade import _parse_order_text

                    parsed_quick = _parse_order_text(text)
                except RECOVERABLE_ERRORS:
                    parsed_quick = {"success": False}
                if parsed_quick.get("success"):
                    # 结构与 _build_tool_call_response 一致，避免把多余键摊进 toolCall.params
                    quick_ai = {
                        "text": "已识别订单，请确认生成发货单。",
                        "action": "tool_call",
                        "data": {
                            "tool_key": "shipment_generate",
                            "intent": "shipment_generate",
                            "slots": {
                                "unit_name": (parsed_quick.get("unit_name") or "").strip(),
                                "products": parsed_quick.get("products") or [],
                            },
                            "hints": [],
                            "habit_suggestion": None,
                        },
                    }
                    return self._build_response(quick_ai, source, text)
                return None

        # 动态规划：不依赖关键词硬编码决策
        from app.application.facades.tools_facade import get_workflow_tool_registry

        tool_registry = get_workflow_tool_registry()
        plan = self.workflow_planner.plan(
            user_id=user_id,
            message=message,
            tool_registry=tool_registry,
            context=context,
        )

        decision = self.risk_gate.evaluate(plan=plan, context=context)
        runtime_ctx = self._merge_tool_runtime_context(user_id, message, context)
        runtime_ctx["source"] = str(source or "").strip()
        runtime_ctx["workflow_trace_mode"] = "agent_orchestrator"
        runtime_ctx["dynamic_workflow"] = True
        thinking_steps = self._build_workflow_thinking_steps(
            plan=plan, decision_reason=decision.reason
        )

        approval_required_nodes = self.approval_service.get_approval_required_nodes(plan)
        has_approval_requirement = bool(approval_required_nodes)
        approval_info = ""
        if has_approval_requirement:
            approval_node_names = [f"{n.tool_id}.{n.action}" for n in approval_required_nodes]
            approval_info = "\n以下操作需要审批后执行：" + "、".join(approval_node_names)

        use_agentic = bool((runtime_ctx.get("excel_analysis") or {}).get("file_path"))
        if not has_approval_requirement and not use_agentic:
            from app.application.agent_orchestrator import AgentOrchestrator

            agent_run = AgentOrchestrator().start_run_from_plan(
                user_id=user_id,
                message=message,
                plan=plan,
                runtime_context=runtime_ctx,
                auto_execute=True,
            )
            if agent_run.status != "waiting_user":
                return self._format_agent_run_response(
                    plan,
                    agent_run,
                    thinking_steps=thinking_steps,
                    user_message=str(message or ""),
                )
            blocking_nodes = [
                step.node_id
                for step in getattr(agent_run, "steps", []) or []
                if step.status == "waiting_user"
            ]
            self._pending_workflows[user_id] = {
                "plan": plan,
                "runtime_context": runtime_ctx,
                "pending_id": uuid.uuid4().hex,
                "agent_run_id": agent_run.run_id,
                "thinking_steps": thinking_steps,
                "approval_required": False,
                "approval_nodes": [],
            }
            todo_text = "\n".join(f"- {step}" for step in (plan.todo_steps or []))
            reason = decision.reason or "工具策略要求用户确认"
            response_text = (
                "我已根据语义生成动态工作流计划：\n"
                f"{thinking_steps}\n\n"
                f"{todo_text}\n\n"
                f"检测到需确认步骤（{', '.join(blocking_nodes) or 'workflow'}），"
                "回复「确认」继续执行，回复「取消」终止。"
            )
            confirm_inner = {
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "thinking_steps": thinking_steps,
                "todo": plan.todo_steps,
                "blocking_nodes": blocking_nodes,
                "reason": reason,
                "approval_required": False,
                "approval_nodes": [],
            }
            return {
                "success": True,
                "message": "处理完成",
                "response": response_text,
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "data": {
                    "text": response_text,
                    "action": "workflow_confirmation_required",
                    "run_id": agent_run.run_id,
                    "agent_run_id": agent_run.run_id,
                    "data": _enrich_confirmation_inner(
                        confirm_inner, action="workflow_confirmation_required"
                    ),
                },
            }

        agent_run_id = ""
        if decision.requires_confirmation and not has_approval_requirement:
            from app.application.agent_orchestrator import AgentOrchestrator

            agent_run = AgentOrchestrator().start_run_from_plan(
                user_id=user_id,
                message=message,
                plan=plan,
                runtime_context=runtime_ctx,
                auto_execute=True,
            )
            if agent_run.status != "waiting_user":
                return self._format_agent_run_response(
                    plan,
                    agent_run,
                    thinking_steps=thinking_steps,
                    user_message=str(message or ""),
                )
            agent_run_id = agent_run.run_id

        if decision.requires_confirmation or has_approval_requirement:
            self._pending_workflows[user_id] = {
                "plan": plan,
                "runtime_context": runtime_ctx,
                "pending_id": uuid.uuid4().hex,
                "agent_run_id": agent_run_id,
                "thinking_steps": thinking_steps,
                "approval_required": has_approval_requirement,
                "approval_nodes": [
                    {
                        "node_id": n.node_id,
                        "tool_id": n.tool_id,
                        "action": n.action,
                        "params": n.params,
                    }
                    for n in approval_required_nodes
                ],
            }
            todo_text = "\n".join(f"- {step}" for step in (plan.todo_steps or []))
            response_text = (
                "我已根据语义生成动态工作流计划：\n"
                f"{thinking_steps}\n\n"
                f"{todo_text}\n\n"
                f"检测到中高风险步骤（{', '.join(decision.blocking_nodes)}），"
                "回复「确认」继续执行，回复「取消」终止。"
                f"{approval_info if has_approval_requirement else ''}"
            )
            risk_inner = {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "thinking_steps": thinking_steps,
                "todo": plan.todo_steps,
                "blocking_nodes": decision.blocking_nodes,
                "reason": decision.reason,
                "approval_required": has_approval_requirement,
                "approval_nodes": [
                    {"node_id": n.node_id, "tool_id": n.tool_id, "action": n.action}
                    for n in approval_required_nodes
                ],
            }
            payload: dict[str, Any] = {
                "success": True,
                "message": "处理完成",
                "response": response_text,
                "data": {
                    "text": response_text,
                    "action": "workflow_confirmation_required",
                    "data": _enrich_confirmation_inner(
                        risk_inner, action="workflow_confirmation_required"
                    ),
                },
            }
            if agent_run_id:
                payload["run_id"] = agent_run_id
                payload["agent_run_id"] = agent_run_id
                payload["data"]["run_id"] = agent_run_id
                payload["data"]["agent_run_id"] = agent_run_id
                payload["data"]["data"]["run_id"] = agent_run_id
                payload["data"]["data"]["agent_run_id"] = agent_run_id
            return payload

        agentic_pre_run = None
        if use_agentic:
            try:
                agentic_pre_run = self._start_agentic_workflow_agent_run(
                    user_id=user_id,
                    message=message,
                    plan=plan,
                    runtime_context=runtime_ctx,
                )
                runtime_ctx["run_id"] = agentic_pre_run.run_id
                runtime_ctx["agent_run_id"] = agentic_pre_run.run_id
            except RECOVERABLE_ERRORS:
                logger.debug("Agentic workflow AgentRun pre-create skipped", exc_info=True)

        run_result = self.workflow_engine.run(
            plan=plan,
            runtime_context=runtime_ctx,
            max_retries=1,
            agentic_loop=use_agentic,
            tool_registry=tool_registry,
            user_id=user_id,
        )
        if use_agentic:
            agent_run = self._bridge_agentic_workflow_result_to_agent_run(
                user_id=user_id,
                message=message,
                plan=plan,
                run_result=run_result,
                runtime_context=runtime_ctx,
                agent_run=agentic_pre_run,
            )
            return self._format_agent_run_response(
                plan,
                agent_run,
                thinking_steps=thinking_steps,
                user_message=str(message or ""),
            )
        return self._format_workflow_run_response(
            plan,
            run_result,
            thinking_steps=thinking_steps,
            user_message=str(message or ""),
        )

    def _build_workflow_thinking_steps(self, plan, decision_reason: str) -> str:
        node_lines = []
        for node in plan.nodes or []:
            deps = ",".join(node.depends_on) if node.depends_on else "无"
            node_lines.append(
                f"- 节点 {node.node_id}: {node.tool_id}.{node.action} "
                f"(risk={node.risk}, depends_on={deps})"
            )
        nodes_text = "\n".join(node_lines) if node_lines else "- 无可执行节点"

        metadata = getattr(plan, "metadata", {}) or {}
        user_memory_rag_summary = str(metadata.get("user_memory_rag_summary") or "").strip()
        memory_v2_summary = str(metadata.get("memory_v2_summary") or "").strip()
        tool_probe_outputs = metadata.get("tool_probe_outputs") or []
        if not isinstance(tool_probe_outputs, list):
            tool_probe_outputs = []

        probe_lines = []
        for item in tool_probe_outputs[:3]:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("tool_id") or "").strip()
            action = str(item.get("action") or "").strip()
            ok = bool(item.get("success"))
            msg = str(item.get("message") or "").strip()
            preview = str(item.get("data_preview") or "").strip()
            if preview:
                preview = preview[:220] + ("…" if len(preview) > 220 else "")
            probe_lines.append(f"- {tid}.{action}: success={ok}; {msg} {preview}".strip())

        memory_block = (
            f"3.5) 用户记忆 RAG 概览:\n{user_memory_rag_summary}\n"
            if user_memory_rag_summary
            else ""
        )
        memory_v2_block = (
            f"3.6) Memory v2 已确认记忆:\n{memory_v2_summary}\n" if memory_v2_summary else ""
        )
        probe_block = (
            "3.7) 工具探测概览:\n"
            + ("\n".join(probe_lines) if probe_lines else "- 无成功探测结果")
            + "\n"
        )
        return (
            "思考步骤:\n"
            f"1) 意图理解: {plan.intent}\n"
            "2) 计划生成: 基于工具注册表构建可执行节点图\n"
            f"3) 风险判断: {decision_reason}\n"
            f"{memory_block}{memory_v2_block}{probe_block}"
            "4) 执行编排: 按依赖顺序执行节点并传递上下文\n"
            f"5) 节点图:\n{nodes_text}"
        )

    def _workflow_products_float_query(self, plan, run_result, user_message: str) -> str:
        """从产品查询节点参数/结果或用户原话中提取副窗搜索词。"""
        for node in plan.nodes or []:
            if node.tool_id == "products" and node.action == "query":
                p = node.params or {}
                q = (
                    str(p.get("keyword") or "").strip()
                    or str(p.get("model_number") or "").strip()
                    or str(p.get("product_name") or p.get("name") or "").strip()
                )
                if q:
                    return q
        for r in run_result.node_results:
            if not r.success or r.tool_id != "products" or r.action != "query":
                continue
            out = r.output or {}
            rows = out.get("data") or []
            if isinstance(rows, list) and rows:
                row = rows[0] if isinstance(rows[0], dict) else {}
                if isinstance(row, dict):
                    m = str(row.get("model_number") or "").strip()
                    n = str(row.get("name") or row.get("product_name") or "").strip()
                    if m:
                        return m
                if n:
                    return n
        return str(user_message or "").strip()

    def _start_agentic_workflow_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan,
        runtime_context: dict[str, Any],
    ):
        from app.application.agent_orchestrator.run_models import AgentRun
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository

        repository = get_agent_run_repository()
        run = AgentRun(
            user_id=str(user_id or ""),
            message=str(message or ""),
            status="running",
            plan_id=str(getattr(plan, "plan_id", "") or ""),
            intent=str(getattr(plan, "intent", "") or "agentic_workflow"),
            metadata={
                "runtime_context": dict(runtime_context or {}),
                "trace_mode": "agentic_loop_bridge",
                "plan": {
                    "todo_steps": list(getattr(plan, "todo_steps", []) or []),
                    "risk_level": str(getattr(plan, "risk_level", "") or ""),
                    "metadata": dict(getattr(plan, "metadata", {}) or {}),
                },
            },
        )
        run.add_event("run.created", "Agentic workflow run 已创建")
        run.add_event(
            "planner.completed",
            "Agentic workflow 计划已接管",
            {
                "plan_id": run.plan_id,
                "intent": run.intent,
                "source": "workflow_engine.agentic_loop",
            },
        )
        run.add_event(
            "agentic_loop.started",
            "Agentic workflow loop 开始执行",
            {"observed": True},
        )
        return repository.save(run)

    def _bridge_agentic_workflow_result_to_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan,
        run_result,
        runtime_context: dict[str, Any],
        agent_run=None,
    ):
        from app.application.agent_orchestrator.run_models import (
            AgentRun,
            AgentStep,
            ToolCall,
            artifact_from_dict,
        )
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        repository = get_agent_run_repository()
        runtime_ctx = dict(runtime_context or {})
        run = agent_run
        if run is None:
            run = AgentRun(
                user_id=str(user_id or ""),
                message=str(message or ""),
                status="running",
                plan_id=str(getattr(plan, "plan_id", "") or ""),
                intent=str(getattr(plan, "intent", "") or "agentic_workflow"),
                metadata={
                    "runtime_context": dict(runtime_ctx),
                    "trace_mode": "agentic_loop_bridge",
                    "plan": {
                        "todo_steps": list(getattr(plan, "todo_steps", []) or []),
                        "risk_level": str(getattr(plan, "risk_level", "") or ""),
                        "metadata": dict(getattr(plan, "metadata", {}) or {}),
                    },
                },
            )
            run.add_event("run.created", "Agentic workflow run 已创建")
            run.add_event(
                "planner.completed",
                "Agentic workflow 计划已接管",
                {
                    "plan_id": run.plan_id,
                    "intent": run.intent,
                    "source": "workflow_engine.agentic_loop",
                },
            )
            run.add_event(
                "agentic_loop.started",
                "Agentic workflow loop 开始执行",
                {"observed": True},
            )
        run.metadata["runtime_context"] = dict(runtime_ctx)
        run.metadata["trace_mode"] = "agentic_loop_bridge"
        run.add_event(
            "agentic_loop.completed",
            str(getattr(run_result, "message", "") or "AgenticLoop 已完成"),
            {"observed": True},
        )

        node_outputs: dict[str, Any] = {}
        for result in getattr(run_result, "node_results", []) or []:
            spec = get_tool_action_spec(result.tool_id, result.action)
            status = "completed" if bool(getattr(result, "success", False)) else "failed"
            step = AgentStep(
                node_id=str(result.node_id or f"agent_{result.tool_id}_{result.action}"),
                tool_id=str(result.tool_id or ""),
                action=str(getattr(spec, "action", "") or result.action or ""),
                params=dict(getattr(result, "params", {}) or {}),
                risk=str(getattr(spec, "risk", "") or "medium"),
                idempotent=bool(getattr(spec, "idempotent", False)),
                description="agentic loop observed tool execution",
                status=status,
                output=dict(getattr(result, "output", {}) or {}),
                error=str(getattr(result, "error", "") or ""),
                started_at=str(getattr(result, "started_at", "") or ""),
                finished_at=str(getattr(result, "finished_at", "") or ""),
                duration_ms=int(getattr(result, "duration_ms", 0) or 0),
            )
            if status == "failed" and not step.error:
                step.error = self._workflow_output_message(step.output) or "tool failed"
            call = ToolCall(
                step_id=step.step_id,
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=dict(step.params or {}),
                status="completed" if status == "completed" else "failed",
                output=dict(step.output or {}),
                error=step.error,
                cost_units=int(getattr(spec, "cost_units", 0) or 0),
                permission=str(getattr(spec, "permission", "") or ""),
                started_at=step.started_at or "",
                finished_at=step.finished_at or "",
                duration_ms=step.duration_ms,
                metadata={
                    "observed": True,
                    "trace_mode": "agentic_loop_bridge",
                    "retryable": bool(getattr(result, "retryable", True)),
                    "retries": int(getattr(result, "retries", 0) or 0),
                    "recovery_hint": str(getattr(result, "recovery_hint", "") or ""),
                },
            )
            run.steps.append(step)
            run.tool_calls.append(call)
            node_outputs[step.node_id] = step.output
            run.add_event(
                "tool.started",
                f"观察到 agentic 工具 {step.tool_id}.{step.action}",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": call.call_id,
                    "cost_units": call.cost_units,
                    "permission": call.permission,
                    "observed": True,
                },
            )
            run.add_event(
                "tool.completed" if status == "completed" else "tool.failed",
                f"记录 agentic 工具 {step.tool_id}.{step.action}",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": call.call_id,
                    "duration_ms": step.duration_ms,
                    "cost_units": call.cost_units,
                    "observed": True,
                    "error": step.error,
                },
            )
            for artifact_payload in self._iter_agentic_artifact_payloads(step.output):
                artifact = artifact_from_dict(artifact_payload)
                if not artifact.artifact_type:
                    continue
                artifact.source = artifact.source or f"{step.tool_id}.{step.action}"
                artifact.metadata = {
                    **dict(artifact.metadata or {}),
                    "step_id": step.step_id,
                    "call_id": call.call_id,
                    "trace_mode": "agentic_loop_bridge",
                }
                run.artifacts.append(artifact)
                run.add_event(
                    "artifact.attached",
                    f"Artifact 已附加: {artifact.artifact_type}",
                    {
                        "artifact_id": artifact.artifact_id,
                        "artifact_type": artifact.artifact_type,
                        "name": artifact.name,
                        "source": artifact.source,
                    },
                )

        cost_units_total = sum(int(call.cost_units or 0) for call in run.tool_calls)
        run.metadata["tool_call_count"] = len(run.tool_calls)
        run.metadata["cost_units_total"] = cost_units_total
        run.metadata["artifact_count"] = len(run.artifacts)
        run.final_output = {
            "node_outputs": node_outputs,
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "artifacts": [artifact.to_dict() for artifact in run.artifacts],
            "cost_units_total": cost_units_total,
            "workflow_result": {
                "success": bool(getattr(run_result, "success", False)),
                "message": str(getattr(run_result, "message", "") or ""),
                "workflow_status": dict(
                    (getattr(run_result, "final_context", {}) or {}).get("workflow_status") or {}
                ),
            },
        }
        run.status = "completed" if bool(getattr(run_result, "success", False)) else "failed"
        if run.status == "failed":
            run.error = str(getattr(run_result, "message", "") or "Agentic workflow failed")
            run.add_event("run.failed", run.error, run.final_output)
        else:
            run.add_event("run.completed", "Agentic workflow run 执行完成", run.final_output)
        return repository.save(run)

    @staticmethod
    def _iter_agentic_artifact_payloads(output: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(output, dict):
            return []
        artifacts = output.get("artifacts")
        if artifacts is None:
            artifacts = output.get("artifact")
        if isinstance(artifacts, dict):
            return [artifacts]
        if isinstance(artifacts, list):
            return [item for item in artifacts if isinstance(item, dict)]
        return []

    @staticmethod
    def _agent_plan_can_auto_execute(plan) -> bool:
        nodes = getattr(plan, "nodes", None)
        if not isinstance(nodes, (list, tuple)) or not nodes:
            return False
        try:
            from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        except RECOVERABLE_ERRORS:
            return False
        for node in nodes:
            spec = get_tool_action_spec(getattr(node, "tool_id", ""), getattr(node, "action", ""))
            risk = str(getattr(spec, "risk", "") or getattr(node, "risk", "") or "").lower()
            idempotent = bool(getattr(spec, "idempotent", getattr(node, "idempotent", False)))
            if risk != "low" or not idempotent:
                return False
        return True

    def _dispatch_workflow_tool(
        self, tool_id: str, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            from app.application.facades.tools_facade import execute_registered_workflow_tool

            return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)
        except RECOVERABLE_ERRORS as err:
            logger.error(
                "workflow 工具调度失败 tool=%s action=%s err=%s",
                tool_id,
                action,
                err,
                exc_info=True,
            )
            return {"success": False, "message": str(err)}

    def _handle_confirmation_flow(
        self, user_id: str, message: str, file_context: dict[str, Any] | None
    ) -> None:
        """处理确认流程"""
        if not file_context:
            return

        if message not in ("是", "好的", "确认", "yes", "ok", "好"):
            return

        saved_name = file_context.get("saved_name")
        unit_name = file_context.get("unit_name_guess") or file_context.get("unit_name", "")
        suggested_use = file_context.get("suggested_use", "")

        if saved_name and suggested_use == "unit_products_db" and unit_name:
            self.ai_service.set_pending_confirmation(
                user_id,
                {
                    "type": "import_unit_products",
                    "tool_key": "sqlite_import_unit_products",
                    "params": {
                        "saved_name": saved_name,
                        "unit_name": unit_name,
                    },
                    "description": f"导入 {unit_name} 的产品",
                },
            )
            logger.info("用户 %s 确认导入文件：%s -> %s", user_id, saved_name, unit_name)

    def _build_response(
        self, ai_result: dict[str, Any], source: str | None, original_message: str = ""
    ) -> dict[str, Any]:
        """构建响应数据"""
        response_data = {
            "success": True,
            "message": "处理完成",
            "data": {
                "text": ai_result.get("text", ""),
                "action": ai_result.get("action", ""),
                "data": ai_result.get("data", {}) or {},
            },
        }
        response_data["response"] = ai_result.get("text", "")

        action = ai_result.get("action")
        result_data = ai_result.get("data") or {}

        if action == "tool_call" and result_data:
            response_data = self._handle_tool_call(
                response_data, ai_result, result_data, source, original_message
            )
        else:
            if action == "followup":
                response_data["followup"] = result_data
            if action == "auto_action" and result_data:
                response_data["autoAction"] = result_data

        return response_data

    def _handle_tool_call(
        self,
        response_data: dict[str, Any],
        ai_result: dict[str, Any],
        result_data: dict[str, Any],
        source: str | None,
        original_message: str = "",
    ) -> dict[str, Any]:
        """处理工具调用响应"""
        tool_key = result_data.get("tool_key")
        parsed_params = result_data.get("params") or {}
        slots = result_data.get("slots", {})

        if not tool_key:
            response_data["response"] = ai_result.get("text", "")
            response_data["data"]["data"] = result_data.get("data", {}) or {}
            return response_data

        if self._is_pro_source(source):
            response_data = self._execute_pro_mode_tools(
                response_data, tool_key, slots, parsed_params, ai_result, original_message
            )
        else:
            response_data = self._execute_normal_mode_tools(
                response_data,
                tool_key,
                parsed_params,
                ai_result,
                result_data,
                slots=slots,
                original_message=original_message,
            )

        return response_data


def get_ai_chat_app_service() -> AIChatApplicationService:
    """获取 AI 聊天应用服务单例"""
    return get_service_registry().ai_chat_application_service
