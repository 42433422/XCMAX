# ruff: noqa: E402, F401
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

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx  # noqa: F401 - compatibility patch point for legacy tests/callers

if TYPE_CHECKING:
    # 仅用于类型标注；运行时经注入端口或 ``app.bootstrap`` 触发式解析，避免 import 期耦合。
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.workflow.ports.checkpoint import CheckpointStore
    from app.application.workflow.ports.runtime import WorkflowRuntime
    from app.application.workflow.types import PlanGraph, WorkflowRunResult
else:
    CheckpointStore = Any
    WorkflowRuntime = Any

from app.di.registry import get_service_registry
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import resolve_fhd_repo_root

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


from app.application.ai_chat.agent_workflow_bridge import AgentWorkflowBridge
from app.application.ai_chat.context_enrichment import (
    inject_excel_vector_context,
    inject_wechat_contact_context,
)
from app.application.ai_chat.conversation_history import (
    persist_chat_turn,
    persist_recallable_chat_turn,
)
from app.application.ai_chat.import_workflow_admission import ImportWorkflowAdmission
from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
from app.application.ai_chat.workflow_session import WorkflowSession


def _workflow_component(name: str):
    """Resolve established public patch points only at the composition boundary."""
    return globals()[name] if name in globals() else __getattr__(name)


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

    _HEADER_HINT_RE = re.compile(
        r"(产品|名称|规格|型号|编号|单价|价格|调价|金额|单位|客户|厂名|品名)"
    )

    def __init__(
        self,
        workflow_runtime: WorkflowRuntime | None = None,
        workflow_checkpointer: CheckpointStore | None = None,
    ):
        self.ai_service = get_ai_conversation_service()
        self.workflow_planner = _workflow_component("LLMWorkflowPlanner")()
        self.risk_gate = _workflow_component("HybridRiskGate")()
        if workflow_runtime is None:
            from app.bootstrap import get_workflow_runtime

            workflow_runtime = get_workflow_runtime()
        self.workflow_engine = workflow_runtime
        if workflow_checkpointer is None:
            from app.bootstrap import get_workflow_checkpointer

            workflow_checkpointer = get_workflow_checkpointer()
        self.workflow_checkpointer = workflow_checkpointer
        self.approval_service = _workflow_component("get_approval_service")()
        self._pending_workflows: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _is_pro_source(source: str | None) -> bool:
        """兼容 pro 来源字段的多种写法（与 fastapi_routes.ai_chat._is_pro_source 对齐）。"""
        normalized = str(source or "").strip().lower().replace("-", "_")
        return normalized in {"pro", "pro_mode", "promode", "professional", "xcagi_pro"}

    @staticmethod
    def _is_pure_casual_chat(text: str) -> bool:
        """无业务槽位时回落普通聊天。"""
        from app.application.normal_chat_dispatch import route_normal_mode_message

        return route_normal_mode_message(str(text or "")).get("intent") == "unknown"

    @staticmethod
    def _merge_tool_runtime_context(
        user_id: str, message: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        runtime_ctx: dict[str, Any] = {"user_id": user_id, "message": message}
        AIChatWorkflowResponseMixin._attach_task_tenant(runtime_ctx)
        if isinstance(context, dict):
            for key in (
                "session_id",
                "conversation_id",
                "turn_id",
                "task_id",
                "local_user_id",
                "actor_id",
                "mod_id",
                "active_mod_id",
            ):
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
        context: dict[str, Any] | None = None,
        source: str | None = None,
        file_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not message:
            return {"success": False, "message": "消息内容不能为空"}
        from app.application.agent_task_context import scoped_conversation_user_id

        context = dict(context or {})
        context.setdefault("conversation_id", context.get("session_id") or user_id)
        user_id = scoped_conversation_user_id(user_id, context)
        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_received

            neuro_notify_chat_received(user_id, message, source)
        except RECOVERABLE_ERRORS:
            logger.debug("neuro_notify_chat_received skipped", exc_info=True)
        from app.application.agent_orchestrator.business_harness import (
            ensure_business_harness_context,
        )

        ctx = ensure_business_harness_context(context, message=message)
        ctx = self._inject_excel_vector_context(message=message, context=ctx)
        ctx = self._inject_wechat_contact_context(message=message, context=ctx)
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
                    user_id=user_id, message=message, source=source, context=ctx, response_data=resp
                )
            except RECOVERABLE_ERRORS as memory_err:
                logger.warning("跨会话记忆写入失败（已返回对话结果）: %s", memory_err)
            return resp

        from app.application.ai_chat.workflow_session import (
            CANCEL_WORDS,
            CONFIRM_WORDS,
        )

        if message.strip().lower().rstrip("。.!！") in CONFIRM_WORDS | CANCEL_WORDS:
            self._handle_confirmation_flow(user_id, message, file_context)
            control_response = self._try_handle_dynamic_workflow(
                user_id, message, source, ctx, file_context or {}
            )
            assert control_response is not None
            return _finalize(control_response)

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

            fhd_root = resolve_fhd_repo_root(anchor=Path(__file__).resolve())
            deterministic_reply = try_deterministic_chat_reply(
                message, runtime_context=ctx, workspace_root=str(fhd_root) if fhd_root else None
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
                    "action": str(deterministic_reply.get("action") or "deterministic_reply"),
                    "data": {
                        "intent": str(
                            deterministic_reply.get("trace_intent") or "deterministic_chat_reply"
                        ),
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
                    intent=str(
                        deterministic_reply.get("trace_intent") or "deterministic_chat_reply"
                    ),
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
        except RECOVERABLE_ERRORS:
            logger.debug("legacy chat AgentRun pre-create skipped", exc_info=True)
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
        except RECOVERABLE_ERRORS:
            logger.exception("AI 服务处理异常")
            loop.close()
            return _finalize(
                self._build_fallback_response(message, "AI 服务暂时不可用，请稍后重试")
            )
        finally:
            loop.close()
        logger.info(
            "用户 %s 消息：%s... -> %s", user_id, message[:50], ai_result.get("action", "unknown")
        )
        response_data = self._build_response(ai_result, source, message)
        return _finalize(response_data)

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

    @classmethod
    def _row_values_look_like_table_headers(cls, values: list[str]) -> bool:
        non_empty = [v for v in values if str(v or "").strip()]
        if len(non_empty) < 2:
            return False
        hits = len([v for v in non_empty if cls._HEADER_HINT_RE.search(str(v))])
        return hits >= 2 and hits >= max(2, len(non_empty) // 3)

    def _try_handle_multimodal_chat(
        self, *, user_id: str, message: str, source: str | None, context: dict[str, Any]
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
                user_id=user_id, message=message, runtime_context=runtime_ctx
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

    # These operations only consume explicit request/record inputs; no inheritance
    # or mutable application-service state is required to persist or enrich a turn.
    _persist_chat_turn = staticmethod(persist_chat_turn)
    _persist_recallable_chat_turn = staticmethod(persist_recallable_chat_turn)
    _inject_excel_vector_context = staticmethod(inject_excel_vector_context)
    _inject_wechat_contact_context = staticmethod(inject_wechat_contact_context)

    def _workflow_session(self) -> WorkflowSession:
        return WorkflowSession(
            self._pending_workflows,
            self,
            runtime=getattr(self, "workflow_engine", None),
            checkpointer=getattr(self, "workflow_checkpointer", None),
            approval=getattr(self, "approval_service", None),
        )

    def _agent_workflow_bridge(self) -> AgentWorkflowBridge:
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository

        return AgentWorkflowBridge(
            get_agent_run_repository(),
            self._workflow_output_message,
            self._iter_agentic_artifact_payloads,
        )

    _iter_agentic_artifact_payloads = staticmethod(AgentWorkflowBridge.iter_artifact_payloads)
    _agent_plan_can_auto_execute = staticmethod(AgentWorkflowBridge.plan_can_auto_execute)

    def _hydrate_pending_workflow(self, user_id: str, session_id: str) -> bool:
        return self._workflow_session().hydrate_pending_workflow(user_id, session_id)

    def _persist_plan_state(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None,
        status: str,
        message: str | None = None,
    ) -> bool:
        return self._workflow_session().persist_plan_state(plan, runtime_context, status, message)

    def _run_workflow_with_state_updates(
        self,
        *,
        plan: PlanGraph,
        runtime_context: dict[str, Any],
        max_retries: int = 1,
        resume: bool = False,
        **kwargs: Any,
    ) -> tuple[Any, list[dict[str, Any]]]:
        return self._workflow_session().run_workflow_with_state_updates(
            plan=plan,
            runtime_context=runtime_context,
            max_retries=max_retries,
            resume=resume,
            **kwargs,
        )

    def _sweep_expired_clarifications(self) -> list[str]:
        return self._workflow_session().sweep_expired_clarifications()

    def _open_clarification_gate(
        self,
        *,
        user_id: str,
        plan: PlanGraph,
        tool_registry: dict[str, Any],
        runtime_context: dict[str, Any],
        thinking_steps: str,
        message: str,
    ) -> dict[str, Any] | None:
        return self._workflow_session().open_clarification_gate(
            user_id=user_id,
            plan=plan,
            tool_registry=tool_registry,
            runtime_context=runtime_context,
            thinking_steps=thinking_steps,
            message=message,
        )

    def _continue_after_clarification(
        self, user_id: str, pending: dict[str, Any], message: str
    ) -> dict[str, Any] | None:
        return self._workflow_session().continue_after_clarification(user_id, pending, message)

    def _resume_pending_dynamic_workflow(
        self, user_id: str, message: str, text: str, context: dict[str, Any] | None = None
    ) -> tuple[bool, dict[str, Any] | None]:
        return self._workflow_session().resume_pending_dynamic_workflow(
            user_id, message, text, context
        )

    def _start_agentic_workflow_agent_run(
        self, *, user_id: str, message: str, plan: PlanGraph, runtime_context: dict[str, Any]
    ) -> AgentRun:
        return self._agent_workflow_bridge().start_run(
            user_id=user_id, message=message, plan=plan, runtime_context=runtime_context
        )

    def _bridge_agentic_workflow_result_to_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan: PlanGraph,
        run_result: WorkflowRunResult,
        runtime_context: dict[str, Any],
        agent_run: AgentRun | None = None,
    ) -> AgentRun:
        return self._agent_workflow_bridge().record_result(
            user_id=user_id,
            message=message,
            plan=plan,
            run_result=run_result,
            runtime_context=runtime_context,
            agent_run=agent_run,
        )

    def _try_handle_dynamic_workflow(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        file_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        return ImportWorkflowAdmission(self._pending_workflows, self).handle(
            user_id, message, source, context, file_context
        )

    def _try_handle_dynamic_workflow_after_excel(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        text: str,
        explicit_workflow_tool_intent: bool,
    ) -> dict[str, Any] | None:
        return PlannedWorkflowDispatch(
            self._pending_workflows,
            self,
            self.workflow_planner,
            self.risk_gate,
            self.approval_service,
        ).handle(user_id, message, source, context, text, explicit_workflow_tool_intent)

    def _dispatch_workflow_tool(
        self, tool_id: str, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            from app.application.facades.tools_facade import execute_registered_workflow_tool

            return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)
        except RECOVERABLE_ERRORS:
            logger.exception("workflow 工具调度失败")
            return {"success": False, "message": "工作流工具调度失败"}

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
                    "params": {"saved_name": saved_name, "unit_name": unit_name},
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
                response_data, tool_key, parsed_params, ai_result, result_data, original_message
            )
        return response_data


def get_ai_chat_app_service() -> AIChatApplicationService:
    """获取 AI 聊天应用服务单例"""
    return get_service_registry().ai_chat_application_service
