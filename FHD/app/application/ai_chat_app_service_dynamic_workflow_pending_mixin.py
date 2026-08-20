# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Pending-workflow resume behavior for the AI chat service."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat_app_service")


class _DynamicWorkflowPendingResumeMixin:
    def _resume_pending_dynamic_workflow(self, user_id: str, message: str, text: str):
        confirm_words = {"确认", "是", "好的", "继续", "执行", "ok", "yes"}
        cancel_words = {"取消", "否", "不要", "停止", "no"}
        _resume_msg = (message or "").strip().lower()
        if user_id not in self._pending_workflows and (
            _resume_msg in {w.lower() for w in confirm_words}
            or _resume_msg in {w.lower() for w in cancel_words}
        ):
            self._hydrate_pending_workflow(user_id)
        pending = self._pending_workflows.get(user_id)
        if pending:
            if pending.get("kind") == "clarification":
                continued = self._continue_after_clarification(user_id, pending, message)
                if continued is not None:
                    return (True, continued)
                return (
                    True,
                    {
                        "success": True,
                        "message": "需要澄清",
                        "response": "仍无法唯一确定操作目标，请回复候选序号或唯一 ID（例如「1」）。",
                        "data": {
                            "text": "仍无法唯一确定操作目标，请回复候选序号或唯一 ID。",
                            "action": "clarification_required",
                            "data": {"requires_confirmation": True},
                        },
                    },
                )
            if text.lower() in confirm_words or text in confirm_words:
                pending_plan = _facade().cast("PlanGraph | None", pending.get("plan"))
                if pending_plan is None:
                    self._pending_workflows.pop(user_id, None)
                    return (True, None)
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
                                    metadata=dict(pending_plan.metadata or {}),
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
                    except RuntimeError as exc:
                        self._pending_workflows.pop(user_id, None)
                        return (
                            True,
                            {
                                "success": False,
                                "message": "审批请求创建失败",
                                "response": f"审批请求创建失败，数据库未写入：{exc}",
                                "data": {
                                    "text": f"审批请求创建失败，数据库未写入：{exc}",
                                    "action": "approval_failed",
                                    "data": {"plan_id": pending_plan.plan_id},
                                },
                            },
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
                    return (
                        True,
                        {
                            "success": True,
                            "message": "处理完成",
                            "response": f"已提交审批请求：{', '.join(approval_request_ids)}。请前往审批工作台逐笔处理。",
                            "data": {
                                "text": f"已提交审批请求：{', '.join(approval_request_ids)}。请前往审批工作台逐笔处理。",
                                "action": "approval_pending",
                                "data": _facade()._enrich_confirmation_inner(
                                    approval_inner, action="approval_pending"
                                ),
                            },
                        },
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
            if text.lower() in cancel_words or text in cancel_words:
                self._pending_workflows.pop(user_id, None)
                return (
                    True,
                    {
                        "success": True,
                        "message": "处理完成",
                        "response": "已取消本次工作流执行。",
                        "data": {
                            "text": "已取消本次工作流执行。",
                            "action": "workflow_cancelled",
                            "data": {},
                        },
                    },
                )
        return (False, None)
