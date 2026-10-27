# ruff: noqa: F401
"""Compose request policy, LLM generation, bounded probes and deterministic planning."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any, cast

import httpx

from app.application.tools.workflow_tools.dispatch import execute_registered_workflow_tool
from app.domain.conversation.services.chat_tool_intent import (
    looks_like_business_db_write as _looks_like_business_db_write,
)
from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import ensure_fhd_repo_on_syspath

from .business_db_planning import (
    _changes_for_business_db_message as _changes_for_business_db_message,
)
from .business_db_planning import (
    _clean_db_slot_value as _clean_db_slot_value,
)
from .business_db_planning import (
    _extract_business_db_id as _extract_business_db_id,
)
from .business_db_planning import (
    _extract_business_db_read_keyword as _extract_business_db_read_keyword,
)
from .business_db_planning import (
    _extract_business_db_write_node as _extract_business_db_write_node,
)
from .business_db_planning import (
    _extract_marked_value as _extract_marked_value,
)
from .business_db_planning import (
    _extract_named_slot as _extract_named_slot,
)
from .business_db_planning import (
    _extract_number as _extract_number,
)
from .business_db_planning import (
    _infer_business_db_entity as _infer_business_db_entity,
)
from .business_db_planning import (
    _infer_business_db_operation as _infer_business_db_operation,
)
from .business_db_planning import (
    _selector_for_business_db_message as _selector_for_business_db_message,
)
from .deterministic_planning import DeterministicDependencies, DeterministicPlanner
from .llm_plan_generation import LlmPlanGeneration, PlannerCompletion, PlannerConversation
from .onboarding_slots import _onboarding_first_order_slots as _onboarding_first_order_slots
from .planner_business_tools import (
    _execute_business_db_read_tool as _execute_business_db_read_tool,
)
from .planner_business_tools import (
    _execute_business_db_write_tool as _execute_business_db_write_tool,
)
from .planner_business_tools import (
    _execute_customers_ensure_exists_tool as _execute_customers_ensure_exists_tool,
)
from .planner_business_tools import (
    _execute_customers_tool as _execute_customers_tool,
)
from .planner_business_tools import (
    _execute_employee_execute_tool as _execute_employee_execute_tool,
)
from .planner_business_tools import (
    _execute_employee_list_tool as _execute_employee_list_tool,
)
from .planner_business_tools import (
    _execute_materials_tool as _execute_materials_tool,
)
from .planner_business_tools import (
    _execute_products_tool as _execute_products_tool,
)
from .planner_business_tools import (
    _execute_shipment_records_tool as _execute_shipment_records_tool,
)
from .planner_document_tools import (
    _execute_price_list_tool as _price_list_export,
)
from .planner_document_tools import (
    _execute_print_label_tool as _execute_print_label_tool,
)
from .planner_document_tools import (
    _execute_shipment_generate_tool as _execute_shipment_generate_tool,
)
from .planner_excel_tools import (
    _execute_excel_analysis_tool as _execute_excel_analysis_tool,
)
from .planner_excel_tools import (
    _execute_excel_decompose_tool as _execute_excel_decompose_tool,
)
from .planner_excel_tools import (
    _execute_excel_schema_tool as _execute_excel_schema_tool,
)
from .planner_excel_tools import (
    _execute_import_excel_tool as _execute_import_excel_tool,
)
from .planner_llm_gateway import request_planner_completion
from .planner_tool_dispatch import RegisteredToolExecutor, ToolHandler
from .planner_tool_dispatch import execute_tool as dispatch_tool
from .planner_tool_dispatch import get_tool_registry as get_tool_registry
from .planning_graph_policy import (
    apply_clarification,
    apply_conditional_edges,
    validate_required_params,
)
from .planning_graph_policy import (
    filter_registry_for_profile as _filter_tool_registry_for_profile,
)
from .planning_loop import PlanningLoop
from .workflow_types import (
    Branch,
    PlanGraph,
    WorkflowNode,
    normalize_workflow_risk,
    validate_plan_graph,
)

logger = logging.getLogger(__name__)
_planner_http_client: httpx.Client | None = None


def _get_planner_http_client() -> httpx.Client:
    global _planner_http_client
    if _planner_http_client is None:
        _planner_http_client = httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            trust_env=False,
        )
    return _planner_http_client


def close_planner_http_client() -> None:
    """Close the reusable planner HTTP client during application shutdown."""
    global _planner_http_client
    client = _planner_http_client
    _planner_http_client = None
    if client is not None and not client.is_closed:
        client.close()


def _execute_price_list_tool(params: dict[str, Any]) -> dict[str, Any]:
    return _price_list_export(params, ensure_repo=ensure_fhd_repo_on_syspath)


def _execute_template_extract_tool(params: dict[str, Any]) -> dict[str, Any]:
    return _execute_excel_decompose_tool(params)


_WORKFLOW_TOOL_HANDLERS: dict[tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]] = {
    ("price_list", "export"): _execute_price_list_tool,
    ("products", "query"): _execute_products_tool,
    ("customers", "query"): _execute_customers_tool,
    ("customers", "ensure_exists"): _execute_customers_ensure_exists_tool,
    ("shipment_generate", "generate"): _execute_shipment_generate_tool,
    ("shipment_records", "query"): _execute_shipment_records_tool,
    ("shipments", "query"): _execute_shipment_records_tool,
    ("materials", "query"): _execute_materials_tool,
    ("print_label", "generate"): _execute_print_label_tool,
    ("excel_decompose", "decompose"): _execute_excel_decompose_tool,
    ("template_extract", "extract"): _execute_template_extract_tool,
    ("excel_schema", "analyze"): _execute_excel_schema_tool,
    ("excel_analysis", "analyze"): _execute_excel_analysis_tool,
    ("import_excel", "import"): _execute_import_excel_tool,
    ("employee", "list"): _execute_employee_list_tool,
    ("employee", "execute"): _execute_employee_execute_tool,
    ("business_db", "read"): _execute_business_db_read_tool,
    ("business_db", "write"): _execute_business_db_write_tool,
}


def execute_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    return dispatch_tool(
        tool_name,
        params,
        handlers=_WORKFLOW_TOOL_HANDLERS,
        registered=execute_registered_workflow_tool,
    )


def _registered_probe(tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
    from app.application.facades.tools_facade import execute_registered_workflow_tool as execute

    return execute(tool_id=tool_id, action=action, params=params)


class LLMWorkflowPlanner:
    def __init__(
        self,
        *,
        ai_service: PlannerConversation | None = None,
        completion: PlannerCompletion | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
        probe: RegisteredToolExecutor | None = None,
    ) -> None:
        self._ai_service = ai_service if ai_service is not None else get_ai_conversation_service()
        self._completion = completion
        self._http_client_factory = http_client_factory
        self._probe = probe

    def plan(
        self,
        user_id: str,
        message: str,
        tool_registry: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PlanGraph:
        from app.application.workflow.sql_execution_policy import rejected_sql_plan

        context = dict(context or {})
        session_key = str(context.get("session_id") or context.get("conversation_id") or "").strip()
        plan_id = (
            f"wp-{session_key}-{uuid.uuid4().hex[:8]}" if session_key else f"wp-{uuid.uuid4().hex}"
        )
        rejected = rejected_sql_plan(message, plan_id)
        if rejected is not None:
            return rejected
        from app.application.normal_chat_dispatch import resolve_tool_execution_profile

        profile = resolve_tool_execution_profile(context)
        registry_for_plan = _filter_tool_registry_for_profile(tool_registry, profile)
        from app.application.workflow.sql_execution_policy import database_maintenance_plan

        restore = database_maintenance_plan(message, plan_id, registry_for_plan)
        if restore is not None:
            return restore
        from app.application.normal_chat_dispatch import route_normal_mode_message

        _route = route_normal_mode_message(str(message or ""))
        if _route.get("intent") in {"desktop", "label_print"}:
            return self._fallback_plan(plan_id, message, registry_for_plan)
        if (
            "sales" in registry_for_plan
            and str(_route.get("intent") or "") == "sales_write"
            and (str(_route.get("action") or "") == "execute_closed_loop")
            and isinstance(_route.get("payload"), dict)
            and bool(_route.get("payload"))
        ):
            from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph

            return cast(
                "PlanGraph",
                finalize_planned_graph(
                    self._decorate_plan(
                        self._fallback_plan(plan_id, message, registry_for_plan),
                        message,
                        registry_for_plan,
                    ),
                    plan_id=plan_id,
                    context=context,
                    validate=validate_plan_graph,
                    fallback_factory=lambda: self._fallback_plan(
                        plan_id, message, registry_for_plan
                    ),
                    warn=logger.warning,
                ),
            )
        try:
            from app.application import get_user_memory_rag_app_service

            rag = get_user_memory_rag_app_service()
            rag_res = rag.query(user_id=user_id, query_text=message, top_k=3)
            hits = (rag_res or {}).get("hits") if isinstance(rag_res, dict) else None
            if isinstance(hits, list) and hits:
                summary = rag.format_for_prompt(
                    user_id=user_id, query_text=message, hits=hits, max_hits=4
                )
                context["user_memory_rag"] = {
                    "summary": summary,
                    "hits": [hit for hit in hits if isinstance(hit, dict)],
                }
        except ImportError:
            logger.debug("用户记忆 RAG 服务不可用（不阻断主流程）")
        except RECOVERABLE_ERRORS as e:
            logger.warning("用户记忆 RAG 不可用（不阻断主流程）: %s", e)
        try:
            from app.domain.shared_services.user_memory_service import get_user_memory_service

            memory_v2_summary = get_user_memory_service().format_memory_v2_for_prompt(
                user_id=user_id, max_items=6
            )
            if "无已确认记忆" not in memory_v2_summary:
                context["memory_v2"] = {"summary": memory_v2_summary}
        except ImportError:
            logger.debug("Memory v2 服务不可用（不阻断主流程）")
        except RECOVERABLE_ERRORS as e:
            logger.warning("Memory v2 不可用（不阻断主流程）: %s", e)
        from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph

        planned = None
        # 规划入口 SQL 拒绝主闸已由 sql_execution_policy.rejected_sql_plan（#1815）承担（L33）；
        # 此处不再重复布闸。原始 SQL 的写路径双保险见 business_db_planning._extract_business_db_write_node。
        from app.application.workflow.sales_quote_plan import sales_quote_node

        if sales_quote_node(message, registry_for_plan, single_request=True) is not None:
            planned = self._fallback_plan(plan_id, message, registry_for_plan)
        elif _onboarding_first_order_slots(message) and "business_db" in registry_for_plan:
            deterministic = self._fallback_plan(plan_id, message, registry_for_plan)
            if deterministic.intent == "onboarding_first_order" and len(deterministic.nodes) == 3:
                planned = deterministic
        elif (
            _looks_like_business_db_write(message, message.lower())
            and "business_db" in registry_for_plan
        ):
            deterministic = self._fallback_plan(plan_id, message, registry_for_plan)
            if deterministic.intent == "business_db_write" and deterministic.nodes:
                planned = deterministic
        if planned is None:
            planned = self._plan_with_react_multiagent(
                plan_id, user_id, message, registry_for_plan, context
            )
        # 统一 Agent Runtime 接缝：把 pre-plan 记忆召回落上计划元数据，
        # 供编排器转成 run.memory_references（主链路可观测闭合）。
        recall_meta = {
            key: dict(context[key])
            for key in ("user_memory_rag", "memory_v2")
            if isinstance(context.get(key), dict)
        }
        if recall_meta and planned is not None:
            try:
                planned.metadata["memory_recall"] = recall_meta
            except (AttributeError, TypeError):
                logger.debug("plan metadata 不支持 memory_recall 附加", exc_info=True)
        return cast(
            "PlanGraph",
            finalize_planned_graph(
                self._decorate_plan(planned, message, registry_for_plan),
                plan_id=plan_id,
                context=context,
                validate=validate_plan_graph,
                fallback_factory=lambda: self._fallback_plan(plan_id, message, registry_for_plan),
                warn=logger.warning,
            ),
        )

    def _decorate_plan(
        self,
        plan: PlanGraph | None,
        message: str,
        tool_registry: dict[str, Any],
    ) -> PlanGraph | None:
        """对规划产出的 PlanGraph 追加确定性条件边与反问澄清节点。

        不强行依赖 LLM 输出：条件边/反问节点由规则派生，保证行为可测、向后兼容。
        """
        if plan is None:
            return None
        plan = self._apply_conditional_edge_rules(plan, message, tool_registry)
        plan = self._apply_clarify_rules(plan, tool_registry)
        return plan

    _apply_conditional_edge_rules = staticmethod(apply_conditional_edges)
    _apply_clarify_rules = staticmethod(apply_clarification)
    _validate_required_params = staticmethod(validate_required_params)

    def _generation(self) -> LlmPlanGeneration:
        return LlmPlanGeneration(
            self._ai_service,
            self._completion if self._completion is not None else request_planner_completion,
            self._http_client_factory
            if self._http_client_factory is not None
            else _get_planner_http_client,
        )

    def _fallback_plan(
        self, plan_id: str, message: str, tool_registry: dict[str, Any]
    ) -> PlanGraph:
        rules = DeterministicDependencies(
            looks_like_write=lambda text, lower: _looks_like_business_db_write(text, lower),
            write_node=lambda text: _extract_business_db_write_node(text),
            entity=_infer_business_db_entity,
            read_keyword=_extract_business_db_read_keyword,
            conditional_edges=self._apply_conditional_edge_rules,
            clarification=self._apply_clarify_rules,
        )
        return DeterministicPlanner(rules).plan(plan_id, message, tool_registry)

    def _plan_with_llm(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, Any],
        context: dict[str, Any],
    ) -> PlanGraph | None:
        return self._generation().generate(plan_id, user_id, message, tool_registry, context)

    def _critic_repair_with_llm(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, Any],
        context: dict[str, Any],
        error: str,
        invalid_plan: PlanGraph,
    ) -> PlanGraph | None:
        return self._generation().repair(
            plan_id, user_id, message, tool_registry, context, error, invalid_plan
        )

    def _plan_with_react_multiagent(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, Any],
        context: dict[str, Any],
    ) -> PlanGraph | None:
        return PlanningLoop(
            self._plan_with_llm,
            self._critic_repair_with_llm,
            self._probe if self._probe is not None else _registered_probe,
            validate_plan_graph,
            self._validate_required_params,
        ).plan(plan_id, user_id, message, tool_registry, context)
