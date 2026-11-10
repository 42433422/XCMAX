"""Session-scoped confirmations, clarification and durable workflow transitions."""

from __future__ import annotations

import copy
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Protocol, cast

from app.application.ai_chat.excel_import_policy import _enrich_confirmation_inner
from app.utils.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.workflow_types import PlanGraph

logger = logging.getLogger(__name__)

CONFIRM_WORDS = {"确认", "是", "是的", "好的", "好", "继续", "执行", "确认执行", "ok", "yes"}
CANCEL_WORDS = {"取消", "否", "不要", "停止", "no"}


def _control_reply(
    text: str,
    action: str,
    data: dict[str, Any] | None = None,
    *,
    success: bool = True,
    message: str = "处理完成",
    display_text: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    return True, {
        "success": success,
        "message": message,
        "response": text,
        "data": {
            "text": text if display_text is None else display_text,
            "action": action,
            "data": {} if data is None else data,
        },
    }


class SessionCallbacks(Protocol):
    def _continue_after_clarification(
        self, user_id: str, pending: dict[str, Any], message: str
    ) -> dict[str, Any] | None: ...
    def _format_agent_run_response(
        self, plan: PlanGraph, agent_run: AgentRun, thinking_steps: str = "", user_message: str = ""
    ) -> dict[str, Any]: ...
    def _hydrate_pending_workflow(self, user_id: str, session_id: str) -> bool: ...
    def _persist_plan_state(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None,
        status: str,
        message: str | None = None,
    ) -> bool: ...

    workflow_planner: Any

    def _dispatch_model_selection(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        text: str,
    ) -> dict[str, Any] | None: ...
    @staticmethod
    def _task_owner_id(user_id: str, runtime_context: dict[str, Any]) -> str: ...


class PlanStateStore(Protocol):
    def list_active(
        self, user_id: str, limit: int = 20, *, session_id: str | None = None
    ) -> list[dict[str, Any]]: ...

    def save(
        self,
        *,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
        status: str = "running",
        user_id: str | None = None,
        session_id: str | None = None,
        message: str | None = None,
        require_commit: bool = False,
    ) -> str: ...


class WorkflowSession:
    def __init__(
        self,
        pending: dict[str, dict[str, Any]],
        callbacks: SessionCallbacks,
        approval: ApprovalService | None = None,
        store: PlanStateStore | None = None,
    ) -> None:
        self.pending = pending
        self.callbacks = callbacks
        self._approval = approval
        self.store = store

    @property
    def approval(self) -> ApprovalService:
        if self._approval is None:
            raise RuntimeError("Approval submission requires an approval service")
        return self._approval

    def _plan_store(self) -> PlanStateStore:
        if self.store is None:
            from app.application.workflow.plan_store import WorkflowPlanStore

            return WorkflowPlanStore()
        return self.store

    def hydrate_pending_workflow(self, user_id: str, session_id: str) -> bool:
        """仅恢复当前会话的待确认计划；跨会话续跑须从明确的任务入口处理。"""
        try:
            from app.application.workflow.workflow_types import plan_from_dict

            active = self._plan_store().list_active(user_id, limit=1, session_id=session_id)
            if not active or active[0].get("status") != "pending_awaiting":
                return False
            plan = plan_from_dict(active[0].get("plan") or {})
            if plan is None or not plan.nodes:
                return False
            runtime_context = dict(active[0].get("runtime_context") or {})
            confirmation = runtime_context.pop("pending_confirmation", {})
            entry = {
                "plan": plan,
                "runtime_context": runtime_context,
                "pending_id": uuid.uuid4().hex,
                "thinking_steps": "",
                "kind": str(confirmation.get("kind") or "workflow"),
                "agent_run_id": str(confirmation.get("agent_run_id") or ""),
                "approval_required": bool(confirmation.get("approval_required")),
                "approval_nodes": confirmation.get("approval_nodes") or [],
                "clarification": confirmation.get("clarification") or {},
                "clarify_node_id": str(confirmation.get("clarify_node_id") or ""),
                "clarification_step_id": str(confirmation.get("clarification_step_id") or ""),
                "target_node_id": str(confirmation.get("target_node_id") or ""),
                "created_at": confirmation.get("created_at", 0),
                "ttl_seconds": confirmation.get("ttl_seconds", 0),
                "hydrated_from_db": True,
            }
            run_id = entry["agent_run_id"]
            if run_id:
                from app.application.agent_orchestrator import AgentOrchestrator

                run = AgentOrchestrator().get_run(run_id)
                if run is None or run.status != "waiting_user":
                    return False
                persisted_plan = plan_from_dict(run.metadata.get("plan"))
                if persisted_plan is None or persisted_plan.plan_id != plan.plan_id:
                    return False
                entry["plan"] = persisted_plan
                if entry["kind"] in {"clarification", "clarification_unbound"}:
                    from app.application.agent_orchestrator.clarification import find_waiting_step

                    waiting = find_waiting_step(run)
                    if waiting is None or (waiting.tool_id, waiting.action) != ("clarify", "ask"):
                        return False
                    detail = waiting.params.get("clarification")
                    entry.update(
                        kind="clarification"
                        if waiting.params.get("target_node_id")
                        else "clarification_unbound",
                        clarification=detail if isinstance(detail, dict) else {},
                        clarify_node_id=waiting.node_id,
                        clarification_step_id=waiting.step_id,
                        target_node_id=str(waiting.params.get("target_node_id") or ""),
                    )
            self.pending[user_id] = entry
            return True
        except RECOVERABLE_ERRORS:
            logger.debug("DB 待续跑计划水合失败 user_id=%s", user_id)
            return False

    def persist_plan_state(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None,
        status: str,
        message: str | None = None,
    ) -> bool:
        """保存计划快照；成功提交返回 True，失败返回 False，调用方据此决定是否完成操作。"""
        try:
            rc = dict(runtime_context or {})
            user_id = str(rc.get("user_id") or "").strip() or None
            session_id = (
                str(rc.get("session_id") or rc.get("conversation_id") or "").strip() or None
            )
            pending = self.pending.get(user_id or "") or {}
            if (
                status == "pending_awaiting"
                and getattr(pending.get("plan"), "plan_id", None) == plan.plan_id
            ):
                rc["pending_confirmation"] = {
                    key: pending.get(key)
                    for key in (
                        "agent_run_id",
                        "approval_required",
                        "approval_nodes",
                        "kind",
                        "clarification",
                        "clarify_node_id",
                        "clarification_step_id",
                        "target_node_id",
                        "created_at",
                        "ttl_seconds",
                    )
                }
            self._plan_store().save(
                plan=plan,
                runtime_context=rc,
                status=status,
                user_id=user_id,
                session_id=session_id,
                message=message,
                require_commit=status == "cancelled",
            )
            return True
        except RECOVERABLE_ERRORS:
            logger.warning(
                "计划持久化失败 plan_id=%s status=%s", getattr(plan, "plan_id", "?"), status
            )
            return False

    def _cancel_pending_agent_run(
        self, user_id: str, pending: dict[str, Any], runtime: dict[str, Any]
    ) -> bool:
        run_id = str(pending.get("agent_run_id") or "").strip()
        if not run_id:
            return True
        try:
            from app.application.agent_orchestrator import AgentOrchestrator

            orchestrator = AgentOrchestrator()
            run = orchestrator.get_run(run_id)
            if run is None or run.user_id not in {
                user_id,
                self.callbacks._task_owner_id(user_id, runtime),
            }:
                return False
            run_runtime = dict(run.metadata.get("runtime_context") or {})
            if (
                run.plan_id != pending["plan"].plan_id
                or str(run_runtime.get("tenant_id") or "") != str(runtime.get("tenant_id") or "")
                or str(run_runtime.get("session_id") or run_runtime.get("conversation_id") or "")
                != str(runtime.get("session_id") or runtime.get("conversation_id") or "")
            ):
                return False
            cancelled = orchestrator.cancel_run(run_id, requested_by=user_id)
            return cancelled is not None and cancelled.status == "cancelled"
        except RECOVERABLE_ERRORS:
            logger.warning("待确认 AgentRun 取消未完成 run_id=%s", run_id)
            return False

    def sweep_expired_clarifications(self) -> list[str]:
        """扫描并移除过期的"澄清待确认"记录（TTL 防堆积）。"""
        from app.application.workflow.clarification_node import sweep_expired

        return sweep_expired(self.pending)

    def capture_agent_run_interaction(
        self,
        *,
        user_id: str,
        agent_run: AgentRun,
        runtime_context: dict[str, Any],
        thinking_steps: str = "",
        decision_reason: str = "",
        approval_nodes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Persist the exact LangGraph checkpoint that is waiting for user input."""
        if agent_run.status != "waiting_user":
            return None
        from app.application.agent_orchestrator.clarification import find_waiting_step
        from app.application.workflow.clarification_node import clarification_ttl_seconds
        from app.application.workflow.workflow_types import plan_from_dict

        plan = plan_from_dict(agent_run.metadata.get("plan"))
        waiting = find_waiting_step(agent_run)
        if plan is None or waiting is None:
            return _control_reply(
                "工作流暂停状态与持久化计划不匹配，已停止续跑；请返回原任务核对。",
                "workflow_resume_failed",
                {"run_id": agent_run.run_id},
                success=False,
                message="工作流暂停状态无效",
            )[1]
        from app.application.workflow.workflow_types import validate_plan_graph

        node = next((item for item in plan.nodes if item.node_id == waiting.node_id), None)
        if (
            validate_plan_graph(plan)
            or node is None
            or (node.tool_id, node.action, node.params, node.depends_on)
            != (waiting.tool_id, waiting.action, waiting.params, waiting.depends_on)
        ):
            return _control_reply(
                "等待交互的步骤与持久化计划不一致，已停止续跑；请重新发起任务。",
                "workflow_resume_failed",
                {"run_id": agent_run.run_id, "plan_id": plan.plan_id},
                success=False,
                message="执行计划绑定校验失败",
            )[1]
        context = dict(runtime_context or {})
        required_ids = {
            str(value)
            for value in (plan.metadata or {}).get("approval_required_node_ids", [])
            if str(value)
        }
        if waiting.tool_id == "clarify" and waiting.action == "ask":
            detail = waiting.params.get("clarification")
            detail = detail if isinstance(detail, dict) else {}
            pending = {
                "plan": plan,
                "runtime_context": context,
                "pending_id": uuid.uuid4().hex,
                "agent_run_id": agent_run.run_id,
                "thinking_steps": thinking_steps,
                "kind": "clarification"
                if waiting.params.get("target_node_id")
                else "clarification_unbound",
                "clarify_node_id": waiting.node_id,
                "clarification_step_id": waiting.step_id,
                "target_node_id": str(waiting.params.get("target_node_id") or ""),
                "clarification": detail,
                "created_at": time.time(),
                "ttl_seconds": clarification_ttl_seconds(),
                "approval_required": bool(required_ids or approval_nodes),
                "approval_nodes": approval_nodes or [],
            }
            self.pending[user_id] = pending
            if not self.callbacks._persist_plan_state(plan, context, status="pending_awaiting"):
                return _control_reply(
                    "澄清步骤已暂停，但待续计划未能持久化；该步骤未执行。请核对任务状态后再继续。",
                    "workflow_persistence_failed",
                    {"run_id": agent_run.run_id, "plan_id": plan.plan_id},
                    success=False,
                    message="澄清状态未保存",
                )[1]
            question = str(
                waiting.output.get("question")
                or waiting.params.get("question")
                or "请补充当前业务参数。"
            )
            return {
                "success": True,
                "message": "需要澄清",
                "response": question,
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "data": {
                    "text": question,
                    "action": "clarification_required",
                    "run_id": agent_run.run_id,
                    "agent_run_id": agent_run.run_id,
                    "data": {
                        "plan_id": plan.plan_id,
                        "target_node_id": pending["target_node_id"],
                        "reason": detail.get("reason", ""),
                        "missing_fields": detail.get("missing_fields") or [],
                        "candidates": detail.get("candidates") or [],
                        "ttl_seconds": pending["ttl_seconds"],
                    },
                },
            }
        if waiting.node_id in required_ids:
            return self._submit_waiting_approval(
                user_id=user_id,
                plan=plan,
                agent_run=agent_run,
                waiting=waiting,
                runtime_context=context,
            )
        self.pending[user_id] = {
            "plan": plan,
            "runtime_context": context,
            "pending_id": uuid.uuid4().hex,
            "agent_run_id": agent_run.run_id,
            "thinking_steps": thinking_steps,
            "kind": "workflow",
            "approval_required": bool(required_ids or approval_nodes),
            "approval_nodes": approval_nodes or [],
        }
        if not self.callbacks._persist_plan_state(plan, context, status="pending_awaiting"):
            return _control_reply(
                "工作流已安全暂停，但待续计划未能持久化；未执行等待确认的步骤。请核对任务状态后再继续。",
                "workflow_persistence_failed",
                {"run_id": agent_run.run_id, "plan_id": plan.plan_id},
                success=False,
                message="待确认状态未保存",
            )[1]
        reason = decision_reason or "工作流步骤需要用户确认"
        response_text = (
            f"工作流已安全暂停（{waiting.tool_id}.{waiting.action}）。{reason}。"
            "回复「确认」继续，回复「取消」终止。"
        )
        return {
            "success": True,
            "message": "等待确认",
            "response": response_text,
            "run_id": agent_run.run_id,
            "agent_run_id": agent_run.run_id,
            "data": {
                "text": response_text,
                "action": "workflow_confirmation_required",
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "data": {
                    "plan_id": plan.plan_id,
                    "blocking_nodes": [waiting.node_id],
                    "approval_required": bool(required_ids or approval_nodes),
                },
            },
        }

    def _submit_waiting_approval(
        self,
        *,
        user_id: str,
        plan: PlanGraph,
        agent_run: AgentRun,
        waiting: Any,
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        required = {
            str(value)
            for value in (plan.metadata or {}).get("approval_required_node_ids", [])
            if str(value)
        }
        node = next((item for item in plan.nodes if item.node_id == waiting.node_id), None)
        if (
            waiting.node_id not in required
            or node is None
            or (node.tool_id, node.action, node.params)
            != (waiting.tool_id, waiting.action, waiting.params)
        ):
            return _control_reply(
                "等待审批的节点与完整计划不一致，未提交审批或执行；请重新发起任务。",
                "approval_failed",
                {"run_id": agent_run.run_id, "plan_id": plan.plan_id},
                success=False,
                message="审批计划校验失败",
            )[1]
        if self._approval is None:
            return _control_reply(
                "审批服务当前不可用，原计划保持暂停且未执行该步骤。",
                "approval_failed",
                {"run_id": agent_run.run_id, "plan_id": plan.plan_id},
                success=False,
                message="审批服务不可用",
            )[1]
        from app.application.workflow.planning_graph_policy import validate_required_params
        from app.application.workflow.workflow_types import validate_plan_graph
        from app.application.workflow_registry_app import get_workflow_tool_registry

        plan_error = validate_plan_graph(plan) or validate_required_params(
            plan, get_workflow_tool_registry()
        )
        run_steps = {step.node_id: step for step in agent_run.steps}
        if (
            plan_error
            or set(run_steps) != {item.node_id for item in plan.nodes}
            or any(
                (node.tool_id, node.action, node.params, node.depends_on)
                != (
                    run_steps[node.node_id].tool_id,
                    run_steps[node.node_id].action,
                    run_steps[node.node_id].params,
                    run_steps[node.node_id].depends_on,
                )
                for node in plan.nodes
            )
        ):
            return _control_reply(
                "审批计划校验失败，未执行任何操作；请重新发起任务。",
                "approval_failed",
                {"run_id": agent_run.run_id, "plan_id": plan.plan_id},
                success=False,
                message="审批计划校验失败",
            )[1]
        request_id = ""
        try:
            approval_context = {**runtime_context, "_approval_agent_run_required": True}
            request = self.approval.create_approval_request(
                plan_id=plan.plan_id,
                node=node,
                runtime_context=approval_context,
                plan=plan,
                require_persistence=True,
            )
            request_id = str(request.request_id or "").strip()
            if not request_id or not self.approval.attach_pending_agent_run(
                request_id,
                agent_run_id=agent_run.run_id,
                approved_step_id=waiting.node_id,
            ):
                raise RuntimeError("审批执行记录关联失败")
        except RECOVERABLE_ERRORS:
            if request_id:
                self.approval.cancel(request_id)
            return _control_reply(
                "审批请求未能安全持久化关联，原计划已暂停且未执行该步骤；请核对审批工作台后重试。",
                "approval_failed",
                {"run_id": agent_run.run_id, "plan_id": plan.plan_id},
                success=False,
                message="审批请求创建失败",
            )[1]
        approval_info = self.approval.get_request_metadata(request_id) or {"request_no": request_id}
        approval_info["agent_run_id"] = agent_run.run_id
        self.pending.pop(user_id, None)
        return _control_reply(
            f"已提交审批请求：{request_id}。请前往审批工作台逐笔处理。",
            "approval_pending",
            _enrich_confirmation_inner(
                {
                    "plan_id": plan.plan_id,
                    "agent_run_id": agent_run.run_id,
                    "approval_request_ids": [request_id],
                    "approval_requests": [approval_info],
                    "approval_required": True,
                    "approval_path": approval_info.get("approval_path")
                    or "/mod/xcagi-approval-bridge/approval-hub/workspace",
                },
                action="approval_pending",
            ),
        )[1]

    def _clarification_answer(
        self, run: AgentRun, waiting: Any, text: str
    ) -> tuple[dict[str, Any], bool, set[str]] | None:
        """Resolve only fields authorized by the server-owned clarification rule."""
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        detail = waiting.params.get("clarification")
        detail = detail if isinstance(detail, dict) else {}
        reason = str(detail.get("reason") or "")
        target_id = str(waiting.params.get("target_node_id") or "")
        target = next((step for step in run.steps if step.node_id == target_id), None)
        if target is None:
            return None
        candidates = detail.get("candidates") or []
        affirmative = str(text or "").strip().lower().rstrip("。.!！") in {
            "确认",
            "是",
            "是的",
            "好的",
            "好",
            "继续",
            "执行",
            "确认执行",
            "ok",
            "yes",
            "按这个",
            "就这样",
            "可以",
        }
        if reason in {"ambiguous_target", "missing_target"}:
            from app.application.workflow.clarification_node import resolve_confirmed_target

            selected = resolve_confirmed_target(
                text, candidates if isinstance(candidates, list) else []
            )
            if selected is None and target.tool_id == "business_db" and target.action == "write":
                if str(text or "").strip().isdigit():
                    selected = {"id": str(text).strip()}
                else:
                    from app.domain.shared_services.tools_workflow_registered import (
                        prepare_business_db_write_target,
                    )

                    entity = str(target.params.get("entity") or "")
                    natural_fields = {
                        "customers": "customer_name",
                        "products": "product_name",
                        "materials": "material_name",
                    }
                    key = natural_fields.get(entity)
                    if key:
                        payload = dict(target.params.get("payload") or {})
                        payload["selector"] = {key: str(text or "").strip()}
                        resolved = prepare_business_db_write_target(
                            entity, str(target.params.get("operation") or ""), payload
                        )
                        if resolved.get("success"):
                            selected = {"id": str(resolved.get("payload", {}).get("id") or "")}
            if not selected or not str(selected.get("id") or "").strip():
                return None
            if target.tool_id == "business_db" and target.action == "write":
                return ({"payload": {"id": selected["id"]}}, True, set())
            return ({"id": selected["id"]}, True, set())

        spec = get_tool_action_spec(target.tool_id, target.action)
        schema = spec.input_schema if spec and isinstance(spec.input_schema, dict) else {}
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}
        allowed: set[str] = set()
        if reason == "missing_required":
            allowed = {
                str(value)
                for value in detail.get("missing_fields", [])
                if isinstance(value, (str, int)) and str(value).strip()
            }
        elif reason == "report_scope":
            field = str(detail.get("field") or "")
            if field == "日期范围":
                allowed = {key for key in ("start_date", "end_date") if key in properties}
            elif field == "group_by" and "group_by" in properties:
                allowed = {"group_by"}
        elif reason == "multi_unit":
            allowed = {
                key
                for key in properties
                if any(token in key.lower() for token in ("unit", "quantity", "amount"))
            }
        elif reason not in {
            "reversal_confirm",
            "inventory_count_diff",
            "journal_entry_reverse",
            "batch_scope",
            "credit_limit_exceed",
        }:
            field_rows = waiting.output.get("fields") if isinstance(waiting.output, dict) else []
            allowed = {
                str(item.get("key"))
                for item in field_rows or []
                if isinstance(item, dict) and item.get("key") in properties
            }
        if allowed:
            planner = getattr(self.callbacks, "workflow_planner", None)
            if planner is None or not hasattr(planner, "extract_clarification_parameters"):
                from app.application.workflow.planner import LLMWorkflowPlanner

                planner = LLMWorkflowPlanner()
            runtime = dict(run.metadata.get("runtime_context") or {})
            parameters = planner.extract_clarification_parameters(
                user_id=run.user_id,
                original_message=run.message,
                answer=text,
                tool_id=target.tool_id,
                action=target.action,
                current_params=target.params,
                allowed_fields=allowed,
                context=runtime,
            )
            if not isinstance(parameters, dict) or not parameters or set(parameters) - allowed:
                return None
            # A resolved parameter extraction is the user's concrete answer to this
            # clarification. Destructive confirmation reasons never use this path.
            return (parameters, reason in {"multi_unit", "report_scope"}, allowed)
        if affirmative:
            return ({}, True, set())
        return None

    def continue_after_clarification(
        self, user_id: str, pending: dict[str, Any], message: str
    ) -> dict[str, Any] | None:
        """Resume the same durable AgentRun after applying an allowlisted clarification."""
        text = str(message or "").strip()
        runtime_ctx = dict(pending.get("runtime_context") or {})
        plan = cast("PlanGraph | None", pending.get("plan"))
        run_id = str(pending.get("agent_run_id") or "").strip()
        if plan is None or not run_id:
            return _control_reply(
                "澄清记录缺少可恢复的执行计划，未执行任何操作；请重新提交完整请求。",
                "workflow_resume_failed",
                {"plan_id": getattr(plan, "plan_id", "")},
                success=False,
                message="澄清计划缺失",
            )[1]
        if text.lower().rstrip("。.!！") in CANCEL_WORDS:
            if not self._cancel_pending_agent_run(user_id, pending, runtime_ctx):
                return _control_reply(
                    "取消尚未完成，待办仍保留；请重试。",
                    "workflow_cancel_failed",
                    {"run_id": run_id, "plan_id": plan.plan_id},
                    success=False,
                    message="任务取消尚未完成",
                )[1]
            if not self.callbacks._persist_plan_state(plan, runtime_ctx, status="cancelled"):
                return _control_reply(
                    "取消状态未能保存，待办仍保留；请重试。",
                    "workflow_cancel_failed",
                    {"run_id": run_id, "plan_id": plan.plan_id},
                    success=False,
                    message="任务取消尚未保存",
                )[1]
            self.pending.pop(user_id, None)
            return _control_reply(
                "已取消本次工作流执行。", "workflow_cancelled", {"plan_id": plan.plan_id}
            )[1]

        try:
            from app.application.agent_orchestrator import AgentOrchestrator
            from app.application.agent_orchestrator.clarification import ClarificationAnswerError
            from app.application.workflow.clarification_node import entry_is_expired
            from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict

            if entry_is_expired(pending):
                if not self._cancel_pending_agent_run(user_id, pending, runtime_ctx):
                    return _control_reply(
                        "澄清已超时，但原执行记录暂时无法终止；未执行待确认步骤，请稍后重试。",
                        "workflow_cancel_failed",
                        {"run_id": run_id, "plan_id": plan.plan_id},
                        success=False,
                        message="过期任务尚未终止",
                    )[1]
                self.callbacks._persist_plan_state(plan, runtime_ctx, status="cancelled")
                self.pending.pop(user_id, None)
                return _control_reply(
                    "这条澄清已超时，原执行保持暂停且未继续；请重新提交请求。",
                    "workflow_clarification_expired",
                    {"run_id": run_id, "plan_id": plan.plan_id},
                    success=False,
                    message="澄清已过期",
                )[1]
            orchestrator = AgentOrchestrator()
            run = orchestrator.get_run(run_id)
            owner_id = self.callbacks._task_owner_id(user_id, runtime_ctx)
            if run is None or run.user_id not in {user_id, owner_id} or run.plan_id != plan.plan_id:
                return _control_reply(
                    "澄清记录已失效或不属于当前任务，未执行任何操作；请重新发起。",
                    "workflow_confirmation_stale",
                    {"run_id": run_id, "plan_id": plan.plan_id},
                    success=False,
                    message="澄清任务不匹配",
                )[1]
            run_context = dict(run.metadata.get("runtime_context") or {})
            if str(run_context.get("tenant_id") or "") != str(
                runtime_ctx.get("tenant_id") or ""
            ) or str(
                run_context.get("session_id") or run_context.get("conversation_id") or ""
            ) != str(runtime_ctx.get("session_id") or runtime_ctx.get("conversation_id") or ""):
                return _control_reply(
                    "澄清记录与当前租户或会话不匹配，未执行任何操作。",
                    "workflow_confirmation_stale",
                    {"run_id": run_id, "plan_id": plan.plan_id},
                    success=False,
                    message="澄清上下文不匹配",
                )[1]
            persisted_plan = plan_from_dict(run.metadata.get("plan"))
            if persisted_plan is None or plan_fingerprint(persisted_plan) != plan_fingerprint(plan):
                return _control_reply(
                    "待澄清计划已变化，未执行任何操作；请重新规划任务。",
                    "workflow_confirmation_stale",
                    {"run_id": run_id, "plan_id": plan.plan_id},
                    success=False,
                    message="澄清计划已变化",
                )[1]
            from app.application.agent_orchestrator.clarification import find_waiting_step

            waiting = find_waiting_step(
                run, approved_step_id=str(pending.get("clarification_step_id") or "")
            )
            if waiting is None or (waiting.tool_id, waiting.action) != ("clarify", "ask"):
                return _control_reply(
                    "原澄清步骤已变化，未执行任何操作；请重新发起。",
                    "workflow_confirmation_stale",
                    {"run_id": run_id, "plan_id": plan.plan_id},
                    success=False,
                    message="澄清步骤已变化",
                )[1]
            if not str(waiting.params.get("target_node_id") or ""):
                if run.tool_calls or any(
                    step.status == "completed" and (step.tool_id, step.action) != ("clarify", "ask")
                    for step in run.steps
                ):
                    return _control_reply(
                        "当前澄清未绑定具体业务步骤，且原计划已有步骤运行；为避免重复执行，原计划保持暂停，请提供新的完整请求。",
                        "workflow_clarification_unbound",
                        {"run_id": run_id, "plan_id": plan.plan_id},
                        success=False,
                        message="澄清未绑定业务节点",
                    )[1]
                if not self._cancel_pending_agent_run(user_id, pending, runtime_ctx):
                    return _control_reply(
                        "原澄清计划无法安全结束，未启动新计划；请核对任务状态。",
                        "workflow_resume_failed",
                        {"run_id": run_id, "plan_id": plan.plan_id},
                        success=False,
                        message="原澄清计划仍暂停",
                    )[1]
                self.callbacks._persist_plan_state(plan, runtime_ctx, status="cancelled")
                self.pending.pop(user_id, None)
                combined = f"原始请求：{run.message}\n用户补充：{text}"
                replanned = self.callbacks._dispatch_model_selection(
                    user_id,
                    combined,
                    str(runtime_ctx.get("source") or ""),
                    runtime_ctx,
                    combined,
                )
                return (
                    replanned
                    or _control_reply(
                        "补充信息已收到，但平台模型没有返回可执行计划；未执行任何业务操作，请重新描述目标。",
                        "workflow_planning_failed",
                        {"plan_id": plan.plan_id},
                        success=False,
                        message="补充后规划失败",
                    )[1]
                )
            answer = self._clarification_answer(run, waiting, text)
            if answer is None:
                question = str(
                    waiting.output.get("question")
                    or waiting.params.get("question")
                    or "请按问题补充信息。"
                )
                return _control_reply(
                    f"我还不能安全确定答案，请直接回答当前问题。\n{question}",
                    "clarification_required",
                    {"requires_confirmation": True, "run_id": run_id, "plan_id": plan.plan_id},
                    message="需要补充信息",
                )[1]
            parameters, confirmed, allowed_fields = answer
            parameters = {
                key: int(value)
                if (key == "id" or key.endswith(".id"))
                and isinstance(value, str)
                and value.isdigit()
                else value
                for key, value in parameters.items()
            }
            if isinstance(parameters.get("payload"), dict):
                payload_patch = dict(parameters["payload"])
                if isinstance(payload_patch.get("id"), str) and payload_patch["id"].isdigit():
                    payload_patch["id"] = int(payload_patch["id"])
                    parameters = {**parameters, "payload": payload_patch}
            continued = orchestrator.continue_after_clarification(
                run_id,
                answered_by=run.user_id,
                clarification_step_id=waiting.step_id,
                parameters=parameters,
                confirmed=confirmed,
                allowed_fields=allowed_fields,
                runtime_context=runtime_ctx,
            )
            if continued is None:
                return _control_reply(
                    "澄清答案未能绑定到当前执行记录，原计划仍暂停；请重新回答或重新发起。",
                    "workflow_resume_failed",
                    {"run_id": run_id, "plan_id": plan.plan_id},
                    success=False,
                    message="澄清续跑失败",
                )[1]
            updated_plan = plan_from_dict(continued.metadata.get("plan"))
            updated_plan = updated_plan or persisted_plan
            if continued.status == "waiting_user":
                interaction = self.capture_agent_run_interaction(
                    user_id=user_id,
                    agent_run=continued,
                    runtime_context=runtime_ctx,
                    thinking_steps=str(pending.get("thinking_steps") or ""),
                    decision_reason="已补充澄清信息，下一步需要确认",
                    approval_nodes=pending.get("approval_nodes") or [],
                )
                return (
                    interaction
                    or _control_reply(
                        "AgentRun 已暂停，但找不到对应的待处理交互；未切换到备用执行路径。",
                        "workflow_resume_failed",
                        {"run_id": continued.run_id, "plan_id": updated_plan.plan_id},
                        success=False,
                        message="待处理交互缺失",
                    )[1]
                )
            self.pending.pop(user_id, None)
            self.callbacks._persist_plan_state(
                updated_plan,
                runtime_ctx,
                status="succeeded" if continued.status == "completed" else "failed",
                message=str(continued.error or ""),
            )
            return self.callbacks._format_agent_run_response(
                updated_plan,
                continued,
                thinking_steps=str(pending.get("thinking_steps") or ""),
                user_message=str(runtime_ctx.get("message") or run.message or ""),
            )
        except ClarificationAnswerError as exc:
            return _control_reply(
                f"{exc}；原计划仍暂停，未执行待确认步骤。",
                "clarification_required",
                {"run_id": run_id, "plan_id": plan.plan_id},
                message="答案需要核对",
            )[1]
        except RECOVERABLE_ERRORS:
            logger.exception("澄清后通过 AgentRun 恢复执行失败 run_id=%s", run_id)
            return _control_reply(
                "澄清续跑失败，原计划保持暂停；请核对执行状态后重试。",
                "workflow_resume_failed",
                {"run_id": run_id, "plan_id": plan.plan_id},
                success=False,
                message="澄清续跑失败",
            )[1]

    def resume_pending_dynamic_workflow(
        self,
        user_id: str,
        message: str,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        text = text.strip().lower().rstrip("。.!！")
        context = context or {}
        session_id = str(context.get("session_id") or context.get("conversation_id") or "")
        control = text in CONFIRM_WORDS | CANCEL_WORDS
        pending = self.pending.get(user_id)
        if pending:
            runtime = pending.get("runtime_context") or {}
            pending_session = str(runtime.get("session_id") or runtime.get("conversation_id") or "")
            if (session_id or pending_session) and pending_session != session_id:
                pending = None
        if not pending and session_id:
            if self.callbacks._hydrate_pending_workflow(user_id, session_id):
                pending = self.pending.get(user_id)
        # Inline cards bind a control to the plan the user actually clicked.
        # Older clients omit this field and retain their existing session contract.
        if "expected_workflow_plan_id" in context:
            expected = context["expected_workflow_plan_id"]
            actual = getattr((pending or {}).get("plan"), "plan_id", None)
            if not isinstance(expected, str) or not expected.strip() or expected != actual:
                return _control_reply(
                    "此确认卡对应的计划已失效或已变化，请返回原任务核对后重试；未执行本次操作。",
                    "workflow_confirmation_stale",
                    {"plan_id": expected if isinstance(expected, str) else ""},
                    success=False,
                    message="待确认计划不匹配",
                )
        invalid_plan = False
        if control and pending:
            from app.application.workflow.workflow_types import (
                PlanGraph,
                validate_plan_graph,
            )

            try:
                plan = pending.get("plan")
                invalid_plan = not isinstance(plan, PlanGraph) or bool(validate_plan_graph(plan))
            except (AttributeError, TypeError, ValueError):
                invalid_plan = True
        if control and (not pending or invalid_plan):
            reply = (
                "原待办计划缺失或损坏，请返回原任务核对后重新提交；未执行任何操作。"
                if invalid_plan
                else "请说明要确认什么，或回到原任务继续处理；当前会话没有待确认的操作。"
            )
            return _control_reply(
                reply,
                "clarification_required",
                success=not invalid_plan,
                message="需要澄清",
            )
        if pending:
            if pending.get("kind") in {"clarification", "clarification_unbound"}:
                clarification_reply = self.callbacks._continue_after_clarification(
                    user_id, pending, message
                )
                return (True, clarification_reply)
            if text in CONFIRM_WORDS:
                pending_plan = cast("PlanGraph", pending.get("plan"))
                runtime_ctx = dict(pending.get("runtime_context") or {})
                approval_required = bool(pending.get("approval_required"))
                approval_nodes = pending.get("approval_nodes") or []
                if approval_required and not approval_nodes:
                    return _control_reply(
                        "审批步骤信息缺失，原计划未执行；请返回任务重新发起。",
                        "approval_failed",
                        {"plan_id": pending_plan.plan_id},
                        success=False,
                        message="审批步骤缺失",
                    )
                from app.application.agent_orchestrator import AgentOrchestrator
                from app.application.workflow.workflow_types import plan_from_dict

                orchestrator = AgentOrchestrator()
                agent_run_id = str(pending.get("agent_run_id") or "").strip()
                if agent_run_id:
                    continued = orchestrator.continue_run(
                        agent_run_id,
                        approved_by=self.callbacks._task_owner_id(user_id, runtime_ctx),
                        runtime_context=runtime_ctx,
                    )
                elif approval_required:
                    approved_plan = copy.deepcopy(pending_plan)
                    required_ids = [str(item.get("node_id") or "") for item in approval_nodes]
                    if not required_ids or any(
                        not any(node.node_id == required_id for node in approved_plan.nodes)
                        for required_id in required_ids
                    ):
                        return _control_reply(
                            "审批节点不属于原完整计划，已阻止执行；请重新发起。",
                            "approval_failed",
                            {"plan_id": pending_plan.plan_id},
                            success=False,
                            message="审批计划校验失败",
                        )
                    # Bind policy-mandated approvals into the durable graph before execution.
                    approved_plan.metadata["approval_required_node_ids"] = required_ids
                    continued = orchestrator.start_run_from_plan(
                        user_id=self.callbacks._task_owner_id(user_id, runtime_ctx),
                        message=str(runtime_ctx.get("message") or message),
                        plan=approved_plan,
                        runtime_context=runtime_ctx,
                        auto_execute=True,
                    )
                else:
                    return _control_reply(
                        "待确认计划没有可恢复的 AgentRun，未执行任何操作；请重新提交请求。",
                        "workflow_resume_failed",
                        {"plan_id": pending_plan.plan_id},
                        success=False,
                        message="执行记录缺失",
                    )
                if continued is None:
                    return _control_reply(
                        "原执行记录无法恢复，未启动备用执行路径；请核对任务状态后重新发起。",
                        "workflow_resume_failed",
                        {"run_id": agent_run_id, "plan_id": pending_plan.plan_id},
                        success=False,
                        message="工作流续跑失败",
                    )
                if continued.status == "waiting_user":
                    interaction = self.capture_agent_run_interaction(
                        user_id=user_id,
                        agent_run=continued,
                        runtime_context=runtime_ctx,
                        thinking_steps=str(pending.get("thinking_steps") or ""),
                        decision_reason="确认已收到，下一步需要用户输入",
                        approval_nodes=approval_nodes,
                    )
                    return (True, interaction)
                self.pending.pop(user_id, None)
                continued_plan = plan_from_dict(continued.metadata.get("plan")) or pending_plan
                self.callbacks._persist_plan_state(
                    continued_plan,
                    runtime_ctx,
                    status="succeeded" if continued.status == "completed" else "failed",
                    message=str(continued.error or ""),
                )
                return (
                    True,
                    self.callbacks._format_agent_run_response(
                        continued_plan,
                        continued,
                        thinking_steps=str(pending.get("thinking_steps") or ""),
                        user_message=str(runtime_ctx.get("message") or continued.message or ""),
                    ),
                )
            if text in CANCEL_WORDS:
                runtime = dict(pending.get("runtime_context") or {})
                runtime.setdefault("user_id", user_id)
                plan = pending["plan"]
                if not self._cancel_pending_agent_run(user_id, pending, runtime):
                    return _control_reply(
                        "任务取消尚未完成，请重试；待办仍保留。",
                        "workflow_cancel_failed",
                        {
                            "plan_id": plan.plan_id,
                            "run_id": pending.get("agent_run_id", ""),
                        },
                        success=False,
                        message="任务取消尚未完成",
                    )
                if not self.callbacks._persist_plan_state(plan, runtime, status="cancelled"):
                    return True, {
                        "success": False,
                        "message": "取消未保存，请重试；计划仍保留待处理。",
                        "response": "取消未保存，请重试；计划仍保留待处理。",
                        "data": {
                            "action": "workflow_cancel_failed",
                            "plan_id": plan.plan_id,
                        },
                    }
                self.pending.pop(user_id, None)
                return _control_reply(
                    "已取消本次工作流执行。",
                    "workflow_cancelled",
                    {"plan_id": plan.plan_id, "task_id": runtime.get("task_id", "")},
                )
            plan = pending["plan"]
            return _control_reply(
                "原操作仍在等待确认，尚未执行；请先回复「确认」或「取消」，再处理新的请求。",
                "workflow_confirmation_required",
                _enrich_confirmation_inner(
                    {
                        "plan_id": plan.plan_id,
                        "run_id": str(pending.get("agent_run_id") or ""),
                        "requires_confirmation": True,
                        "approval_required": bool(pending.get("approval_required")),
                        "approval_nodes": pending.get("approval_nodes") or [],
                    },
                    action="workflow_confirmation_required",
                ),
            )
        return (False, None)
