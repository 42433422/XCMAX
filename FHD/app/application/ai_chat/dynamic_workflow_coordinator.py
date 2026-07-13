"""Thin coordinator selecting dynamic-workflow use cases."""

from __future__ import annotations

from typing import Any, Callable

from app.application.ai_chat.dynamic_workflow_profiles import DYNAMIC_WORKFLOW_STOP


class AIChatDynamicWorkflowCoordinator:
    def __init__(
        self,
        *,
        excel_import: Any,
        import_use_cases: Any,
        profile_router: Any,
        planner_executor: Any,
        pending_workflows: dict[str, dict[str, Any]],
        is_pro_source: Callable[[str | None], bool],
    ) -> None:
        self._excel = excel_import
        self._imports = import_use_cases
        self._profiles = profile_router
        self._planner = planner_executor
        self._pending_workflows = pending_workflows
        self._is_pro_source = is_pro_source

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
        explicit_intent = self._excel._looks_like_explicit_workflow_tool_intent(text)
        smart_intent = self._excel._looks_like_smart_workflow_intent(text, context)
        if (
            not self._is_pro_source(source)
            and not smart_intent
            and user_id not in self._pending_workflows
        ):
            return None

        merged_file_ctx: dict[str, Any] = {}
        if isinstance(context, dict):
            merged_file_ctx.update(context.get("file_analysis") or {})
            merged_file_ctx.update(context.get("file_context") or {})
        if isinstance(file_context, dict):
            merged_file_ctx.update(file_context)

        handlers = (
            lambda: self._imports.try_unit_products_import(
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                merged_file_ctx=merged_file_ctx,
                text=text,
            ),
            lambda: self._imports.try_missing_excel_context(
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                merged_file_ctx=merged_file_ctx,
                text=text,
                explicit_workflow_tool_intent=explicit_intent,
            ),
            lambda: self._imports.try_excel_import(
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                merged_file_ctx=merged_file_ctx,
                text=text,
            ),
        )
        for handler in handlers:
            result = handler()
            if result is not None:
                return result

        from app.application.normal_chat_dispatch import resolve_tool_execution_profile

        profile = resolve_tool_execution_profile(context if isinstance(context, dict) else {})
        routed = self._profiles.try_normal_profile(
            profile=profile,
            text=text,
            context=context,
            explicit_workflow_tool_intent=explicit_intent,
        )
        if routed is not None:
            return routed

        pending = self._profiles.try_pending_workflow(user_id=user_id, text=text)
        if pending is not None:
            return pending

        if profile == "normal" and not explicit_intent and not smart_intent:
            return None

        pro_result = self._profiles.try_pro_shipment(
            profile=profile,
            text=text,
            source=source,
        )
        if pro_result is DYNAMIC_WORKFLOW_STOP:
            return None
        if isinstance(pro_result, dict):
            return pro_result

        return self._planner.plan_and_execute(
            user_id=user_id,
            message=message,
            source=source,
            context=context,
        )


__all__ = ["AIChatDynamicWorkflowCoordinator"]
