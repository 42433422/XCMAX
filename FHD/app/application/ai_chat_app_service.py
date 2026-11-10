# ruff: noqa: F401
"""Unified chat application service for dialogue and LangGraph business turns."""

from __future__ import annotations

import copy
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # 仅用于类型标注；运行时经注入端口或 ``app.bootstrap`` 触发式解析，避免 import 期耦合。
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.workflow.workflow_types import PlanGraph

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
from app.application.ai_chat.workflow_response_builder import AIChatWorkflowResponseMixin


def _import_workflow_components():
    from app.application.workflow import (
        HybridRiskGate,
        LLMWorkflowPlanner,
        get_approval_service,
    )
    from app.services import get_ai_conversation_service

    return get_ai_conversation_service, HybridRiskGate, LLMWorkflowPlanner, get_approval_service


# 单测通过 ``patch("app.application.ai_chat_app_service.LLMWorkflowPlanner")`` 等方式
# 替换工作流组件；这些符号不能在模块顶层 ``from app.application.workflow import``，
# 否则会重新引入与 ``app.application.workflow.planner`` 的循环 import（见 commit
# ed1f6e7e0）。PEP 562 模块级 ``__getattr__`` 在属性未在 ``__dict__`` 时才触发，
# 既能让 ``mock.patch`` 取到原始值，又不会在 import 期触发循环。
_LAZY_WORKFLOW_RE_EXPORTS = (
    "get_ai_conversation_service",
    "HybridRiskGate",
    "LLMWorkflowPlanner",
    "get_approval_service",
)


def __getattr__(name: str):
    if name in _LAZY_WORKFLOW_RE_EXPORTS:
        get_ai_conversation_service, HybridRiskGate, LLMWorkflowPlanner, get_approval_service = (
            _import_workflow_components()
        )
        globals().update(
            get_ai_conversation_service=get_ai_conversation_service,
            HybridRiskGate=HybridRiskGate,
            LLMWorkflowPlanner=LLMWorkflowPlanner,
            get_approval_service=get_approval_service,
        )
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
):
    """
    统一聊天应用服务：平台模型负责回复与业务计划，LangGraph 执行已校验的业务图。
    """

    _HEADER_HINT_RE = re.compile(
        r"(产品|名称|规格|型号|编号|单价|价格|调价|金额|单位|客户|厂名|品名)"
    )

    def __init__(self):
        ai_service = _workflow_component("get_ai_conversation_service")()
        self.workflow_planner = _workflow_component("LLMWorkflowPlanner")(ai_service=ai_service)
        self.risk_gate = _workflow_component("HybridRiskGate")()
        self.approval_service = _workflow_component("get_approval_service")()
        self._pending_workflows: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _merge_tool_runtime_context(
        user_id: str, message: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        runtime_ctx: dict[str, Any] = {
            "conversation_id": user_id,
            "message": message,
        }
        AIChatWorkflowResponseMixin._attach_task_tenant(runtime_ctx)
        if isinstance(context, dict):
            for key in (
                "session_id",
                "conversation_id",
                "turn_id",
                "task_id",
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
            for key in (
                "file_context",
                "file_analysis",
                "multimodal_attachments",
                "attachments",
                "files",
                "artifacts",
                "ocr",
                "ocr_result",
                "generated_document",
                "excel_index_id",
                "excel_vector_index_id",
                "dataset_id",
                "dataset_version",
                "dataset_top_k",
                "rag_top_k",
                "include_answer",
                "rerank",
                "rag_rerank",
                "metadata_filter",
                "chat_db_read_authorized",
                "chat_knowledge_dataset_ids",
            ):
                if key in context and context[key] is not None:
                    runtime_ctx[key] = copy.deepcopy(context[key])
        if isinstance(context, dict) and context.get("_actor_authorization") is not None:
            from copy import deepcopy

            from app.application.agent_orchestrator.runtime_context import (
                RuntimeContextOwnershipError,
            )
            from app.infrastructure.auth.agent_mod_scope import validate_actor_context

            if validate_actor_context(context) is not None:
                raise RuntimeContextOwnershipError("工具任务的原登录身份已失效")
            # Conversation identifiers are not business principals. Preserve the
            # original server-bound actor through the delegate, never re-sign it.
            for key in (
                "user_id",
                "actor_id",
                "local_user_id",
                "tenant_id",
                "_actor_authorization",
                "_mod_authorization",
                "mutation_policy",
                "_bulk_preview_scopes",
                "idempotency_key",
            ):
                if key in context:
                    runtime_ctx[key] = deepcopy(context[key])
                else:
                    runtime_ctx.pop(key, None)
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
            "etl",
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
        ctx = self._inject_excel_vector_context(message=message, context=ctx)
        ctx = self._inject_wechat_contact_context(message=message, context=ctx)

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

        workflow_result = self._try_handle_dynamic_workflow(
            user_id=user_id,
            message=message,
            source=source,
            context=ctx,
            file_context=file_context or {},
        )
        if workflow_result is None:
            workflow_result = {
                "success": False,
                "execution_state": "failed",
                "message": "平台模型未返回有效回复或业务计划，本轮没有执行操作。",
                "response": "平台模型未返回有效回复或业务计划，本轮没有执行操作。请重试。",
                "data": {
                    "action": "model_output_unavailable",
                    "error_code": "model_output_unavailable",
                    "execution_started": False,
                },
            }
        return _finalize(workflow_result)

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
            approval=getattr(self, "approval_service", None),
        )

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

    def _sweep_expired_clarifications(self) -> list[str]:
        return self._workflow_session().sweep_expired_clarifications()

    def _capture_agent_run_interaction(
        self,
        *,
        user_id: str,
        agent_run: AgentRun,
        runtime_context: dict[str, Any],
        thinking_steps: str = "",
        decision_reason: str = "",
        approval_nodes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        return self._workflow_session().capture_agent_run_interaction(
            user_id=user_id,
            agent_run=agent_run,
            runtime_context=runtime_context,
            thinking_steps=thinking_steps,
            decision_reason=decision_reason,
            approval_nodes=approval_nodes,
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

    def _dispatch_model_selection(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        text: str,
    ) -> dict[str, Any] | None:
        return PlannedWorkflowDispatch(
            self._pending_workflows,
            self,
            self.workflow_planner,
            self.risk_gate,
            self.approval_service,
        ).handle(user_id, message, source, context, text)


def get_ai_chat_app_service() -> AIChatApplicationService:
    """获取 AI 聊天应用服务单例"""
    return get_service_registry().ai_chat_application_service
