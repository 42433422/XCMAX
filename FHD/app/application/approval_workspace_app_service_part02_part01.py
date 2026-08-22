# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.approval_workspace_app_service")


def approve_request(
    request_id: int,
    http_request: _facade().Request,
    body: dict = _facade().Body(default_factory=dict),
    x_user_id: str | None = _facade().Header(default=None, alias="X-User-ID"),
):
    actor = _facade()._resolve_actor(http_request, x_user_id)
    if actor is None:
        raise _facade().HTTPException(status_code=401, detail="请先登录")
    opinion = str(body.get("opinion") or "").strip() or "同意"
    approver_name = str(body.get("approver_name") or "").strip() or None
    with _facade().get_db() as db:
        req = (
            db.query(_facade().ApprovalRequest)
            .filter(_facade().ApprovalRequest.id == request_id)
            .first()
        )
        if not req:
            return _facade().JSONResponse(
                {"success": False, "message": "审批请求不存在"}, status_code=404
            )
        if req.status not in (
            _facade().ApprovalStatus.PENDING.value,
            _facade().ApprovalStatus.IN_PROGRESS.value,
        ):
            return _facade().JSONResponse(
                {"success": False, "message": f"当前状态不可审批：{req.status}"}, status_code=400
            )
        current_node = req.current_node
        if current_node is None:
            if _facade()._is_ai_workflow_request(req):
                return _facade()._approve_ai_workflow_request_without_node(
                    db, req=req, actor=actor, approver_name=approver_name, opinion=opinion
                )
            return _facade().JSONResponse(
                {"success": False, "message": "审批请求缺少当前节点"}, status_code=400
            )
        if not _facade()._node_query_for_user(current_node, actor):
            return _facade().JSONResponse(
                {"success": False, "message": "当前用户不在审批人列表中"}, status_code=403
            )
        status_before = req.status
        node_id_before = current_node.id
        record = _facade().ApprovalRecord(
            request_id=req.id,
            node_id=current_node.id,
            node_name=current_node.node_name,
            node_order=current_node.node_order,
            approver_id=actor,
            approver_name=approver_name,
            action=_facade().ApprovalAction.APPROVE.value,
            opinion=opinion,
            is_passed=True,
        )
        db.add(record)
        nodes = _facade()._ordered_nodes(db, req.flow_id)
        new_status, next_node_id = _facade()._close_request_if_needed(
            db, req=req, nodes=nodes, approver_id=actor, approver_name=approver_name
        )
        _facade()._audit(
            db,
            actor=actor,
            action="approval.approve",
            payload={
                "request_id": req.id,
                "request_no": req.request_no,
                "flow_id": req.flow_id,
                "node_id": node_id_before,
                "next_node_id": next_node_id,
                "status_before": status_before,
                "status_after": new_status,
                "opinion": opinion,
            },
        )
        workflow_execution = None
        if (
            new_status == _facade().ApprovalStatus.APPROVED.value
            and _facade()._is_ai_workflow_request(req)
        ):
            workflow_execution = _facade()._resume_pending_ai_workflow_after_approval(
                request_no=str(req.request_no or ""), opinion=opinion, approved_by=str(actor)
            )
            _execution_success = bool(
                workflow_execution
                and workflow_execution.get("workflow_executed")
                and workflow_execution.get("success")
            )
            safe_code, safe_message = _facade().canonical_workflow_outcome(
                success=_execution_success, code=str((workflow_execution or {}).get("code") or "")
            )
            if _execution_success:
                _facade()._persist_ai_workflow_outcome(
                    req,
                    status=_facade().ApprovalStatus.APPROVED.value,
                    success=True,
                    code=safe_code,
                    message=safe_message,
                    workflow_executed=True,
                    nodes_executed=_facade()._safe_workflow_node_count(
                        (workflow_execution or {}).get("nodes_executed")
                    ),
                    nodes_total=_facade()._safe_workflow_node_count(
                        (workflow_execution or {}).get("nodes_total")
                    ),
                )
            else:
                _facade()._persist_ai_workflow_outcome(
                    req,
                    status=_facade().ApprovalStatus.CANCELLED.value,
                    success=False,
                    code=safe_code,
                    message=safe_message,
                    workflow_executed=bool(
                        workflow_execution and workflow_execution.get("workflow_executed")
                    ),
                    nodes_executed=_facade()._safe_workflow_node_count(
                        (workflow_execution or {}).get("nodes_executed")
                    ),
                    nodes_total=_facade()._safe_workflow_node_count(
                        (workflow_execution or {}).get("nodes_total")
                    ),
                )
                req.status = _facade().ApprovalStatus.CANCELLED.value
                req.rejection_reason = safe_code
                _facade()._audit(
                    db,
                    actor=actor,
                    action="approval.execute_ai_workflow_failed",
                    payload={
                        "request_no": req.request_no,
                        "code": safe_code,
                        "message": safe_message,
                    },
                )
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
        if workflow_execution is not None and (
            not (workflow_execution.get("workflow_executed") and workflow_execution.get("success"))
        ):
            return {
                "success": False,
                "data": _facade()._request_to_dict(req, include_records=False),
                "workflow_execution": workflow_execution,
                "message": "审批未通过：AI 工作流未成功执行",
            }
        if req.applicant_id:
            _facade().notify_mobile_user(
                int(req.applicant_id),
                "审批进度更新",
                f"《{req.title or req.request_no}》已处理",
                {"route": f"/app/approval/{req.id}", "request_id": str(req.id)},
            )
        data = _facade()._request_to_dict(req, include_records=True)
        if workflow_execution is not None:
            data["workflow_execution"] = workflow_execution
        return {"success": True, "data": data}


def reject_request(
    request_id: int,
    http_request: _facade().Request,
    body: dict = _facade().Body(default_factory=dict),
    x_user_id: str | None = _facade().Header(default=None, alias="X-User-ID"),
):
    actor = _facade()._resolve_actor(http_request, x_user_id)
    if actor is None:
        raise _facade().HTTPException(status_code=401, detail="请先登录")
    reason = str(body.get("reason") or body.get("opinion") or "").strip()
    if not reason:
        raise _facade().HTTPException(status_code=400, detail="拒绝原因不能为空")
    approver_name = str(body.get("approver_name") or "").strip() or None
    with _facade().get_db() as db:
        req = (
            db.query(_facade().ApprovalRequest)
            .filter(_facade().ApprovalRequest.id == request_id)
            .first()
        )
        if not req:
            return _facade().JSONResponse(
                {"success": False, "message": "审批请求不存在"}, status_code=404
            )
        if req.status not in (
            _facade().ApprovalStatus.PENDING.value,
            _facade().ApprovalStatus.IN_PROGRESS.value,
        ):
            return _facade().JSONResponse(
                {"success": False, "message": f"当前状态不可拒绝：{req.status}"}, status_code=400
            )
        current_node = req.current_node
        if current_node is None:
            if _facade()._is_ai_workflow_request(req):
                if not _facade()._can_review_ai_workflow_request(db, req, actor):
                    return _facade().JSONResponse(
                        {"success": False, "message": "当前用户无权拒绝这条 AI 工作流"},
                        status_code=403,
                    )
                audit_node = _facade()._ai_workflow_audit_node(db, req)
                if audit_node is None:
                    return _facade().JSONResponse(
                        {"success": False, "message": "AI 审批流程缺少合法留痕节点"},
                        status_code=409,
                    )
                status_before = req.status
                req.status = _facade().ApprovalStatus.REJECTED.value
                req.rejected_at = _facade().datetime.now()
                req.rejection_reason = reason
                req.approved_by = actor
                req.approved_by_name = approver_name
                db.add(
                    _facade().ApprovalRecord(
                        request_id=req.id,
                        node_id=audit_node.id,
                        node_name=audit_node.node_name,
                        node_order=audit_node.node_order,
                        approver_id=actor,
                        approver_name=approver_name,
                        action=_facade().ApprovalAction.REJECT.value,
                        opinion=reason,
                        reject_reason=reason,
                        is_passed=False,
                    )
                )
                _facade()._audit(
                    db,
                    actor=actor,
                    action="approval.reject_ai_workflow",
                    payload={
                        "request_id": req.id,
                        "request_no": req.request_no,
                        "status_before": status_before,
                        "status_after": req.status,
                        "reason": reason,
                    },
                )
                db.commit()
                db.refresh(req)
                workflow_execution = _facade()._drop_pending_ai_workflow_after_rejection(
                    request_no=str(req.request_no or ""), reason=reason
                )
                if workflow_execution and workflow_execution.get("agent_run_id"):
                    from app.application.business_harness_projection import (
                        project_terminal_run_to_conversation,
                    )

                    project_terminal_run_to_conversation(
                        str(workflow_execution.get("agent_run_id") or ""),
                        approval_request_id=str(req.request_no or ""),
                    )
                if req.applicant_id:
                    _facade().notify_mobile_user(
                        int(req.applicant_id),
                        "审批进度更新",
                        f"《{req.title or req.request_no}》已驳回",
                        {"route": f"/app/approval/{req.id}", "request_id": str(req.id)},
                    )
                data = _facade()._request_to_dict(req, include_records=True)
                if workflow_execution is not None:
                    data["workflow_execution"] = workflow_execution
                return {"success": True, "data": data}
            return _facade().JSONResponse(
                {"success": False, "message": "审批请求缺少当前节点"}, status_code=400
            )
        if not _facade()._node_query_for_user(current_node, actor):
            return _facade().JSONResponse(
                {"success": False, "message": "当前用户不在审批人列表中"}, status_code=403
            )
        status_before = req.status
        node_id_before = current_node.id
        record = _facade().ApprovalRecord(
            request_id=req.id,
            node_id=current_node.id,
            node_name=current_node.node_name,
            node_order=current_node.node_order,
            approver_id=actor,
            approver_name=approver_name,
            action=_facade().ApprovalAction.REJECT.value,
            opinion=reason,
            reject_reason=reason,
            is_passed=False,
        )
        db.add(record)
        req.status = _facade().ApprovalStatus.REJECTED.value
        req.rejected_at = _facade().datetime.now()
        req.rejection_reason = reason
        _facade()._audit(
            db,
            actor=actor,
            action="approval.reject",
            payload={
                "request_id": req.id,
                "request_no": req.request_no,
                "flow_id": req.flow_id,
                "node_id": node_id_before,
                "status_before": status_before,
                "status_after": req.status,
                "reason": reason,
            },
        )
        db.commit()
        db.refresh(req)
        if req.applicant_id:
            _facade().notify_mobile_user(
                int(req.applicant_id),
                "审批进度更新",
                f"《{req.title or req.request_no}》已驳回",
                {"route": f"/app/approval/{req.id}", "request_id": str(req.id)},
            )
        return {"success": True, "data": _facade()._request_to_dict(req, include_records=True)}
