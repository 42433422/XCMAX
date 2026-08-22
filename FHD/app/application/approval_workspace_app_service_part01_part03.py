# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.approval_workspace_app_service")


def _approve_ai_workflow_request_without_node(
    db, *, req: _facade().ApprovalRequest, actor: int, approver_name: str | None, opinion: str
) -> dict[str, _facade().Any] | _facade().JSONResponse:
    """审批由 AI workflow 持久化、没有传统审批节点的请求。"""
    if not _facade()._can_review_ai_workflow_request(db, req, actor):
        return _facade().JSONResponse(
            {"success": False, "message": "当前用户无权审批这条 AI 工作流"}, status_code=403
        )
    if not _facade()._has_pending_ai_workflow(req.request_no):
        return _facade().JSONResponse(
            {"success": False, "message": "AI 工作流运行态不存在或已过期，请重新发起任务"},
            status_code=409,
        )
    audit_node = _facade()._ai_workflow_audit_node(db, req)
    if audit_node is None:
        return _facade().JSONResponse(
            {"success": False, "message": "AI 审批流程缺少合法留痕节点"}, status_code=409
        )
    workflow_execution = _facade()._resume_pending_ai_workflow_after_approval(
        request_no=str(req.request_no or ""), opinion=opinion, approved_by=str(actor)
    )
    _execution_success = bool(workflow_execution and workflow_execution.get("success"))
    status_before = req.status
    terminal_status = (
        _facade().ApprovalStatus.APPROVED.value
        if _execution_success
        else _facade().ApprovalStatus.CANCELLED.value
    )
    (safe_code, safe_message) = _facade().canonical_workflow_outcome(
        success=_execution_success, code=str((workflow_execution or {}).get("code") or "")
    )
    nodes_executed_count = _facade()._safe_workflow_node_count(
        (workflow_execution or {}).get("nodes_executed")
    )
    nodes_total_count = _facade()._safe_workflow_node_count(
        (workflow_execution or {}).get("nodes_total")
    )
    bounded_outcome = {
        "status": terminal_status,
        "success": _execution_success,
        "code": safe_code,
        "message": safe_message,
        "workflow_executed": bool(
            workflow_execution and workflow_execution.get("workflow_executed")
        ),
        "nodes_executed": nodes_executed_count,
        "nodes_total": nodes_total_count,
    }
    _facade()._persist_ai_workflow_outcome(
        req,
        status=terminal_status,
        success=_execution_success,
        code=safe_code,
        message=safe_message,
        workflow_executed=bool(workflow_execution and workflow_execution.get("workflow_executed")),
        nodes_executed=nodes_executed_count,
        nodes_total=nodes_total_count,
    )
    req.status = terminal_status
    if _execution_success:
        req.approved_at = _facade().datetime.now()
        req.approved_by = actor
        req.approved_by_name = approver_name
        req.current_node_id = None
        req.current_node_order = (req.current_node_order or 0) + 1
        db.add(
            _facade().ApprovalRecord(
                request_id=req.id,
                node_id=audit_node.id,
                node_name=audit_node.node_name,
                node_order=audit_node.node_order,
                approver_id=actor,
                approver_name=approver_name,
                action=_facade().ApprovalAction.APPROVE.value,
                opinion=opinion,
                is_passed=True,
            )
        )
        _facade()._audit(
            db,
            actor=actor,
            action="approval.approve_ai_workflow",
            payload={
                "request_id": req.id,
                "request_no": req.request_no,
                "status_before": status_before,
                "status_after": req.status,
                "opinion": opinion,
            },
        )
    _facade()._audit(
        db,
        actor=actor,
        action="approval.execute_ai_workflow",
        payload={
            "request_id": req.id,
            "request_no": req.request_no,
            "workflow_execution_status": bounded_outcome["status"],
            "workflow_execution_success": _execution_success,
            "workflow_execution_code": safe_code,
            "workflow_execution_message": bounded_outcome["message"],
        },
    )
    if not _execution_success:
        req.rejection_reason = _facade().WORKFLOW_EXECUTION_FAILED_CODE
        _facade()._audit(
            db,
            actor=actor,
            action="approval.execute_ai_workflow_failed",
            payload={
                "request_no": req.request_no,
                "code": safe_code,
                "message": bounded_outcome["message"],
            },
        )
    notification = _facade().completed_workflow_notification(req) if req.applicant_id else None
    db.commit()
    db.refresh(req)
    if workflow_execution and workflow_execution.get("agent_run_id"):
        from app.application.business_harness_projection import (
            project_terminal_run_to_conversation,
        )

        project_terminal_run_to_conversation(
            str(workflow_execution.get("agent_run_id") or ""),
            approval_request_id=str(req.request_no or ""),
        )
    if _execution_success and notification is not None:
        _facade().notify_mobile_user(*notification)
    data = _facade()._request_to_dict(req, include_records=True)
    data["workflow_execution"] = bounded_outcome
    if not _execution_success:
        return _facade().JSONResponse(
            {"success": False, "data": data, "message": "审批通过后 AI 工作流执行失败，审批已取消"},
            status_code=409,
        )
    return {"success": True, "data": data}
