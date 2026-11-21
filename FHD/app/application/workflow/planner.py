"""Compose request policy, one-pass model planning and deterministic plan admission."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any, cast

import httpx

from app.infrastructure.observability.metrics import observe_plan_stage
from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .llm_plan_generation import LlmPlanGeneration, PlannerCompletion, PlannerConversation
from .model_response_metrics import model_response_scope, record_response_error
from .planner_llm_gateway import request_planner_completion
from .planner_prompt_profile import attachment_import_manifest
from .planning_graph_policy import apply_clarification, validate_required_params
from .planning_graph_policy import (
    filter_registry_for_profile as _filter_tool_registry_for_profile,
)
from .tool_profile import resolve_tool_execution_profile
from .workflow_types import PlanGraph, WorkflowNode, plan_fingerprint, validate_plan_graph

logger = logging.getLogger(__name__)
_planner_http_client: httpx.Client | None = None


def _standalone_question(plan: PlanGraph) -> str | None:
    """Identify a planning question before any executable business graph exists."""
    if len(plan.nodes) != 1:
        return None
    node = plan.nodes[0]
    question = node.params.get("question")
    if (
        (node.tool_id, node.action) != ("clarify", "ask")
        or set(node.params) - {"question", "answer_key", "target_node_id", "clarification"}
        or node.params.get("clarification") not in (None, {}, {"reason": "planning_scope"})
        or node.params.get("target_node_id") not in (None, "")
        or not isinstance(question, str)
        or not 0 < len(question.strip()) <= 12_000
        or node.depends_on
        or node.next is not None
        or node.branches
    ):
        return None
    return question.strip()


def _clarification_plan(plan_id: str, question: str) -> PlanGraph:
    return PlanGraph(
        plan_id=plan_id,
        intent="planning_clarification",
        nodes=[
            WorkflowNode(
                node_id="planning_question",
                tool_id="clarify",
                action="ask",
                params={"question": question, "clarification": {"reason": "planning_scope"}},
                idempotent=True,
            )
        ],
        metadata={"planner": "llm", "planning_clarification": True},
    )


def _bind_attachment_batch(plan: PlanGraph, files: list[str]) -> bool:
    """Bind the model's import action to the current verified attachment selection."""
    nodes = plan.nodes
    scope = set(files)
    selected: set[str] = set()
    if not nodes or len(scope) != len(files):
        return False
    for node in nodes:
        if (
            (node.tool_id, node.action) != ("elt_import", "execute")
            or node.depends_on
            or node.next is not None
            or node.branches
            or set(node.params) - {"file_paths", "valid_rows_only", "accept_suggested"}
        ):
            return False
        paths = node.params.get("file_paths")
        if paths is None and len(nodes) == 1:
            break
        if not isinstance(paths, list) or not all(
            isinstance(path, str) and path in scope for path in paths
        ):
            return False
        selected.update(paths)
    else:
        if selected != scope:
            return False
    # This direct request supplies a file scope, without skipping invalid rows
    # or accepting suggested mappings on the user's behalf.
    node = nodes[0]
    node.params = {"file_paths": files.copy()}
    if len(nodes) > 1:
        plan.nodes = [node]
        node.description = "导入本轮全部附件"
        plan.todo_steps = [node.description]
    return True


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


def _repair_failure_kind(trace: dict[str, Any]) -> str:
    errors = trace.get("errors") or []
    if (
        errors
        and errors[-1].get("code") == "repair_request_failed"
        and "余额不足" in str(errors[-1].get("message") or "")
    ):
        return "model_unavailable"
    return "plan_repair_failed"


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
        context.pop("_planning_failure_code", None)
        for key in (
            "planning_failure_reason",
            "planning_failure_kind",
            "plan_repair_trace",
            "goal_coverage_rejected",
        ):
            context.pop(key, None)
        context.pop("prior_conversation", None)
        session_key = str(context.get("session_id") or context.get("conversation_id") or "").strip()
        plan_id = (
            f"wp-{session_key}-{uuid.uuid4().hex[:8]}" if session_key else f"wp-{uuid.uuid4().hex}"
        )
        rejected = rejected_sql_plan(message, plan_id)
        if rejected is not None:
            return rejected
        from app.application.workflow.local_database_backup_plan import local_database_backup_plan

        backup = local_database_backup_plan(message, plan_id)
        if backup is not None:
            return backup
        profile = resolve_tool_execution_profile(context)
        registry_for_plan = _filter_tool_registry_for_profile(tool_registry, profile)
        context.pop("available_employees", None)
        context.pop("user_memory_rag", None)
        context.pop("memory_v2", None)
        if context.get("_actor_authorization"):
            try:
                from app.domain.shared_services.auth_service import get_auth_service
                from app.infrastructure.auth.agent_mod_scope import _bound_actor
                from app.mod_sdk.employee_directory import build_employee_directory

                if get_auth_service().has_permission(_bound_actor(context), "employee.list"):
                    # 与员工工作台/通讯录共用同一目录，避免三处员工名单不一致。
                    context["available_employees"] = [
                        {
                            "employee_id": row["pack_id"],
                            "description": str(row.get("description") or "")[:200],
                        }
                        for row in build_employee_directory()
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
                from app.domain.shared_services.user_memory_service import get_user_memory_service

                memory_v2_summary = get_user_memory_service().format_memory_v2_for_prompt(
                    user_id=memory_user_id, max_items=6
                )
                if "无已确认记忆" not in memory_v2_summary:
                    context["memory_v2"] = {"summary": memory_v2_summary}
            except ImportError:
                logger.debug("Memory v2 服务不可用（不阻断主流程）")
            except RECOVERABLE_ERRORS as e:
                logger.warning("Memory v2 不可用（不阻断主流程）: %s", e)
        from app.application.workflow.workflow_types import normalize_workflow_risk
        from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph

        batch_files = attachment_import_manifest(message, context) or []
        reviewed_fingerprint: str | None = None

        def validate_candidate(candidate: PlanGraph) -> str | None:
            if (
                reviewed_fingerprint is not None
                and plan_fingerprint(candidate) != reviewed_fingerprint
            ):
                return "目标核对后的计划发生变化，必须重新核对"
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
            if _standalone_question(candidate):
                return validate_plan_graph(candidate)
            if len(batch_files) > 1 and not _bind_attachment_batch(candidate, batch_files):
                return (
                    "本轮批量导入须用一个 elt_import.execute 节点，file_paths 按附件清单逐项列出。"
                )
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
            if (
                reviewed_fingerprint is not None
                and plan_fingerprint(candidate) != reviewed_fingerprint
            ):
                return "目标核对后的计划发生变化，必须重新核对"
            return validate_plan_graph(candidate) or validate_required_params(
                candidate, registry_for_plan
            )

        # Every online business turn is first planned by the configured platform
        # model. Deterministic checks may reject or constrain that plan, but never
        # synthesize an executable replacement when the model output is missing.
        from app.infrastructure.modstore_transport import MarketModelError

        started = time.perf_counter()
        with model_response_scope():
            try:
                planned = self._plan_with_llm(plan_id, user_id, message, registry_for_plan, context)
            except MarketModelError as exc:
                context["planning_failure_reason"] = str(exc)
                context["planning_failure_kind"] = "model_unavailable"
                planned = None
                record_response_error()
        repair_trace: dict[str, Any] = {}
        if planned is not None:
            from app.application.workflow.plan_repair import repair_plan
            from app.infrastructure.llm.model_admission import model_rate_limit_scope

            with model_rate_limit_scope(context):
                planned, repair_trace = repair_plan(
                    planned=planned,
                    plan_id=plan_id,
                    message=message,
                    context=context,
                    tool_registry=registry_for_plan,
                    validate=validate_candidate,
                    complete=self.complete_messages,
                )
            if planned is None:
                errors = repair_trace.get("errors") or []
                context["planning_failure_kind"] = _repair_failure_kind(repair_trace)
                context["plan_repair_trace"] = repair_trace
                if errors:
                    context["planning_failure_reason"] = str(errors[-1].get("message") or "")
                logger.warning("计划修复未成功，本轮不执行: %s", repair_trace.get("errors"))
        if planned is not None and planned.metadata.get("planning_tier") != "light":
            from app.application.ai_chat.dialogue_memory import recent_conversation_messages

            from .goal_coverage import review_goal_coverage

            # Review the final, repaired graph, never the planner's own claim of completeness.
            # One full replan is allowed before execution; the old graph is not resumed.
            for attempt in range(2):
                if question := _standalone_question(planned):
                    planned = _clarification_plan(plan_id, question)
                    break
                with model_rate_limit_scope(context), model_response_scope():
                    try:
                        review_context = {
                            **context,
                            "prior_conversation": recent_conversation_messages(context, limit=12),
                        }
                        review, error = review_goal_coverage(
                            planned, message, review_context, self.complete_messages
                        )
                    except RECOVERABLE_ERRORS:
                        review, error = None, "目标覆盖核对暂不可用，本轮未执行任何操作"
                        record_response_error()
                if error is None and review is not None:
                    planned.metadata["goal_coverage"] = review.model_dump()
                    context.pop("goal_coverage_rejected", None)
                    break
                if review is not None and review.violations and review.clarification_question:
                    planned = _clarification_plan(plan_id, review.clarification_question)
                    context.pop("goal_coverage_rejected", None)
                    context.pop("planning_failure_reason", None)
                    break
                context["planning_failure_reason"] = str(error or "目标核对未完成")
                context["planning_failure_kind"] = "goal_coverage_rejected"
                context["goal_coverage_rejected"] = review is not None
                if attempt or review is None:
                    planned = None
                    break
                context.pop("goal_coverage_rejected", None)
                with model_rate_limit_scope(context), model_response_scope():
                    try:
                        planned = self._generation().generate(
                            plan_id,
                            user_id,
                            message,
                            registry_for_plan,
                            context,
                            coverage_feedback={"review": review.model_dump(), "error": error},
                        )
                    except MarketModelError as exc:
                        context["planning_failure_reason"] = str(exc)
                        context["planning_failure_kind"] = "model_unavailable"
                        context.pop("goal_coverage_rejected", None)
                        planned = None
                        record_response_error()
                    if planned is not None:
                        planned, repair_trace = repair_plan(
                            planned=planned,
                            plan_id=plan_id,
                            message=message,
                            context=context,
                            tool_registry=registry_for_plan,
                            validate=validate_candidate,
                            complete=self.complete_messages,
                        )
                        if planned is None:
                            context["planning_failure_kind"] = _repair_failure_kind(repair_trace)
                            context["plan_repair_trace"] = repair_trace
                            errors = repair_trace.get("errors") or []
                            if errors:
                                context["planning_failure_reason"] = str(
                                    errors[-1].get("message") or ""
                                )
                if planned is None:
                    break
                context.pop("planning_failure_reason", None)
                context.pop("planning_failure_kind", None)
        # 统一 Agent Runtime 接缝：把 pre-plan 记忆召回落上计划元数据，
        # 供编排器转成 run.memory_references（主链路可观测闭合）。
        recall_meta = {
            key: dict(context[key])
            for key in ("user_memory_rag", "memory_v2")
            if isinstance(context.get(key), dict)
        }
        if planned is None and repair_trace and repair_trace.get("errors"):
            context["plan_repair_trace"] = repair_trace
        if planned is not None and repair_trace:
            try:
                planned.metadata["plan_repair"] = repair_trace
            except (AttributeError, TypeError):
                logger.debug("plan metadata 不支持 plan_repair 附加", exc_info=True)
        if recall_meta and planned is not None:
            try:
                planned.metadata["memory_recall"] = recall_meta
            except (AttributeError, TypeError):
                logger.debug("plan metadata 不支持 memory_recall 附加", exc_info=True)
        if planned is not None and "goal_coverage" in planned.metadata:
            reviewed_fingerprint = plan_fingerprint(planned)
        final_plan = finalize_planned_graph(
            planned,
            plan_id=plan_id,
            context=context,
            validate=validate_candidate,
            warn=logger.warning,
            plan_type=PlanGraph,
            node_type=WorkflowNode,
        )
        if planned is None or (final_plan.metadata or {}).get("planning_rejected"):
            valid_outcome = "rejected"
        elif repair_trace.get("first_pass_valid"):
            valid_outcome = "valid_first_pass"
        else:
            valid_outcome = "valid_after_repair"
        observe_plan_stage(
            stage="plan_valid",
            outcome=valid_outcome,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return cast("PlanGraph", final_plan)

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
        max_tokens: int | None = None,
        **extra: Any,
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
            **extra,
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
        candidates: list[dict[str, Any]] | None = None,
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
                candidates=candidates,
            )
