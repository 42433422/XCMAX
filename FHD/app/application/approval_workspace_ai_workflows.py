"""Durable AgentRun bridges used by the Approval Workspace."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.db.models.approval import ApprovalRequest
from app.db.session import get_db
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def durable_ai_workflow_link(request_no: str | None) -> dict[str, str]:
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


def has_pending_ai_workflow(request_no: str | None) -> bool:
    approval_request_id = str(request_no or "").strip()
    if not approval_request_id:
        return False
    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.workflow import get_approval_service

        if get_approval_service().get_pending_workflow(approval_request_id):
            return True
        link = durable_ai_workflow_link(approval_request_id)
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


def drop_pending_ai_workflow_after_rejection(
    *, request_no: str, reason: str
) -> dict[str, Any] | None:
    """Drop memory state and cancel the linked durable run after rejection."""

    approval_request_id = str(request_no or "").strip()
    if not approval_request_id:
        return None
    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.workflow import get_approval_service

        approval_service = get_approval_service()
        workflow_data = approval_service.get_pending_workflow(approval_request_id) or {}
        durable_link = durable_ai_workflow_link(approval_request_id)
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
