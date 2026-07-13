"""AI chat facade composing import, workflow, response, and tracing services."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx  # noqa: F401 - retained as a public patch point for extensions

from app.application.ai_chat.compatibility import install_ai_chat_compatibility_surface
from app.application.ai_chat.excel_import_policy import (
    _EXCEL_IMPORT_MEASURE_UNIT_TOKENS,
    _skip_pro_excel_deterministic_import,
)
from app.application.ai_chat.service_assembly import assemble_ai_chat_components
from app.application.workflow import (
    HybridRiskGate,
    LLMWorkflowPlanner,
    WorkflowEngine,  # noqa: F401 - retained as a public patch point for extensions
    get_approval_service,
)
from app.di.registry import get_service_registry
from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import resolve_fhd_repo_root

logger = logging.getLogger(__name__)


class AIChatApplicationService:
    """Stable chat use-case facade backed by explicit collaborators."""

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        components = self.__dict__.get("_components")
        if (
            (not name.startswith("_") and name != "ai_service")
            or name in {"_components", "_pending_workflows"}
            or components is None
        ):
            return
        for component in components:
            targets = (component, *getattr(component, "_components", ()))
            for target in targets:
                owns_name = name in getattr(target, "__dict__", {}) or any(
                    name in cls.__dict__ for cls in type(target).__mro__
                )
                if owns_name:
                    setattr(target, name, value)
                if name == "ai_service" and "_ai_service" in getattr(target, "__dict__", {}):
                    target._ai_service = value

    def __init__(self) -> None:
        self.ai_service = get_ai_conversation_service()
        self.workflow_planner = LLMWorkflowPlanner()
        self.risk_gate = HybridRiskGate()
        self.approval_service = get_approval_service()
        self._pending_workflows: dict[str, dict[str, Any]] = {}
        self.workflow_engine, self._components = assemble_ai_chat_components(
            ai_service=self.ai_service,
            workflow_planner=self.workflow_planner,
            risk_gate=self.risk_gate,
            approval_service=self.approval_service,
            pending_workflows=self._pending_workflows,
            is_pro_source=self._is_pro_source,
            merge_tool_runtime_context=self._merge_tool_runtime_context,
            resolve_unit_price_column=lambda *args: type(self)._resolve_unit_price_column(*args),
            facade_type=type(self),
        )

    def __getattr__(self, name: str) -> Any:
        state = object.__getattribute__(self, "__dict__")
        components = state.get("_components")
        if components is None:
            ai_service = state.get("ai_service") or get_ai_conversation_service()
            workflow_planner = state.get("workflow_planner") or LLMWorkflowPlanner()
            risk_gate = state.get("risk_gate") or HybridRiskGate()
            approval_service = state.get("approval_service") or get_approval_service()
            pending_workflows = state.setdefault("_pending_workflows", {})
            engine, components = assemble_ai_chat_components(
                ai_service=ai_service,
                workflow_planner=workflow_planner,
                risk_gate=risk_gate,
                approval_service=approval_service,
                pending_workflows=pending_workflows,
                is_pro_source=self._is_pro_source,
                merge_tool_runtime_context=self._merge_tool_runtime_context,
                resolve_unit_price_column=lambda *args: type(self)._resolve_unit_price_column(
                    *args
                ),
                facade_type=type(self),
                workflow_engine=state.get("workflow_engine"),
            )
            state.setdefault("ai_service", ai_service)
            state.setdefault("workflow_planner", workflow_planner)
            state.setdefault("risk_gate", risk_gate)
            state.setdefault("approval_service", approval_service)
            state.setdefault("workflow_engine", engine)
            state["_components"] = components
        for component in components:
            try:
                return getattr(component, name)
            except AttributeError:
                continue
        raise AttributeError(name)

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


def get_ai_chat_app_service() -> AIChatApplicationService:
    """获取 AI 聊天应用服务单例"""
    return get_service_registry().ai_chat_application_service


install_ai_chat_compatibility_surface(AIChatApplicationService)


__all__ = [
    "AIChatApplicationService",
    "_EXCEL_IMPORT_MEASURE_UNIT_TOKENS",
    "_skip_pro_excel_deterministic_import",
    "get_ai_chat_app_service",
]
