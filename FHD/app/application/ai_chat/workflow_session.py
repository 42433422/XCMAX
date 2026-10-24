"""Session-scoped confirmations, clarification and durable workflow transitions."""

from __future__ import annotations

import copy
import logging
import uuid
from typing import TYPE_CHECKING, Any, Protocol, cast

from app.application.ai_chat.excel_import_policy import _enrich_confirmation_inner
from app.utils.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.ports import CheckpointStore, WorkflowRuntime
    from app.application.workflow.types import PlanGraph, WorkflowRunResult

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
    def _format_workflow_run_response(
        self,
        plan: PlanGraph,
        run_result: WorkflowRunResult,
        thinking_steps: str = "",
        user_message: str = "",
        state_updates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...
    def _hydrate_pending_workflow(self, user_id: str, session_id: str) -> bool: ...
    def _persist_plan_state(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None,
        status: str,
        message: str | None = None,
    ) -> bool: ...
    def _run_workflow_with_state_updates(
        self,
        *,
        plan: PlanGraph,
        runtime_context: dict[str, Any],
        max_retries: int = 1,
        resume: bool = False,
        **kwargs: Any,
    ) -> tuple[WorkflowRunResult, list[dict[str, Any]]]: ...
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
        runtime: WorkflowRuntime | None = None,
        checkpointer: CheckpointStore | None = None,
        approval: ApprovalService | None = None,
        store: PlanStateStore | None = None,
    ) -> None:
        self.pending = pending
        self.callbacks = callbacks
        self._runtime = runtime
        self.checkpointer = checkpointer
        self._approval = approval
        self.store = store

    @property
    def runtime(self) -> WorkflowRuntime:
        if self._runtime is None:
            raise RuntimeError("Workflow execution requires a runtime")
        return self._runtime

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
            from app.application.workflow.types import plan_from_dict

            active = self._plan_store().list_active(user_id, limit=1, session_id=session_id)
            if not active or active[0].get("status") != "pending_awaiting":
                return False
            plan = plan_from_dict(active[0].get("plan") or {})
            if plan is None or not plan.nodes:
                return False
            runtime_context = dict(active[0].get("runtime_context") or {})
            confirmation = runtime_context.pop("pending_confirmation", {})
            self.pending[user_id] = {
                "plan": plan,
                "runtime_context": runtime_context,
                "pending_id": uuid.uuid4().hex,
                "thinking_steps": "",
                "kind": "workflow",
                "agent_run_id": str(confirmation.get("agent_run_id") or ""),
                "approval_required": bool(confirmation.get("approval_required")),
                "approval_nodes": confirmation.get("approval_nodes") or [],
                "hydrated_from_db": True,
            }
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
                    for key in ("agent_run_id", "approval_required", "approval_nodes")
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

    def run_workflow_with_state_updates(
        self,
        *,
        plan: PlanGraph,
        runtime_context: dict[str, Any],
        max_retries: int = 1,
        resume: bool = False,
        **kwargs: Any,
    ) -> tuple[WorkflowRunResult, list[dict[str, Any]]]:
        """运行工作流引擎，并收集每步节点完成后的 ``state.update`` 事件。

        ``resume=True`` 时从该计划在 DB 中的最新 checkpoint 断点续跑（不重复执行已完成节点），
        用于跨会话/中断恢复的长任务；返回 ``(run_result, state_updates)``。
        """
        state_updates: list[dict[str, Any]] = []

        def record_state_event(event: dict[str, Any]) -> None:
            state_updates.append(event)

        checkpointer = self.checkpointer
        self.callbacks._persist_plan_state(plan, runtime_context, status="running")
        if resume and checkpointer is not None:
            latest = checkpointer.latest_checkpoint(plan.plan_id)
            if latest is not None:
                run_result = self.runtime.resume_run(
                    plan,
                    latest["checkpoint_id"],
                    checkpointer=checkpointer,
                    max_retries=max_retries,
                )
            else:
                run_result = self.runtime.run(
                    plan=plan,
                    runtime_context=runtime_context,
                    max_retries=max_retries,
                    state_event_callback=record_state_event,
                    checkpointer=checkpointer,
                    **kwargs,
                )
        else:
            run_result = self.runtime.run(
                plan=plan,
                runtime_context=runtime_context,
                max_retries=max_retries,
                state_event_callback=record_state_event,
                checkpointer=checkpointer,
                **kwargs,
            )
        self.callbacks._persist_plan_state(
            plan,
            runtime_context,
            status="succeeded" if run_result.success else "failed",
            message=str(run_result.message or ""),
        )
        return (run_result, state_updates)

    def sweep_expired_clarifications(self) -> list[str]:
        """扫描并移除过期的"澄清待确认"记录（TTL 防堆积）。"""
        from app.application.workflow.clarification_node import sweep_expired

        return sweep_expired(self.pending)

    def open_clarification_gate(
        self,
        *,
        user_id: str,
        plan: PlanGraph,
        tool_registry: dict[str, Any],
        runtime_context: dict[str, Any],
        thinking_steps: str,
        message: str,
    ) -> dict[str, Any] | None:
        """显示独立澄清问题，或暂停缺参数的业务节点。"""
        for node in plan.nodes or []:
            if (node.tool_id, node.action) == ("clarify", "ask") and not node.params.get(
                "target_node_id"
            ):
                question = str(node.params.get("question") or "请补充业务操作和参数。")
                return {
                    "success": True,
                    "message": "需要澄清",
                    "response": question,
                    "data": {"text": question, "action": "clarification_required", "data": {}},
                }
        from app.application.workflow.clarification_node import (
            build_clarify_node,
            insert_clarify_node,
            make_pending_entry,
            needs_clarification,
        )

        clarify_items = needs_clarification(plan, tool_registry)
        if not clarify_items:
            return None
        item = clarify_items[0]
        target = next((n for n in plan.nodes if n.node_id == item["node_id"]), None)
        if target is None:
            return None
        clarify_node = build_clarify_node(
            item.get("question") or "请确认目标后再执行写操作。",
            ambient={
                "target_node_id": target.node_id,
                "answer_key": item.get("field") or "confirmed",
            },
        )
        insert_clarify_node(plan, clarify_node)
        runtime_context["_clarify_node_id"] = clarify_node.node_id
        self.runtime.run(
            plan=plan,
            runtime_context=runtime_context,
            max_retries=1,
            checkpointer=self.checkpointer,
        )
        self.pending[user_id] = make_pending_entry(
            plan=plan,
            runtime_context=runtime_context,
            thinking_steps=thinking_steps,
            clarification=item,
            clarify_node_id=clarify_node.node_id,
            target_node_id=target.node_id,
        )
        self.callbacks._persist_plan_state(plan, runtime_context, status="pending_awaiting")
        question = item.get("question") or "请确认目标后再执行写操作。"
        clarify_inner = {
            "plan_id": plan.plan_id,
            "intent": plan.intent,
            "requires_confirmation": True,
            "reason": item.get("reason"),
            "field": item.get("field"),
            "candidates": item.get("candidates") or [],
            "missing_fields": item.get("missing_fields") or [],
            "target_node_id": target.node_id,
            "ttl_seconds": self.pending[user_id]["ttl_seconds"],
        }
        return {
            "success": True,
            "message": "需要澄清",
            "response": question,
            "data": {"text": question, "action": "clarification_required", "data": clarify_inner},
        }

    def continue_after_clarification(
        self, user_id: str, pending: dict[str, Any], message: str
    ) -> dict[str, Any] | None:
        """处理澄清待确认的回复：取消 / 解析唯一目标后继续执行。

        已处理（取消或继续执行）返回响应；无法唯一确定目标返回 None（保留 pending 继续追问）。
        """
        text = str(message or "").strip()
        cancel_words = {"取消", "否", "不要", "停止", "no"}
        if text.lower() in cancel_words or text in cancel_words:
            self.pending.pop(user_id, None)
            return {
                "success": True,
                "message": "处理完成",
                "response": "已取消本次待澄清操作。",
                "data": {
                    "text": "已取消本次待澄清操作。",
                    "action": "workflow_cancelled",
                    "data": {},
                },
            }
        from app.application.workflow.clarification_node import resolve_confirmed_target

        plan = cast("PlanGraph | None", pending.get("plan"))
        if plan is None:
            self.pending.pop(user_id, None)
            return None
        runtime_ctx = dict(pending.get("runtime_context") or {})
        item = pending.get("clarification") or {}
        clarify_node_id = pending.get("clarify_node_id")
        target_node_id = pending.get("target_node_id")
        target = next((n for n in plan.nodes if n.node_id == target_node_id), None)
        if target is None:
            self.pending.pop(user_id, None)
            return None
        candidates = item.get("candidates") or []
        confirmed = resolve_confirmed_target(text, candidates)
        if confirmed is None and target.tool_id == "business_db" and (not candidates):
            from app.services.tools_workflow_registered import prepare_business_db_write_target

            entity = str(target.params.get("entity") or "")
            selector: dict[str, Any]
            if text.isdigit():
                selector = {"id": int(text)}
            else:
                natural_fields = {
                    "customers": "customer_name",
                    "products": "product_name",
                    "materials": "material_name",
                }
                natural_field = natural_fields.get(entity)
                selector = {natural_field: text} if natural_field else {}
            payload = dict(target.params.get("payload") or {})
            payload["selector"] = selector
            resolved = prepare_business_db_write_target(
                entity, str(target.params.get("operation") or ""), payload
            )
            if resolved.get("success"):
                target.params["payload"] = resolved["payload"]
                confirmed = {"id": int(resolved["payload"]["id"])}
        if confirmed is None:
            return None
        if target.tool_id == "business_db":
            payload = dict(target.params.get("payload") or {})
            payload["id"] = int(confirmed["id"])
            target.params["payload"] = payload
        else:
            target.params.update(confirmed)
        target.params.pop("candidates", None)
        target.params.pop("_candidates", None)
        runtime_ctx["_clarify_answers"] = {clarify_node_id: {"confirmed": True, **confirmed}}
        self.pending.pop(user_id, None)
        (run_result, state_updates) = self.callbacks._run_workflow_with_state_updates(
            plan=plan, runtime_context=runtime_ctx, max_retries=1, resume=True
        )
        return self.callbacks._format_workflow_run_response(
            plan,
            run_result,
            thinking_steps=str(pending.get("thinking_steps") or ""),
            user_message=str(runtime_ctx.get("message") or ""),
            state_updates=state_updates,
        )

    def resume_pending_dynamic_workflow(
        self, user_id: str, message: str, text: str, context: dict[str, Any] | None = None
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
        if control and not pending and session_id:
            if self.callbacks._hydrate_pending_workflow(user_id, session_id):
                pending = self.pending.get(user_id)
        invalid_plan = False
        if control and pending:
            from app.application.workflow.types import PlanGraph, validate_plan_graph

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
                reply, "clarification_required", success=not invalid_plan, message="需要澄清"
            )
        if pending:
            if pending.get("kind") == "clarification":
                continued = self.callbacks._continue_after_clarification(user_id, pending, message)
                if continued is not None:
                    return (True, continued)
                return _control_reply(
                    "仍无法唯一确定操作目标，请回复候选序号或唯一 ID（例如「1」）。",
                    "clarification_required",
                    {"requires_confirmation": True},
                    message="需要澄清",
                    display_text="仍无法唯一确定操作目标，请回复候选序号或唯一 ID。",
                )
            if text in CONFIRM_WORDS:
                pending_plan = cast("PlanGraph", pending.get("plan"))
                runtime_ctx = pending.get("runtime_context", {})
                approval_required = pending.get("approval_required", False)
                approval_nodes = pending.get("approval_nodes", [])
                if approval_required and approval_nodes:
                    approval_request_ids: list[str] = []
                    approval_requests: list[dict[str, Any]] = []
                    try:
                        from app.application.agent_orchestrator import AgentOrchestrator
                        from app.application.workflow.types import PlanGraph

                        for node_info in approval_nodes:
                            node = None
                            for n in pending_plan.nodes:
                                if n.node_id == node_info.get("node_id"):
                                    node = n
                                    break
                            if node:
                                approved_node = copy.deepcopy(node)
                                approved_node.depends_on = []
                                approved_node.next = None
                                approved_node.branches = []
                                approved_plan = PlanGraph(
                                    plan_id=f"{pending_plan.plan_id}:{node.node_id}",
                                    intent=pending_plan.intent,
                                    todo_steps=[
                                        node.description or f"{node.tool_id}.{node.action}"
                                    ],
                                    nodes=[approved_node],
                                    risk_level=node.risk,
                                    metadata={
                                        **dict(pending_plan.metadata or {}),
                                        "approval_parent_plan_id": pending_plan.plan_id,
                                        "approval_parent_node_id": node.node_id,
                                    },
                                )
                                agent_run = AgentOrchestrator().start_run_from_plan(
                                    user_id=self.callbacks._task_owner_id(user_id, runtime_ctx),
                                    message=str(runtime_ctx.get("message") or message),
                                    plan=approved_plan,
                                    runtime_context=runtime_ctx,
                                    auto_execute=True,
                                )
                                if agent_run.status != "waiting_user":
                                    raise RuntimeError(
                                        f"审批节点未进入安全等待态：{node.node_id} ({agent_run.status})"
                                    )
                                request = self.approval.create_approval_request(
                                    plan_id=pending_plan.plan_id,
                                    node=node,
                                    runtime_context=runtime_ctx,
                                    plan=approved_plan,
                                    require_persistence=True,
                                )
                                request_id = str(request.request_id or "").strip()
                                if not request_id:
                                    raise RuntimeError("审批请求缺少请求号")
                                self.approval.attach_pending_agent_run(
                                    request_id,
                                    agent_run_id=agent_run.run_id,
                                    approved_step_id=approved_node.node_id,
                                )
                                approval_request_ids.append(request_id)
                                metadata = self.approval.get_request_metadata(request_id) or {
                                    "request_no": request_id
                                }
                                metadata["agent_run_id"] = agent_run.run_id
                                approval_requests.append(metadata)
                    except RuntimeError:
                        self.pending.pop(user_id, None)
                        return _control_reply(
                            "审批请求创建失败，数据库未写入",
                            "approval_failed",
                            {"plan_id": pending_plan.plan_id},
                            success=False,
                            message="审批请求创建失败",
                        )
                    self.pending.pop(user_id, None)
                    approval_path = str(
                        (approval_requests[0] if approval_requests else {}).get("approval_path")
                        or "/mod/xcagi-approval-bridge/approval-hub/workspace"
                    )
                    approval_inner = {
                        "plan_id": pending_plan.plan_id,
                        "approval_required": True,
                        "approval_nodes": approval_nodes,
                        "approval_request_ids": approval_request_ids,
                        "approval_requests": approval_requests,
                        "approval_path": approval_path,
                    }
                    return _control_reply(
                        f"已提交审批请求：{', '.join(approval_request_ids)}。请前往审批工作台逐笔处理。",
                        "approval_pending",
                        _enrich_confirmation_inner(approval_inner, action="approval_pending"),
                    )
                agent_run_id = str(pending.get("agent_run_id") or "").strip()
                if agent_run_id:
                    from app.application.agent_orchestrator import AgentOrchestrator

                    continued_agent_run = AgentOrchestrator().continue_run(
                        agent_run_id, approved_by=user_id, runtime_context=runtime_ctx
                    )
                    self.pending.pop(user_id, None)
                    if continued_agent_run is not None:
                        return (
                            True,
                            self.callbacks._format_agent_run_response(
                                pending_plan,
                                continued_agent_run,
                                thinking_steps=str(pending.get("thinking_steps") or ""),
                                user_message=str(runtime_ctx.get("message") or ""),
                            ),
                        )
                run_result, state_updates = self.callbacks._run_workflow_with_state_updates(
                    plan=pending_plan, runtime_context=runtime_ctx, max_retries=1, resume=True
                )
                self.pending.pop(user_id, None)
                return (
                    True,
                    self.callbacks._format_workflow_run_response(
                        pending_plan,
                        run_result,
                        user_message=str(runtime_ctx.get("message") or ""),
                        state_updates=state_updates,
                    ),
                )
            if text in CANCEL_WORDS:
                runtime = dict(pending.get("runtime_context") or {})
                runtime.setdefault("user_id", user_id)
                plan = pending["plan"]
                if not self.callbacks._persist_plan_state(plan, runtime, status="cancelled"):
                    return True, {
                        "success": False,
                        "message": "取消未保存，请重试；计划仍保留待处理。",
                        "response": "取消未保存，请重试；计划仍保留待处理。",
                        "data": {"action": "workflow_cancel_failed", "plan_id": plan.plan_id},
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
