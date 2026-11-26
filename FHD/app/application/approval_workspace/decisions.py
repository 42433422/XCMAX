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
from app.db.models.user import User

from .access import supported_approval_flow, unsupported_approval_policy
from .outcomes import execution_handed_off, execution_outcome, persist_outcome
from .protocols import (
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


def _active_decision_actor(db: Session, req: ApprovalRequest, actor: int) -> bool:
    """An old reviewer list cannot reauthorize a deactivated or moved user."""
    # PostgreSQL holds the reviewer row until this decision commits.
    # A concurrent revocation/tenant move must serialize before or after the
    # approval, rather than slip between the permission read and the CAS.
    user = (
        db.query(User)
        .filter(User.id == actor, User.is_active.is_(True))
        .with_for_update(read=True)
        .first()
    )
    return user is not None and (
        req.tenant_id is None or user.tenant_id == req.tenant_id
    )


def _claim_open_step(db: Session, req: ApprovalRequest, target: str) -> bool:
    """CAS status and current node to fence a stale reviewer or duplicated decision."""
    return db.query(ApprovalRequest).filter(
        ApprovalRequest.id == req.id,
        ApprovalRequest.tenant_id == req.tenant_id,
        ApprovalRequest.status == req.status,
        ApprovalRequest.current_node_id == req.current_node_id,
        ApprovalRequest.current_node_order == req.current_node_order,
    ).update(
        {ApprovalRequest.status: target},
        synchronize_session=False,
    ) == 1


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
        self,
        request_id: int,
        http_request: Request,
        body: JsonObject,
        x_user_id: str | None,
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
            if req.status not in (
                ApprovalStatus.PENDING.value,
                ApprovalStatus.IN_PROGRESS.value,
            ):
                return JSONResponse(
                    {"success": False, "message": f"当前状态不可审批：{req.status}"},
                    status_code=400,
                )
            if not _active_decision_actor(db, req, actor):
                return JSONResponse(
                    {"success": False, "message": "审批人已停用或企业归属发生变更"},
                    status_code=403,
                )
            current_node = req.current_node
            if current_node is None:
                if self.access.is_workflow(req):
                    return self.approve_without_node(
                        db,
                        req=req,
                        actor=actor,
                        approver_name=approver_name,
                        opinion=opinion,
                    )
                return JSONResponse(
                    {"success": False, "message": "审批请求缺少当前节点"},
                    status_code=400,
                )
            if not self.access.node_reviewer(current_node, actor):
                return JSONResponse(
                    {"success": False, "message": "当前用户不在审批人列表中"},
                    status_code=403,
                )
            status_before = req.status
            node_id_before = current_node.id
            nodes = self.nodes.ordered(db, req.flow_id)
            if not supported_approval_flow(req.flow, [current_node, *nodes]):
                return unsupported_approval_policy()
            try:
                business = json.loads(req.business_data or "{}")
            except (ValueError, TypeError):
                business = {}
            final_workflow = self.access.is_workflow(req) and (
                self.nodes.next_node(nodes, req.current_node_order or 0) is None
            )
            workflow_execution = None
            if not final_workflow and not _claim_open_step(db, req, status_before):
                db.rollback()
                return JSONResponse(
                    {"success": False, "message": "审批节点已由其他请求处理或状态变更，请刷新"},
                    status_code=409,
                )
            final_restore = (
                final_workflow
                and isinstance(business, dict)
                and (
                    (business.get("tool_id"), business.get("action"))
                    == ("system_maintenance", "restore_database")
                )
            )
            if final_workflow:
                # Claim before any outer write: SQLite cannot grant the inner
                # approval CAS while this session holds an audit/decision lock.
                if final_restore:
                    list(req.records)
                workflow_execution = self.workflows.resume(
                    request_no=str(req.request_no or ""),
                    opinion=opinion,
                    approved_by=str(actor),
                )
                if (workflow_execution or {}).get("approval_claim_conflict"):
                    db.rollback()
                    return JSONResponse(
                        {
                            "success": False,
                            "message": "该审批正在处理或结果待核对，请刷新任务状态。",
                        },
                        status_code=409,
                    )
                if final_restore and execution_outcome(workflow_execution)["success"]:
                    # Restore may replace the destination database entirely.
                    db.expunge_all()
                    req = db.merge(req)
                elif not final_restore:
                    db.refresh(req, attribute_names=["business_data"])
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
            outcome = execution_outcome(None)
            if final_workflow:
                outcome = execution_outcome(workflow_execution)
                handed_off = execution_handed_off(workflow_execution)
                persist_outcome(req, **outcome)
                if (
                    not handed_off
                    and not outcome["success"]
                    and outcome["code"] != "outcome_unknown"
                ):
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
            if final_workflow and (handed_off or outcome["code"] == "outcome_unknown"):
                handoff_message = outcome["message"]
                data = self.view(req, include_records=False)
                data["workflow_execution"] = workflow_execution
                return JSONResponse(
                    {
                        "success": False,
                        "accepted": True,
                        "data": data,
                        "message": handoff_message,
                    },
                    status_code=202,
                )
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
        self,
        request_id: int,
        http_request: Request,
        body: JsonObject,
        x_user_id: str | None,
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
            if req.status not in (
                ApprovalStatus.PENDING.value,
                ApprovalStatus.IN_PROGRESS.value,
            ):
                return JSONResponse(
                    {"success": False, "message": f"当前状态不可拒绝：{req.status}"},
                    status_code=400,
                )
            if not _active_decision_actor(db, req, actor):
                return JSONResponse(
                    {"success": False, "message": "审批人已停用或企业归属发生变更"},
                    status_code=403,
                )
            node = req.current_node
            workflow_without_node = node is None and self.access.is_workflow(req)
            if node is None:
                if not workflow_without_node:
                    return JSONResponse(
                        {"success": False, "message": "审批请求缺少当前节点"},
                        status_code=400,
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
                    {"success": False, "message": "当前用户不在审批人列表中"},
                    status_code=403,
                )
            status_before = req.status
            if self.access.is_workflow(req):
                try:
                    business = json.loads(req.business_data or "{}")
                except (ValueError, TypeError):
                    business = {}
                (
                    business.get("durable_workflow_snapshot")
                    if isinstance(business, dict)
                    else None
                )
                conflict = isinstance(business, dict) and "agent_execution_claim" in business
                if not conflict:
                    # One durable claim for ordinary and AI requests; the latter
                    # also binds its persisted execution snapshot.
                    query = db.query(ApprovalRequest).filter(
                        ApprovalRequest.id == req.id,
                        ApprovalRequest.tenant_id == req.tenant_id,
                        ApprovalRequest.status == status_before,
                        ApprovalRequest.current_node_id == req.current_node_id,
                        ApprovalRequest.current_node_order == req.current_node_order,
                        ApprovalRequest.business_data == req.business_data,
                    )
                    conflict = query.update(
                        {ApprovalRequest.status: ApprovalStatus.REJECTED.value},
                        synchronize_session=False,
                    ) != 1
                if conflict:
                    db.rollback()
                    return JSONResponse(
                        {"success": False, "message": "该审批已被领取或状态已变更，请核对原任务。"},
                        status_code=409,
                    )
            if not self.access.is_workflow(req) and not _claim_open_step(
                db, req, ApprovalStatus.REJECTED.value
            ):
                db.rollback()
                return JSONResponse(
                    {"success": False, "message": "审批已被其他请求处理或状态变更，请刷新"},
                    status_code=409,
                )
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
                action=(
                    "approval.reject_ai_workflow" if workflow_without_node else "approval.reject"
                ),
                payload=payload,
            )
            # Reject expired workflows too. Runtime cleanup follows the durable rejection.
            db.commit()
            db.refresh(req)
            workflow_execution = None
            if self.access.is_workflow(req):
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

    def _expire_stale_workflow(
        self,
        db: Session,
        *,
        req: ApprovalRequest,
        actor: int,
        approver_name: str | None,
        opinion: str,
    ) -> WorkspaceResponse:
        """运行态已丢失（通常是应用重启）：收敛挂起单，避免每次点击都返回 409。"""
        message = (
            "该审批已失效：AI 工作流运行态已过期（通常由应用重启导致），"
            "已自动关闭，请重新发起任务。"
        )
        audit_node = self.nodes.audit_node(db, req)
        if audit_node is not None:
            db.add(
                ApprovalRecord(
                    request_id=req.id,
                    node_id=audit_node.id,
                    node_name=audit_node.node_name,
                    node_order=audit_node.node_order,
                    approver_id=actor,
                    approver_name=approver_name,
                    action=ApprovalAction.CANCEL.value,
                    opinion=opinion or "AI 工作流运行态已过期",
                    is_passed=False,
                )
            )
        req.status = ApprovalStatus.CANCELLED.value
        req.rejection_reason = "workflow_runtime_expired"
        self.effects.audit(
            db,
            actor=actor,
            action="approval.ai_workflow_runtime_expired",
            payload={
                "request_id": req.id,
                "request_no": req.request_no,
                "reason": "workflow_runtime_expired",
            },
        )
        db.commit()
        db.refresh(req)
        if req.applicant_id:
            self.effects.notify(
                int(req.applicant_id),
                "审批已失效",
                f"《{req.title or req.request_no}》已自动关闭：{message}",
                {"route": f"/app/approval/{req.id}", "request_id": str(req.id)},
            )
        return JSONResponse(
            {
                "success": False,
                "expired": True,
                "data": self.view(req, include_records=False),
                "message": message,
            },
            status_code=409,
        )

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
                {"success": False, "message": "当前用户无权审批这条 AI 工作流"},
                status_code=403,
            )
        if not supported_approval_flow(req.flow, self.nodes.ordered(db, req.flow_id)):
            return unsupported_approval_policy()
        pending = self.workflows.pending(req.request_no)
        if pending is None:
            return JSONResponse(
                {
                    "success": False,
                    "retryable": True,
                    "message": "暂时无法核实工作流状态，请稍后重试",
                },
                status_code=503,
            )
        if not pending:
            return self._expire_stale_workflow(
                db, req=req, actor=actor, approver_name=approver_name, opinion=opinion
            )
        audit_node = self.nodes.audit_node(db, req)
        if audit_node is None:
            return JSONResponse(
                {"success": False, "message": "AI 审批流程缺少合法留痕节点"},
                status_code=409,
            )
        try:
            business = json.loads(req.business_data) if isinstance(req.business_data, str) else {}
        except (ValueError, TypeError):
            business = {}
        restore_approval = isinstance(business, dict) and (
            business.get("tool_id"),
            business.get("action"),
        ) == ("system_maintenance", "restore_database")
        request_no = str(req.request_no or "")
        from app.application.workflow.approval_persistence import (
            load_durable_workflow_snapshot,
            mark_durable_request_approved_and_load,
        )

        snapshot = load_durable_workflow_snapshot(request_no, allow_terminal=False)
        uses_agent_claim = bool(
            snapshot
            and snapshot.get("agent_run_id")
            and isinstance(business, dict)
            and snapshot.get("runtime_context", {}).get("_approval_agent_run_required") is True
            and snapshot.get("runtime_context", {}).get("cross_module_http") is not True
            and not restore_approval
            and (business.get("tool_id"), business.get("action"))
            not in {
                ("customers", "batch_delete"),
                ("products", "batch_delete"),
                ("data_docking", "auto_ingest"),
            }
        )
        # Agent continuation first commits its exact execution claim. A separate
        # approved state here would strand an unclaimed run after process exit.
        if snapshot is not None and not uses_agent_claim:
            if mark_durable_request_approved_and_load(request_no) is None:
                return JSONResponse(
                    {"success": False, "message": "审批决定未能先于执行落库"},
                    status_code=409,
                )
            db.refresh(req)
        workflow_execution = self.workflows.resume(
            request_no=str(req.request_no or ""),
            opinion=opinion,
            approved_by=str(actor),
        )
        if (workflow_execution or {}).get("approval_claim_conflict"):
            db.rollback()
            return JSONResponse(
                {
                    "success": False,
                    "message": "该审批正在处理或结果待核对，请刷新任务状态。",
                },
                status_code=409,
            )
        if uses_agent_claim or (
            isinstance(business, dict)
            and (business.get("tool_id"), business.get("action"))
            in {
                ("customers", "batch_delete"),
                ("products", "batch_delete"),
                ("data_docking", "auto_ingest"),
            }
        ):
            # Preserve the committed claim and its decision actor in the final
            # outcome, instead of overwriting them with this session's old JSON.
            db.refresh(req)
        bounded_outcome = execution_outcome(workflow_execution)
        _execution_success = bounded_outcome["success"]
        handed_off = execution_handed_off(workflow_execution)
        if _execution_success and restore_approval:
            # The restored database may predate this request; merge its identity after restore.
            db.expunge(req)
            req = db.merge(req)
        include_waiting_decision = False
        status_before = req.status
        safe_code, safe_message = bounded_outcome["code"], bounded_outcome["message"]
        # 工具超时但结果未知：审批放行有效，不能报「执行失败、审批已取消」。
        uncertain = safe_code == "outcome_unknown" and not _execution_success
        if handed_off:
            handoff_message = bounded_outcome["message"]
            persist_outcome(req, **bounded_outcome)
            req.status = ApprovalStatus.APPROVED.value
            safe_code, safe_message = bounded_outcome["code"], handoff_message
            include_waiting_decision = bool((workflow_execution or {}).get("waiting_user_decision"))
        else:
            persist_outcome(req, **bounded_outcome)
            req.status = bounded_outcome["status"]
        if _execution_success or handed_off or uncertain:
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
        if not _execution_success and not handed_off and safe_code != "outcome_unknown":
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
        data["workflow_execution"] = {
            **bounded_outcome,
            **({"waiting_user_decision": True} if include_waiting_decision else {}),
        }
        for key in (
            "agent_run_id",
            "execution_state",
            "plan_id",
            "requires_reconciliation",
            "retryable",
        ):
            if key in (workflow_execution or {}):
                data["workflow_execution"][key] = (workflow_execution or {})[key]
        if handed_off:
            data["workflow_execution"]["execution_accepted"] = True
            if (workflow_execution or {}).get("waiting_approval"):
                data["workflow_execution"]["next_approval_request_id"] = (
                    workflow_execution or {}
                ).get("next_approval_request_id")
            return JSONResponse(
                {
                    "success": False,
                    "accepted": True,
                    "data": data,
                    "message": handoff_message,
                },
                status_code=202,
            )
        if uncertain:
            return JSONResponse(
                {
                    "success": False,
                    "accepted": True,
                    "data": data,
                    "message": bounded_outcome["message"],
                },
                status_code=202,
            )
        if not _execution_success:
            failure_message = "审批通过后 AI 工作流执行失败，审批已取消"
            if safe_code in SETUP_GUIDANCE_CODES:
                failure_message = f"{failure_message}：{safe_message}"
            return JSONResponse(
                {"success": False, "data": data, "message": failure_message},
                status_code=409,
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
