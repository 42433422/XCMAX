"""Dependency assembly for the AI chat application facade."""

from __future__ import annotations

from typing import Any, Callable

from app.application.ai_chat.agentic_workflow_service import AIChatAgenticWorkflowService
from app.application.ai_chat.chat_support_service import AIChatSupportService
from app.application.ai_chat.compatibility import FacadeCompatibilityProxy
from app.application.ai_chat.dynamic_workflow_coordinator import AIChatDynamicWorkflowCoordinator
from app.application.ai_chat.dynamic_workflow_imports import AIChatDynamicImportUseCases
from app.application.ai_chat.dynamic_workflow_planner import AIChatWorkflowPlannerExecutor
from app.application.ai_chat.dynamic_workflow_profiles import AIChatWorkflowProfileRouter
from app.application.ai_chat.excel_import_pipeline import AIChatExcelImportService
from app.application.ai_chat.instant_tools import AIChatInstantToolService
from app.application.ai_chat.response_coordinator import AIChatResponseCoordinator
from app.application.ai_chat.workflow_response_builder import AIChatWorkflowResponseBuilder
from app.application.ai_chat.workflow_tool_dispatcher import AIChatWorkflowToolDispatcher
from app.application.workflow import WorkflowEngine


def assemble_ai_chat_components(
    *,
    ai_service: Any,
    workflow_planner: Any,
    risk_gate: Any,
    approval_service: Any,
    pending_workflows: dict[str, dict[str, Any]],
    is_pro_source: Callable[[str | None], bool],
    merge_tool_runtime_context: Callable[..., dict[str, Any]],
    resolve_unit_price_column: Callable[..., tuple[str, str | None]],
    facade_type: type[Any],
    workflow_engine: Any | None = None,
) -> tuple[Any, tuple[Any, ...]]:
    tool_dispatcher = AIChatWorkflowToolDispatcher()
    engine = workflow_engine or WorkflowEngine(tool_dispatcher=tool_dispatcher.dispatch)
    agentic = AIChatAgenticWorkflowService()
    compat_agentic = FacadeCompatibilityProxy(facade_type, agentic)
    workflow_responses = AIChatWorkflowResponseBuilder(
        products_float_query=agentic._workflow_products_float_query
    )
    compat_workflow_responses = FacadeCompatibilityProxy(facade_type, workflow_responses)
    agentic.bind_output_message(workflow_responses._workflow_output_message)
    excel_import = AIChatExcelImportService(
        ai_service=ai_service,
        merge_tool_runtime_context=merge_tool_runtime_context,
        is_number_text=AIChatSupportService._is_number_text,
        row_values_look_like_table_headers=AIChatSupportService._row_values_look_like_table_headers,
        resolve_unit_price_column=resolve_unit_price_column,
        format_agent_run_response=workflow_responses._format_agent_run_response,
        pending_workflows=pending_workflows,
        facade_type=facade_type,
    )
    compat_excel_import = FacadeCompatibilityProxy(facade_type, excel_import)
    support = AIChatSupportService(
        start_deterministic_import_agent_run=compat_excel_import._start_deterministic_import_agent_run
    )
    instant_tools = AIChatInstantToolService()
    responses = AIChatResponseCoordinator(
        ai_service=ai_service,
        instant_tools=instant_tools,
        is_pro_source=is_pro_source,
    )
    import_use_cases = AIChatDynamicImportUseCases(
        excel_import=compat_excel_import,
        build_workflow_thinking_steps=compat_agentic._build_workflow_thinking_steps,
    )
    profile_router = AIChatWorkflowProfileRouter(
        pending_workflows=pending_workflows,
        approval_service=approval_service,
        workflow_engine=engine,
        format_agent_run_response=compat_workflow_responses._format_agent_run_response,
        format_workflow_run_response=compat_workflow_responses._format_workflow_run_response,
        build_response=responses._build_response,
    )
    planner_executor = AIChatWorkflowPlannerExecutor(
        workflow_planner=workflow_planner,
        risk_gate=risk_gate,
        approval_service=approval_service,
        workflow_engine=engine,
        pending_workflows=pending_workflows,
        merge_tool_runtime_context=merge_tool_runtime_context,
        build_workflow_thinking_steps=compat_agentic._build_workflow_thinking_steps,
        format_agent_run_response=compat_workflow_responses._format_agent_run_response,
        format_workflow_run_response=compat_workflow_responses._format_workflow_run_response,
        start_agentic_workflow_agent_run=agentic._start_agentic_workflow_agent_run,
        bridge_agentic_workflow_result_to_agent_run=agentic._bridge_agentic_workflow_result_to_agent_run,
    )
    dynamic_workflow = AIChatDynamicWorkflowCoordinator(
        excel_import=compat_excel_import,
        import_use_cases=import_use_cases,
        profile_router=profile_router,
        planner_executor=planner_executor,
        pending_workflows=pending_workflows,
        is_pro_source=is_pro_source,
    )
    return engine, (
        support,
        responses,
        dynamic_workflow,
        import_use_cases,
        profile_router,
        planner_executor,
        excel_import,
        agentic,
        workflow_responses,
        instant_tools,
        tool_dispatcher,
    )


__all__ = ["assemble_ai_chat_components"]
