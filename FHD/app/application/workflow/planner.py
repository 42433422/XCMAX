"""Compose request policy, one-pass model planning and deterministic plan admission."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any, cast

import httpx

from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .llm_plan_generation import LlmPlanGeneration, PlannerCompletion, PlannerConversation
from .planner_llm_gateway import request_planner_completion
from .planning_graph_policy import apply_clarification, validate_required_params
from .planning_graph_policy import (
    filter_registry_for_profile as _filter_tool_registry_for_profile,
)
from .tool_profile import resolve_tool_execution_profile
from .workflow_types import PlanGraph, WorkflowNode, validate_plan_graph

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


class LLMWorkflowPlanner:
    def __init__(
        self,
        *,
        ai_service: PlannerConversation | None = None,
        completion: PlannerCompletion | None = None,
        http_client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self._ai_service = ai_service if ai_service is not None else get_ai_conversation_service()
        self._completion = completion
        self._http_client_factory = http_client_factory

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
        profile = resolve_tool_execution_profile(context)
        registry_for_plan = _filter_tool_registry_for_profile(tool_registry, profile)
        context.pop("available_employees", None)
        if context.get("_actor_authorization"):
            try:
                from app.domain.shared_services.auth_service import get_auth_service
                from app.infrastructure.auth.agent_mod_scope import _bound_actor
                from app.mod_sdk.employee_tool_registry import build_employee_tools_status

                if get_auth_service().has_permission(_bound_actor(context), "employee.list"):
                    context["available_employees"] = [
                        {
                            "employee_id": row["pack_id"],
                            "description": str(row.get("description") or "")[:200],
                        }
                        for row in build_employee_tools_status().get("employee_pack_tools", [])
                        if row.get("runtime_ok") and row.get("pack_id")
                    ][:80]
            except RECOVERABLE_ERRORS:
                logger.warning("authorized employee discovery unavailable", exc_info=True)
        from app.application.ai_chat.conversation_history import authorized_memory_context

        authorized_memory = authorized_memory_context(user_id, context)
        if authorized_memory is not None:
            memory_user_id, _memory_access = authorized_memory
            try:
                from app.application import get_user_memory_rag_app_service

                rag = get_user_memory_rag_app_service()
                rag_res = rag.query(user_id=memory_user_id, query_text=message, top_k=3)
                hits = (rag_res or {}).get("hits") if isinstance(rag_res, dict) else None
                if memory_user_id != user_id:
                    # Preserve recall of existing session-scoped chunks while new
                    # writes move to the stable owner namespace.
                    legacy_res = rag.query(user_id=user_id, query_text=message, top_k=3)
                    legacy_hits = (
                        (legacy_res or {}).get("hits") if isinstance(legacy_res, dict) else None
                    )
                    hits = hits if isinstance(hits, list) else []
                    merged = {
                        str(hit.get("chunk_id") or f"stable:{index}"): hit
                        for index, hit in enumerate(hits)
                        if isinstance(hit, dict)
                    }
                    for index, hit in enumerate(legacy_hits or []):
                        if isinstance(hit, dict):
                            merged.setdefault(str(hit.get("chunk_id") or f"legacy:{index}"), hit)
                    hits = sorted(
                        merged.values(), key=lambda hit: float(hit.get("score") or 0), reverse=True
                    )[:4]
                if isinstance(hits, list) and hits:
                    summary = rag.format_for_prompt(
                        user_id=memory_user_id, query_text=message, hits=hits, max_hits=4
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
                from app.application.task_conversation_store import durable_user_id
                from app.domain.shared_services.user_memory_service import get_user_memory_service

                owner_id = durable_user_id(context.get("local_user_id") or context.get("actor_id"))
                memory_v2_summary = (
                    get_user_memory_service().format_memory_v2_for_prompt(
                        user_id=str(owner_id), max_items=6
                    )
                    if owner_id is not None
                    else "【MemoryV2】无已确认记忆。"
                )
                if "无已确认记忆" not in memory_v2_summary:
                    context["memory_v2"] = {"summary": memory_v2_summary}
            except ImportError:
                logger.debug("Memory v2 服务不可用（不阻断主流程）")
            except RECOVERABLE_ERRORS as e:
                logger.warning("Memory v2 不可用（不阻断主流程）: %s", e)
        from app.application.workflow.workflow_types import normalize_workflow_risk
        from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph

        def validate_candidate(candidate: PlanGraph) -> str | None:
            if (candidate.metadata or {}).get("response_mode") == "reply":
                reply_nodes = [
                    node
                    for node in candidate.nodes or []
                    if (node.tool_id, node.action) == ("conversation", "reply")
                ]
                if (
                    len(candidate.nodes or []) != 1
                    or len(reply_nodes) != 1
                    or str(reply_nodes[0].params.get("response") or "").strip()
                    != str((candidate.metadata or {}).get("reply") or "").strip()
                ):
                    return "普通回复计划必须是唯一的内部 conversation.reply 节点"
                return validate_plan_graph(candidate)
            for node in candidate.nodes or []:
                if node.tool_id == "clarify" and node.action == "ask":
                    node.risk, node.idempotent = "low", True
                    continue
                tool_meta = registry_for_plan.get(node.tool_id)
                actions = tool_meta.get("actions") if isinstance(tool_meta, dict) else None
                action_meta = actions.get(node.action) if isinstance(actions, dict) else None
                if not isinstance(action_meta, dict):
                    return f"节点 {node.node_id} 使用未授权动作: {node.tool_id}.{node.action}"
                node.risk = normalize_workflow_risk(action_meta.get("risk"), default="high")
                node.idempotent = action_meta.get("idempotent") is True
            # The deterministic preflight owns missing/ambiguous input detection.
            # It may attach a typed clarify node, but it never invents business
            # values or selects a tool/action on the model's behalf.
            apply_clarification(
                candidate,
                registry_for_plan,
                user_message=message,
                context=context,
            )
            return validate_plan_graph(candidate) or validate_required_params(
                candidate, registry_for_plan
            )

        # Every online business turn is first planned by the configured platform
        # model. Deterministic checks may reject or constrain that plan, but never
        # synthesize an executable replacement when the model output is missing.
        from app.infrastructure.modstore_transport import MarketModelError

        try:
            planned = self._plan_with_llm(plan_id, user_id, message, registry_for_plan, context)
        except MarketModelError as exc:
            context["planning_failure_reason"] = str(exc)
            planned = None
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
                planned,
                plan_id=plan_id,
                context=context,
                validate=validate_candidate,
                warn=logger.warning,
                plan_type=PlanGraph,
                node_type=WorkflowNode,
            ),
        )

    def _generation(self) -> LlmPlanGeneration:
        return LlmPlanGeneration(
            self._ai_service,
            self._completion if self._completion is not None else request_planner_completion,
            self._http_client_factory
            if self._http_client_factory is not None
            else _get_planner_http_client,
        )

    def complete_messages(
        self,
        *,
        messages: list[dict[str, str]],
        context: dict[str, Any] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1200,
    ) -> dict[str, Any] | None:
        """Send a bounded model task through this planner's configured provider."""
        completion = (
            self._completion if self._completion is not None else request_planner_completion
        )
        return completion(
            ai_service=self._ai_service,
            context=context,
            messages=messages,
            http_client_factory=self._http_client_factory or _get_planner_http_client,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _plan_with_llm(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, Any],
        context: dict[str, Any],
    ) -> PlanGraph | None:
        return self._generation().generate(plan_id, user_id, message, tool_registry, context)

    def extract_clarification_parameters(
        self,
        *,
        user_id: str,
        original_message: str,
        answer: str,
        tool_id: str,
        action: str,
        current_params: dict[str, Any],
        allowed_fields: set[str],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        from app.infrastructure.llm.model_admission import model_rate_limit_scope

        with model_rate_limit_scope(context):
            return self._generation().extract_clarification_parameters(
                user_id=user_id,
                original_message=original_message,
                answer=answer,
                tool_id=tool_id,
                action=action,
                current_params=current_params,
                allowed_fields=allowed_fields,
                context=context,
            )
