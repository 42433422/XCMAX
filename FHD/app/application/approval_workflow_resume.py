"""Extracted helpers for an existing public module."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


def _resume_pending_ai_workflow_after_approval(
    *, request_no: str, opinion: str
) -> dict[str, Any] | None:
    """工作台审批通过后，继续执行由 AI 工作流创建的 pending workflow。"""
    approval_request_id = str(request_no or "").strip()
    if not approval_request_id:
        return None
    try:
        from app.application.workflow import WorkflowEngine, get_approval_service
        from app.fastapi_routes.domains.misc.helpers import _dispatch_tool_for_approval

        approval_service = get_approval_service()
        approved_in_memory = approval_service.approve(approval_request_id, opinion)
        workflow_data = approval_service.get_pending_workflow(approval_request_id)
        if not workflow_data:
            with get_db() as db:
                persisted = (
                    db.query(ApprovalRequest)
                    .filter(ApprovalRequest.request_no == approval_request_id)
                    .first()
                )
                persisted_data = persisted.to_dict().get("business_data") if persisted else {}
            persisted_data = persisted_data if isinstance(persisted_data, dict) else {}
            persisted_run_id = str(persisted_data.get("agent_run_id") or "").strip()
            if persisted_run_id:
                from app.application.agent_orchestrator import AgentOrchestrator
                from app.application.ai_chat_app_service import AIChatApplicationService

                persisted_run = AgentOrchestrator().get_run(persisted_run_id)
                if persisted_run is not None:
                    persisted_runtime = dict(
                        (getattr(persisted_run, "metadata", None) or {}).get("runtime_context")
                        or {}
                    )
                    persisted_runtime["agent_run_id"] = persisted_run_id
                    persisted_runtime["approval_node_id"] = str(
                        persisted_data.get("approval_node_id")
                        or persisted_data.get("node_id")
                        or ""
                    )
                    workflow_data = {
                        "plan": AIChatApplicationService._plan_from_agent_run(persisted_run),
                        "runtime_context": persisted_runtime,
                    }
            if not workflow_data:
                return None

        plan_obj = workflow_data.get("plan")
        runtime_ctx = workflow_data.get("runtime_context", {})
        if not plan_obj:
            approval_service.remove_pending_workflow(approval_request_id)
            return {
                "workflow_executed": False,
                "approval_request_id": approval_request_id,
                "approved_in_memory": approved_in_memory,
                "message": "审批已通过，但缺少可恢复的工作流计划",
            }

        agent_run_id = str((runtime_ctx or {}).get("agent_run_id") or "").strip()
        if agent_run_id:
            from app.application.agent_orchestrator import AgentOrchestrator

            node_id = ""
            pending_request = approval_service.get_pending_request(approval_request_id)
            if pending_request is not None:
                node_id = str(getattr(pending_request, "node_id", "") or "").strip()
            if not node_id:
                node_id = str((runtime_ctx or {}).get("approval_node_id") or "").strip()
            continued = AgentOrchestrator().continue_run(
                agent_run_id,
                approved_by=f"approval:{approval_request_id}",
                approved_step_id=node_id,
                runtime_context=dict(runtime_ctx or {}),
                auto_execute=True,
            )
            approval_service.remove_pending_workflow(approval_request_id)
            if continued is None:
                return {
                    "workflow_executed": False,
                    "approval_request_id": approval_request_id,
                    "approved_in_memory": approved_in_memory,
                    "success": False,
                    "agent_run_id": agent_run_id,
                    "message": "审批已通过，但持久化任务恢复失败",
                }
            return {
                "workflow_executed": continued.status == "completed",
                "approval_request_id": approval_request_id,
                "approved_in_memory": approved_in_memory,
                "success": continued.status == "completed",
                "agent_run_id": agent_run_id,
                "agent_status": continued.status,
                "plan_id": getattr(continued, "plan_id", ""),
                "intent": getattr(continued, "intent", ""),
                "message": (
                    "持久化任务已恢复并执行完成"
                    if continued.status == "completed"
                    else f"持久化任务恢复后状态为 {continued.status}"
                ),
                "nodes_executed": len(
                    [
                        step
                        for step in (getattr(continued, "steps", None) or [])
                        if getattr(step, "status", "") == "completed"
                    ]
                ),
                "nodes_total": len(getattr(continued, "steps", None) or []),
            }

        engine = WorkflowEngine(tool_dispatcher=_dispatch_tool_for_approval)
        run_result = engine.run(plan=plan_obj, runtime_context=runtime_ctx, max_retries=1)
        approval_service.remove_pending_workflow(approval_request_id)
        return {
            "workflow_executed": True,
            "approval_request_id": approval_request_id,
            "approved_in_memory": approved_in_memory,
            "success": bool(run_result.success),
            "plan_id": getattr(plan_obj, "plan_id", ""),
            "intent": getattr(plan_obj, "intent", ""),
            "message": str(run_result.message or ""),
            "nodes_executed": len(run_result.node_results or []),
            "nodes_total": len(getattr(plan_obj, "nodes", []) or []),
            "node_results": [
                {
                    "node_id": item.node_id,
                    "tool_id": item.tool_id,
                    "action": item.action,
                    "success": bool(item.success),
                    "error": str(item.error or "")[:240],
                    "retries": int(getattr(item, "retries", 0) or 0),
                    "retryable": bool(getattr(item, "retryable", True)),
                    "recovery_hint": str(getattr(item, "recovery_hint", "") or "")[:240],
                }
                for item in (run_result.node_results or [])[:10]
            ],
        }
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "resume pending AI workflow after approval failed request_no=%s: %s",
            approval_request_id,
            exc,
            exc_info=True,
        )
        return {
            "workflow_executed": False,
            "approval_request_id": approval_request_id,
            "success": False,
            "message": f"审批已通过，但恢复 AI 工作流失败：{exc}",
        }


sync_module_functions(
    target=globals(),
    source_module="app.application.approval_workspace_app_service",
    function_names=("_resume_pending_ai_workflow_after_approval",),
)
