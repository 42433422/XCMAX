# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Pending-workflow resume behavior for the AI chat service."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat_app_service")


CONFIRM_WORDS = {"确认", "是", "是的", "好的", "好", "继续", "执行", "确认执行", "ok", "yes"}
CANCEL_WORDS = {"取消", "否", "不要", "停止", "no"}


def _control_reply(text, action, data=None, *, success=True, message="处理完成", display_text=None):
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


class _DynamicWorkflowPendingResumeMixin:
    def _resume_pending_dynamic_workflow(self, user_id: str, message: str, text: str, context=None):
        text = text.strip().lower().rstrip("。.!！")
        context = context or {}
        session_id = str(context.get("session_id") or context.get("conversation_id") or "")
        control = text in CONFIRM_WORDS | CANCEL_WORDS
        pending = self._pending_workflows.get(user_id)
        if pending:
            runtime = pending.get("runtime_context") or {}
            pending_session = str(runtime.get("session_id") or runtime.get("conversation_id") or "")
            if (session_id or pending_session) and pending_session != session_id:
                pending = None
        if control and not pending and session_id:
            if self._hydrate_pending_workflow(user_id, session_id):
                pending = self._pending_workflows.get(user_id)
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
                continued = self._continue_after_clarification(user_id, pending, message)
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
                pending_plan = _facade().cast("PlanGraph | None", pending.get("plan"))
                runtime_ctx = pending.get("runtime_context", {})
                approval_required = pending.get("approval_required", False)
                approval_nodes = pending.get("approval_nodes", [])
                if approval_required and approval_nodes:
                    approval_request_ids: list[str] = []
                    approval_requests: list[dict[str, _facade().Any]] = []
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
                                approved_node = _facade().copy.deepcopy(node)
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
                                    user_id=self._task_owner_id(user_id, runtime_ctx),
                                    message=str(runtime_ctx.get("message") or message),
                                    plan=approved_plan,
                                    runtime_context=runtime_ctx,
                                    auto_execute=True,
                                )
                                if agent_run.status != "waiting_user":
                                    raise RuntimeError(
                                        f"审批节点未进入安全等待态：{node.node_id} ({agent_run.status})"
                                    )
                                request = self.approval_service.create_approval_request(
                                    plan_id=pending_plan.plan_id,
                                    node=node,
                                    runtime_context=runtime_ctx,
                                    plan=approved_plan,
                                    require_persistence=True,
                                )
                                request_id = str(request.request_id or "").strip()
                                if not request_id:
                                    raise RuntimeError("审批请求缺少请求号")
                                self.approval_service.attach_pending_agent_run(
                                    request_id,
                                    agent_run_id=agent_run.run_id,
                                    approved_step_id=approved_node.node_id,
                                )
                                approval_request_ids.append(request_id)
                                metadata = self.approval_service.get_request_metadata(
                                    request_id
                                ) or {"request_no": request_id}
                                metadata["agent_run_id"] = agent_run.run_id
                                approval_requests.append(metadata)
                    except RuntimeError:
                        self._pending_workflows.pop(user_id, None)
                        return _control_reply(
                            "审批请求创建失败，数据库未写入",
                            "approval_failed",
                            {"plan_id": pending_plan.plan_id},
                            success=False,
                            message="审批请求创建失败",
                        )
                    self._pending_workflows.pop(user_id, None)
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
                        _facade()._enrich_confirmation_inner(
                            approval_inner, action="approval_pending"
                        ),
                    )
                agent_run_id = str(pending.get("agent_run_id") or "").strip()
                if agent_run_id:
                    from app.application.agent_orchestrator import AgentOrchestrator

                    continued_agent_run = AgentOrchestrator().continue_run(
                        agent_run_id, approved_by=user_id, runtime_context=runtime_ctx
                    )
                    self._pending_workflows.pop(user_id, None)
                    if continued_agent_run is not None:
                        return (
                            True,
                            self._format_agent_run_response(
                                pending_plan,
                                continued_agent_run,
                                thinking_steps=str(pending.get("thinking_steps") or ""),
                                user_message=str(runtime_ctx.get("message") or ""),
                            ),
                        )
                run_result, state_updates = self._run_workflow_with_state_updates(
                    plan=pending_plan, runtime_context=runtime_ctx, max_retries=1, resume=True
                )
                self._pending_workflows.pop(user_id, None)
                return (
                    True,
                    self._format_workflow_run_response(
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
                if not self._persist_plan_state(plan, runtime, status="cancelled"):
                    return True, {
                        "success": False,
                        "message": "取消未保存，请重试；计划仍保留待处理。",
                        "response": "取消未保存，请重试；计划仍保留待处理。",
                        "data": {"action": "workflow_cancel_failed", "plan_id": plan.plan_id},
                    }
                self._pending_workflows.pop(user_id, None)
                return _control_reply(
                    "已取消本次工作流执行。",
                    "workflow_cancelled",
                    {"plan_id": plan.plan_id, "task_id": runtime.get("task_id", "")},
                )
            plan = pending["plan"]
            return _control_reply(
                "原操作仍在等待确认，尚未执行；请先回复「确认」或「取消」，再处理新的请求。",
                "workflow_confirmation_required",
                _facade()._enrich_confirmation_inner(
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
