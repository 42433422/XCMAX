"""Authorized approval decisions and their transaction boundaries."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.application.workflow.approval_persistence import (
    SETUP_GUIDANCE_CODES,
    WORKFLOW_EXECUTION_FAILED_CODE,
)
from app.db.models.approval import (
    ApprovalAction,
    ApprovalFlowNode,
    ApprovalRecord,
    ApprovalRequest,
    ApprovalStatus,
)

from .outcomes import execution_outcome, persist_outcome
from .ports import (
    ApprovalAccess,
    ApprovalNodes,
    ApproveWithoutNode,
    DecisionEffects,
    JsonObject,
    RequestView,
    WorkflowActions,
    WorkspaceResponse,
)
from .repository import ApprovalRepository


class ApprovalDecisions:
    def __init__(
        self,
        repository: ApprovalRepository,
        access: ApprovalAccess,
        nodes: ApprovalNodes,
        workflows: WorkflowActions,
        effects: DecisionEffects,
        view: RequestView,
        approve_without_node: ApproveWithoutNode,
    ) -> None:
        self.repository = repository
        self.access = access
        self.nodes = nodes
        self.workflows = workflows
        self.effects = effects
        self.view = view
        self.approve_without_node = approve_without_node

    def project_workflow(self, execution: JsonObject | None, req: ApprovalRequest) -> None:
        if execution and execution.get("agent_run_id"):
            self.effects.project(str(execution["agent_run_id"]), str(req.request_no or ""))

    def approve_request(
        self, request_id: int, http_request: Request, body: JsonObject, x_user_id: str | None
    ) -> WorkspaceResponse:
        actor = self.access.actor(http_request, x_user_id)
        if actor is None:
            raise HTTPException(status_code=401, detail="请先登录")
        opinion = str(body.get("opinion") or "").strip() or "同意"
        approver_name = str(body.get("approver_name") or "").strip() or None
        with self.repository.session() as db:
            req = self.repository.request(db, request_id)
            if not req:
                return JSONResponse(
                    {"success": False, "message": "审批请求不存在"}, status_code=404
                )
            if req.status not in (ApprovalStatus.PENDING.value, ApprovalStatus.IN_PROGRESS.value):
                return JSONResponse(
                    {"success": False, "message": f"当前状态不可审批：{req.status}"},
                    status_code=400,
                )
            current_node = req.current_node
            if current_node is None:
                if self.access.is_workflow(req):
                    return self.approve_without_node(
                        db, req=req, actor=actor, approver_name=approver_name, opinion=opinion
                    )
                return JSONResponse(
                    {"success": False, "message": "审批请求缺少当前节点"}, status_code=400
                )
            if not self.access.node_reviewer(current_node, actor):
                return JSONResponse(
                    {"success": False, "message": "当前用户不在审批人列表中"}, status_code=403
                )
            status_before = req.status
            node_id_before = current_node.id
            nodes = self.nodes.ordered(db, req.flow_id)
            try:
                business = json.loads(req.business_data or "{}")
            except (ValueError, TypeError):
                business = {}
            restore_execution = None
            final_restore = (
                self.access.is_workflow(req)
                and isinstance(business, dict)
                and (
                    (business.get("tool_id"), business.get("action"))
                    == ("system_maintenance", "restore_database")
                )
                and (self.nodes.next_node(nodes, req.current_node_order or 0) is None)
            )
            if final_restore:
                # Restore before any destination write; then reattach the request and history.
                list(req.records)
                restore_execution = self.workflows.resume(
                    request_no=str(req.request_no or ""), opinion=opinion, approved_by=str(actor)
                )
                if execution_outcome(restore_execution)["success"]:
                    db.expunge_all()
                    req = db.merge(req)
            record = ApprovalRecord(
                request_id=req.id,
                node_id=current_node.id,
                node_name=current_node.node_name,
                node_order=current_node.node_order,
                approver_id=actor,
                approver_name=approver_name,
                action=ApprovalAction.APPROVE.value,
                opinion=opinion,
                is_passed=True,
            )
            db.add(record)
            new_status, next_node_id = self.nodes.advance(
                db, req=req, nodes=nodes, approver_id=actor, approver_name=approver_name
            )
            self.effects.audit(
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
            final_workflow = (
                new_status == ApprovalStatus.APPROVED.value and self.access.is_workflow(req)
            )
            outcome = execution_outcome(None)
            if final_workflow:
                workflow_execution = restore_execution
                if not final_restore:
                    workflow_execution = self.workflows.resume(
                        request_no=str(req.request_no or ""),
                        opinion=opinion,
                        approved_by=str(actor),
                    )
                outcome = execution_outcome(workflow_execution)
                persist_outcome(req, **outcome)
                if not outcome["success"]:
                    req.status = ApprovalStatus.CANCELLED.value
                    req.rejection_reason = outcome["code"]
                    self.effects.audit(
                        db,
                        actor=actor,
                        action="approval.execute_ai_workflow_failed",
                        payload={
                            "request_no": req.request_no,
                            "code": outcome["code"],
                            "message": outcome["message"],
                        },
                    )
            db.commit()
            db.refresh(req)
            self.project_workflow(workflow_execution, req)
            if final_workflow and not outcome["success"]:
                return {
                    "success": False,
                    "data": self.view(req, include_records=False),
                    "workflow_execution": workflow_execution,
                    "message": "审批未通过：AI 工作流未成功执行",
                }
            if req.applicant_id:
                self.effects.notify(
                    int(req.applicant_id),
                    "审批进度更新",
                    f"《{req.title or req.request_no}》已处理",
                    {"route": f"/app/approval/{req.id}", "request_id": str(req.id)},
                )
            data = self.view(req, include_records=True)
            if workflow_execution is not None:
                data["workflow_execution"] = workflow_execution
            return {"success": True, "data": data}

    def reject_request(
        self, request_id: int, http_request: Request, body: JsonObject, x_user_id: str | None
    ) -> WorkspaceResponse:
        actor = self.access.actor(http_request, x_user_id)
        if actor is None:
            raise HTTPException(status_code=401, detail="请先登录")
        reason = str(body.get("reason") or body.get("opinion") or "").strip()
        if not reason:
            raise HTTPException(status_code=400, detail="拒绝原因不能为空")
        approver_name = str(body.get("approver_name") or "").strip() or None
        with self.repository.session() as db:
            req = self.repository.request(db, request_id)
            if not req:
                return JSONResponse(
                    {"success": False, "message": "审批请求不存在"}, status_code=404
                )
            if req.status not in (ApprovalStatus.PENDING.value, ApprovalStatus.IN_PROGRESS.value):
                return JSONResponse(
                    {"success": False, "message": f"当前状态不可拒绝：{req.status}"},
                    status_code=400,
                )
            node = req.current_node
            workflow_without_node = node is None and self.access.is_workflow(req)
            if node is None:
                if not workflow_without_node:
                    return JSONResponse(
                        {"success": False, "message": "审批请求缺少当前节点"}, status_code=400
                    )
                if not self.access.workflow_reviewer(db, req, actor):
                    return JSONResponse(
                        {"success": False, "message": "当前用户无权拒绝这条 AI 工作流"},
                        status_code=403,
                    )
                node = self.nodes.audit_node(db, req)
                if node is None:
                    return JSONResponse(
                        {"success": False, "message": "AI 审批流程缺少合法留痕节点"},
                        status_code=409,
                    )
            elif not self.access.node_reviewer(node, actor):
                return JSONResponse(
                    {"success": False, "message": "当前用户不在审批人列表中"}, status_code=403
                )
            status_before = req.status
            db.add(
                ApprovalRecord(
                    request_id=req.id,
                    node_id=node.id,
                    node_name=node.node_name,
                    node_order=node.node_order,
                    approver_id=actor,
                    approver_name=approver_name,
                    action=ApprovalAction.REJECT.value,
                    opinion=reason,
                    reject_reason=reason,
                    is_passed=False,
                )
            )
            req.status = ApprovalStatus.REJECTED.value
            req.rejected_at = datetime.now()
            req.rejection_reason = reason
            payload: JsonObject = {
                "request_id": req.id,
                "request_no": req.request_no,
                "status_before": status_before,
                "status_after": req.status,
                "reason": reason,
            }
            if workflow_without_node:
                req.approved_by = actor
                req.approved_by_name = approver_name
            else:
                payload.update(flow_id=req.flow_id, node_id=node.id)
            self.effects.audit(
                db,
                actor=actor,
                action="approval.reject_ai_workflow"
                if workflow_without_node
                else "approval.reject",
                payload=payload,
            )
            # Reject expired workflows too. Runtime cleanup follows the durable rejection.
            db.commit()
            db.refresh(req)
            workflow_execution = None
            if workflow_without_node:
                workflow_execution = self.workflows.reject(
                    request_no=str(req.request_no or ""), reason=reason
                )
                self.project_workflow(workflow_execution, req)
            if req.applicant_id:
                self.effects.notify(
                    int(req.applicant_id),
                    "审批进度更新",
                    f"《{req.title or req.request_no}》已驳回",
                    {"route": f"/app/approval/{req.id}", "request_id": str(req.id)},
                )
            data = self.view(req, include_records=True)
            if workflow_execution is not None:
                data["workflow_execution"] = workflow_execution
            return {"success": True, "data": data}

    def approve_workflow(
        self,
        db: Session,
        *,
        req: ApprovalRequest,
        actor: int,
        approver_name: str | None,
        opinion: str,
    ) -> WorkspaceResponse:
        """审批由 AI workflow 持久化、没有传统审批节点的请求。"""
        if not self.access.workflow_reviewer(db, req, actor):
            return JSONResponse(
                {"success": False, "message": "当前用户无权审批这条 AI 工作流"}, status_code=403
            )
        if not self.workflows.pending(req.request_no):
            return JSONResponse(
                {"success": False, "message": "AI 工作流运行态不存在或已过期，请重新发起任务"},
                status_code=409,
            )
        audit_node = self.nodes.audit_node(db, req)
        if audit_node is None:
            return JSONResponse(
                {"success": False, "message": "AI 审批流程缺少合法留痕节点"}, status_code=409
            )
        try:
            business = json.loads(req.business_data) if isinstance(req.business_data, str) else {}
        except (ValueError, TypeError):
            business = {}
        restore_approval = isinstance(business, dict) and (
            business.get("tool_id"),
            business.get("action"),
        ) == ("system_maintenance", "restore_database")
        workflow_execution = self.workflows.resume(
            request_no=str(req.request_no or ""), opinion=opinion, approved_by=str(actor)
        )
        bounded_outcome = execution_outcome(workflow_execution)
        _execution_success = bounded_outcome["success"]
        if _execution_success and restore_approval:
            # The restored database may predate this request; merge its identity after restore.
            db.expunge(req)
            req = db.merge(req)
        status_before = req.status
        safe_code, safe_message = bounded_outcome["code"], bounded_outcome["message"]
        persist_outcome(req, **bounded_outcome)
        req.status = bounded_outcome["status"]
        if _execution_success:
            req.approved_at = datetime.now()
            req.approved_by = actor
            req.approved_by_name = approver_name
            req.current_node_id = None
            req.current_node_order = (req.current_node_order or 0) + 1
            db.add(
                ApprovalRecord(
                    request_id=req.id,
                    node_id=audit_node.id,
                    node_name=audit_node.node_name,
                    node_order=audit_node.node_order,
                    approver_id=actor,
                    approver_name=approver_name,
                    action=ApprovalAction.APPROVE.value,
                    opinion=opinion,
                    is_passed=True,
                )
            )
            self.effects.audit(
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
        self.effects.audit(
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
            req.rejection_reason = WORKFLOW_EXECUTION_FAILED_CODE
            self.effects.audit(
                db,
                actor=actor,
                action="approval.execute_ai_workflow_failed",
                payload={
                    "request_no": req.request_no,
                    "code": safe_code,
                    "message": bounded_outcome["message"],
                },
            )
        notification = self.effects.completed_notification(req) if req.applicant_id else None
        db.commit()
        db.refresh(req)
        self.project_workflow(workflow_execution, req)
        if _execution_success and notification is not None:
            self.effects.notify(*notification)
        data = self.view(req, include_records=True)
        data["workflow_execution"] = bounded_outcome
        if not _execution_success:
            failure_message = "审批通过后 AI 工作流执行失败，审批已取消"
            if safe_code in SETUP_GUIDANCE_CODES:
                failure_message = f"{failure_message}：{safe_message}"
            return JSONResponse(
                {"success": False, "data": data, "message": failure_message}, status_code=409
            )
        return {"success": True, "data": data}


def advance_request(
    db: Session,
    *,
    req: ApprovalRequest,
    nodes: list[ApprovalFlowNode],
    approver_id: int,
    approver_name: str | None,
    next_node: Callable[[list[ApprovalFlowNode], int], ApprovalFlowNode | None],
) -> tuple[str, int | None]:
    """串行流程：推进到下一节点；若已到末节点则置为 ``approved``。"""
    successor = next_node(nodes, req.current_node_order or 0)
    if successor is None:
        req.status = ApprovalStatus.APPROVED.value
        req.approved_at = datetime.now()
        req.approved_by = approver_id
        req.approved_by_name = approver_name
        req.current_node_id = None
        req.current_node_order = (req.current_node_order or 0) + 1
        return (ApprovalStatus.APPROVED.value, None)
    req.status = ApprovalStatus.IN_PROGRESS.value
    req.current_node_id = successor.id
    req.current_node_order = successor.node_order
    return (ApprovalStatus.IN_PROGRESS.value, successor.id)
