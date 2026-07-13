"""Compatibility adapters for the former monolithic chat service surface."""

from __future__ import annotations

from typing import Any


class ComponentMethod:
    """Expose a composed method on instances while remaining class-patchable."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(self, instance: Any, owner: type[Any]) -> Any:
        if instance is None:
            return self
        return instance.__getattr__(self.name)


class FacadeCompatibilityProxy:
    """Resolve patched facade methods first, then the composed collaborator."""

    def __init__(self, facade_type: type[Any], component: Any) -> None:
        self._facade_type = facade_type
        self._component = component

    def __getattr__(self, name: str) -> Any:
        def invoke(*args: Any, **kwargs: Any) -> Any:
            facade_attr = vars(self._facade_type).get(name)
            if facade_attr is None or isinstance(facade_attr, ComponentMethod):
                return getattr(self._component, name)(*args, **kwargs)
            return getattr(self._facade_type, name)(*args, **kwargs)

        return invoke


def install_ai_chat_compatibility_surface(facade: type[Any]) -> None:
    """Install the stable private extension surface without host inheritance."""
    from app.application.ai_chat.agentic_workflow_service import AIChatAgenticWorkflowService
    from app.application.ai_chat.chat_support_service import AIChatSupportService
    from app.application.ai_chat.excel_import_column_inference import ExcelImportColumnInferer
    from app.application.ai_chat.excel_import_context import ExcelImportContextResolver
    from app.application.ai_chat.excel_import_intent import ExcelImportIntentMatcher
    from app.application.ai_chat.excel_import_price_resolution import ExcelImportPriceResolver
    from app.application.ai_chat.excel_import_trace import ExcelImportTraceService
    from app.application.ai_chat.workflow_response_builder import AIChatWorkflowResponseBuilder

    context = ExcelImportContextResolver()
    intents = ExcelImportIntentMatcher()
    columns = ExcelImportColumnInferer(
        ai_service=None,
        is_number_text=AIChatSupportService._is_number_text,
    )
    prices = ExcelImportPriceResolver()
    static_methods = {
        "_attach_deterministic_workflow_trace": ExcelImportTraceService._attach_deterministic_workflow_trace,
        "_build_fallback_response": AIChatSupportService._build_fallback_response,
        "_customer_hint_from_preview_grid": context._customer_hint_from_preview_grid,
        "_excel_analysis_payload_present": intents._excel_analysis_payload_present,
        "_excel_cell_looks_like_product_measure_unit": context._excel_cell_looks_like_product_measure_unit,
        "_guess_default_purchase_unit": context._guess_default_purchase_unit,
        "_header_hint_column_roles": columns._header_hint_column_roles,
        "_is_number_text": AIChatSupportService._is_number_text,
        "_iter_agentic_artifact_payloads": AIChatAgenticWorkflowService._iter_agentic_artifact_payloads,
        "_agent_plan_can_auto_execute": AIChatAgenticWorkflowService._agent_plan_can_auto_execute,
        "_looks_like_explicit_workflow_tool_intent": intents._looks_like_explicit_workflow_tool_intent,
        "_looks_like_short_excel_import_command": intents._looks_like_short_excel_import_command,
        "_merge_user_intent_for_price_resolution": prices._merge_user_intent_for_price_resolution,
        "_model_like_score": columns._model_like_score,
        "_normal_slot_dispatch_chat_overlay": AIChatWorkflowResponseBuilder._normal_slot_dispatch_chat_overlay,
        "_packaging_or_measure_ratio": columns._packaging_or_measure_ratio,
        "_price_column_buckets": prices._price_column_buckets,
        "_resolve_excel_path_for_import": context._resolve_excel_path_for_import,
        "_resolve_force_header_row_1based": context._resolve_force_header_row_1based,
        "_resolve_sheet_name_for_reimport": context._resolve_sheet_name_for_reimport,
        "_resolve_unit_price_column": prices._resolve_unit_price_column,
        "_row_values_look_like_table_headers": AIChatSupportService._row_values_look_like_table_headers,
        "_sanitize_import_scalar": context._sanitize_import_scalar,
        "_try_structured_reload_records": context._try_structured_reload_records,
        "_workflow_output_message": AIChatWorkflowResponseBuilder._workflow_output_message,
        "_workflow_output_preview": AIChatWorkflowResponseBuilder._workflow_output_preview,
    }
    for name, method in static_methods.items():
        setattr(facade, name, staticmethod(method))

    def default_purchase_unit(
        excel_analysis: dict[str, Any],
        preview_data: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> str:
        return context._default_purchase_unit_for_import(
            excel_analysis,
            preview_data,
            request_context,
            customer_hint_from_grid=facade._customer_hint_from_preview_grid,
            resolve_excel_path=facade._resolve_excel_path_for_import,
            resolve_sheet_name=facade._resolve_sheet_name_for_reimport,
            guess_default_unit=facade._guess_default_purchase_unit,
        )

    facade._default_purchase_unit_for_import = staticmethod(default_purchase_unit)
    for name in (
        "_build_response",
        "_build_workflow_thinking_steps",
        "_extract_excel_import_records",
        "_format_agent_run_response",
        "_format_workflow_run_response",
        "_handle_confirmation_flow",
        "_infer_excel_column_roles",
        "_infer_excel_column_roles_with_llm",
        "_inject_excel_vector_context",
        "_persist_chat_turn",
        "_start_deterministic_import_agent_run",
        "_try_handle_dynamic_workflow",
    ):
        setattr(facade, name, ComponentMethod(name))


__all__ = [
    "ComponentMethod",
    "FacadeCompatibilityProxy",
    "install_ai_chat_compatibility_surface",
]
