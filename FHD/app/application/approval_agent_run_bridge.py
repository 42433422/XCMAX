from __future__ import annotations

import json
import logging
from typing import Any

from app.db.models.approval import ApprovalRequest
from app.db.session import get_db
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _compat_durable_ai_workflow_link(request_no: str | None) -> dict[str, str]:
    """Honor legacy monkeypatch/plugin overrides exposed by the owning service."""
    import sys

    owner = sys.modules.get("app.application.approval_workspace_app_service")
    resolver = getattr(owner, "_durable_ai_workflow_link", None) if owner else None
    if callable(resolver) and resolver is not _durable_ai_workflow_link:
        return resolver(request_no)
    return _durable_ai_workflow_link(request_no)


def _durable_ai_workflow_link(request_no: str | None) -> dict[str, str]:
    """Resolve the AgentRun link persisted inside an AI approval request."""

    approval_request_id = str(request_no or "").strip()
    if not approval_request_id:
        return {}
    try:
        with get_db() as db:
            req = (
                db.query(ApprovalRequest)
                .filter(ApprovalRequest.request_no == approval_request_id)
                .first()
            )
            raw = json.loads(str(getattr(req, "description", "") or "{}")) if req else {}
        if not isinstance(raw, dict):
            return {}
        return {
            "agent_run_id": str(raw.get("agent_run_id") or "").strip(),
            "agent_step_id": str(raw.get("agent_step_id") or "").strip(),
            "agent_node_id": str(raw.get("agent_node_id") or "").strip(),
        }
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "resolve durable AI workflow failed request_no=%s: %s",
            approval_request_id,
            exc,
        )
        return {}


def _has_pending_ai_workflow(request_no: str | None) -> bool:
    approval_request_id = str(request_no or "").strip()
    if not approval_request_id:
        return False
    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.workflow import get_approval_service

        if get_approval_service().get_pending_workflow(approval_request_id):
            return True
        link = _compat_durable_ai_workflow_link(approval_request_id)
        run_id = link.get("agent_run_id", "")
        run = AgentOrchestrator().get_run(run_id) if run_id else None
        return bool(run and run.status not in {"completed", "failed", "cancelled"})
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "check pending AI workflow failed request_no=%s: %s",
            approval_request_id,
            exc,
        )
        return False


def _resume_pending_ai_workflow_after_approval(
    *, request_no: str, opinion: str
) -> dict[str, Any] | None:
    """工作台审批通过后，继续执行由 AI 工作流创建的 pending workflow。"""
    approval_request_id = str(request_no or "").strip()
    if not approval_request_id:
        return None
    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.workflow import WorkflowEngine, get_approval_service
        from app.fastapi_routes.domains.misc.helpers import _dispatch_tool_for_approval

        approval_service = get_approval_service()
        approved_in_memory = approval_service.approve(approval_request_id, opinion)
        workflow_data = approval_service.get_pending_workflow(approval_request_id) or {}
        durable_link = _compat_durable_ai_workflow_link(approval_request_id)
        agent_run_id = str(
            workflow_data.get("agent_run_id") or durable_link.get("agent_run_id") or ""
        ).strip()
        if agent_run_id:
            approved_step_id = str(
                workflow_data.get("agent_step_id")
                or workflow_data.get("agent_node_id")
                or durable_link.get("agent_step_id")
                or durable_link.get("agent_node_id")
                or ""
            ).strip()
            agent_run = AgentOrchestrator().approve_run_step(
                agent_run_id,
                approved_by="approval_workspace",
                approved_step_id=approved_step_id,
                approval_request_id=approval_request_id,
            )
            approval_service.remove_pending_workflow(approval_request_id)
            if agent_run is None:
                return {
                    "workflow_executed": False,
                    "approval_request_id": approval_request_id,
                    "approved_in_memory": approved_in_memory,
                    "success": False,
                    "message": "审批已通过，但关联的持久化任务不存在",
                }
            return {
                "workflow_executed": agent_run.status != "waiting_user",
                "approval_request_id": approval_request_id,
                "approved_in_memory": approved_in_memory,
                "success": agent_run.status not in {"failed", "cancelled"},
                "agent_run_id": agent_run.run_id,
                "agent_run_status": agent_run.status,
                "plan_id": agent_run.plan_id,
                "intent": agent_run.intent,
                "message": (
                    "审批已通过，持久化任务已继续执行"
                    if agent_run.status != "waiting_user"
                    else "当前节点已通过，任务正等待下一审批节点"
                ),
                "tool_calls": len(agent_run.tool_calls),
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


def _drop_pending_ai_workflow_after_rejection(
    *, request_no: str, reason: str
) -> dict[str, Any] | None:
    """工作台拒绝 AI workflow 审批后，清理内存 pending workflow。"""
    approval_request_id = str(request_no or "").strip()
    if not approval_request_id:
        return None
    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.workflow import get_approval_service

        approval_service = get_approval_service()
        workflow_data = approval_service.get_pending_workflow(approval_request_id) or {}
        durable_link = _compat_durable_ai_workflow_link(approval_request_id)
        agent_run_id = str(
            workflow_data.get("agent_run_id") or durable_link.get("agent_run_id") or ""
        ).strip()
        rejected_in_memory = approval_service.reject(approval_request_id, reason)
        removed = approval_service.remove_pending_workflow(approval_request_id)
        cancelled_run = (
            AgentOrchestrator().cancel_run(
                agent_run_id,
                cancelled_by="approval_workspace_rejection",
            )
            if agent_run_id
            else None
        )
        return {
            "workflow_executed": False,
            "approval_request_id": approval_request_id,
            "rejected_in_memory": rejected_in_memory,
            "discarded_pending_workflow": removed is not None,
            "agent_run_id": agent_run_id,
            "agent_run_status": getattr(cancelled_run, "status", ""),
            "message": "审批已拒绝，AI 工作流已取消",
        }
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "drop pending AI workflow after rejection failed request_no=%s: %s",
            approval_request_id,
            exc,
            exc_info=True,
        )
        return {
            "workflow_executed": False,
            "approval_request_id": approval_request_id,
            "success": False,
            "message": f"审批已拒绝，但清理 AI 工作流失败：{exc}",
        }
