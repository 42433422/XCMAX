"""Submission, withdrawal, and applicant-owned retention transactions."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.models.approval import (
    ApprovalAction,
    ApprovalFlow,
    ApprovalFlowNode,
    ApprovalRecord,
    ApprovalRequest,
    ApprovalStatus,
)

from .access import FINAL_STATUSES, normalize_statuses
from .ports import ApprovalAccess, AuditWriter, JsonObject, RequestView, WorkspaceResponse
from .repository import ApprovalRepository


class RequestLifecycle:
    def __init__(
        self,
        repository: ApprovalRepository,
        access: ApprovalAccess,
        audit: AuditWriter,
        view: RequestView,
        ordered_nodes: Callable[[Session, int], list[ApprovalFlowNode]],
        request_number: Callable[[], str],
    ) -> None:
        self.repository = repository
        self.access = access
        self.audit = audit
        self.view = view
        self.ordered_nodes = ordered_nodes
        self.request_number = request_number

    def submit_request(
        self, request: Request, body: JsonObject, x_user_id: str | None
    ) -> WorkspaceResponse:
        """提交一个新的审批请求；按 ``flow_key`` 找到流程并定位首个有效节点。"""
        flow_key = str(body.get("flow_key") or "").strip()
        business_type = str(body.get("business_type") or "general").strip()
        title = str(body.get("title") or "").strip()
        if not flow_key or not title:
            raise HTTPException(status_code=400, detail="flow_key 与 title 为必填项")
        actor = self.access.actor(request, x_user_id, fallback=body.get("applicant_id"))
        if actor is None:
            raise HTTPException(status_code=401, detail="请先登录")
        business_id = body.get("business_id")
        business_data = body.get("business_data")
        description = str(body.get("description") or "").strip() or None
        applicant_name = str(body.get("applicant_name") or "").strip() or None
        applicant_department = str(body.get("applicant_department") or "").strip() or None
        priority = str(body.get("priority") or "normal").strip() or "normal"
        with self.repository.session() as db:
            flow = (
                db.query(ApprovalFlow)
                .filter(ApprovalFlow.flow_key == flow_key, ApprovalFlow.is_active == True)
                .first()
            )
            if not flow:
                return JSONResponse(
                    {
                        "success": False,
                        "message": f"未找到启用的审批流程：{flow_key}",
                        "data": None,
                    },
                    status_code=404,
                )
            nodes = self.ordered_nodes(db, flow.id)
            if not nodes:
                return JSONResponse(
                    {"success": False, "message": "审批流程未配置任何启用节点", "data": None},
                    status_code=400,
                )
            first_node = nodes[0]
            req = ApprovalRequest(
                request_no=self.request_number(),
                flow_id=flow.id,
                business_type=business_type,
                business_id=int(business_id)
                if isinstance(business_id, (int, str)) and str(business_id).isdigit()
                else None,
                business_data=json.dumps(business_data, ensure_ascii=False)
                if business_data
                else None,
                applicant_id=actor,
                applicant_name=applicant_name,
                applicant_department=applicant_department,
                title=title,
                description=description,
                current_node_id=first_node.id,
                current_node_order=first_node.node_order,
                status=ApprovalStatus.PENDING.value,
                priority=priority,
            )
            db.add(req)
            db.flush()
            self.audit(
                db,
                actor=actor,
                action="approval.submit",
                payload={
                    "request_id": req.id,
                    "request_no": req.request_no,
                    "flow_id": flow.id,
                    "flow_key": flow.flow_key,
                    "business_type": business_type,
                    "business_id": req.business_id,
                    "first_node_id": first_node.id,
                },
            )
            db.commit()
            db.refresh(req)
            return {"success": True, "data": self.view(req, include_records=True)}

    def cleanup_requests(
        self, request: Request, body: JsonObject, x_user_id: str | None
    ) -> WorkspaceResponse:
        """批量清理已完成的审批记录。

        Body 参数::

            {
              "statuses": ["approved", "rejected", "withdrawn", "cancelled"],
                                  # 或 "all" / "completed"；默认全部终态
              "before_days": 0,    # 仅清理 N 天之前的记录；0/不传表示不限
              "scope": "self",    # "self" 仅清理本人（默认）；其他值暂不支持
              "dry_run": false    # true 时只返回待清理数量，不真正删除
            }
        """
        actor = self.access.actor(request, x_user_id, fallback=body.get("user_id"))
        if actor is None:
            raise HTTPException(status_code=401, detail="请先登录")
        statuses = normalize_statuses(body.get("statuses") or body.get("status"))
        dry_run = bool(body.get("dry_run", False))
        before_days_raw = body.get("before_days")
        before_days: int | None
        try:
            before_days = int(before_days_raw) if before_days_raw not in (None, "", 0) else None
        except (TypeError, ValueError):
            before_days = None
        if before_days is not None and before_days < 0:
            before_days = None
        scope = str(body.get("scope") or "self").strip() or "self"
        if scope != "self":
            return JSONResponse(
                {"success": False, "message": f"暂不支持的清理范围：{scope}"}, status_code=400
            )
        with self.repository.session() as db:
            query = db.query(ApprovalRequest).filter(
                ApprovalRequest.applicant_id == actor, ApprovalRequest.status.in_(statuses)
            )
            if before_days is not None:
                from datetime import timedelta

                cutoff = datetime.now() - timedelta(days=before_days)
                query = query.filter(ApprovalRequest.created_at < cutoff)
            items = query.all()
            matched = len(items)
            if dry_run or matched == 0:
                return {
                    "success": True,
                    "data": {
                        "matched": matched,
                        "deleted": 0,
                        "dry_run": dry_run,
                        "statuses": statuses,
                        "before_days": before_days,
                    },
                }
            ids = [req.id for req in items]
            nos = [req.request_no for req in items]
            self.audit(
                db,
                actor=actor,
                action="approval.cleanup",
                payload={
                    "count": matched,
                    "statuses": statuses,
                    "before_days": before_days,
                    "request_ids": ids[:500],
                    "request_nos": nos[:500],
                },
            )
            for req in items:
                db.delete(req)
            db.commit()
            return {
                "success": True,
                "data": {
                    "matched": matched,
                    "deleted": matched,
                    "dry_run": False,
                    "statuses": statuses,
                    "before_days": before_days,
                },
            }

    def withdraw_request(
        self, request_id: int, http_request: Request, body: JsonObject, x_user_id: str | None
    ) -> WorkspaceResponse:
        actor = self.access.actor(http_request, x_user_id, fallback=body.get("user_id"))
        if actor is None:
            raise HTTPException(status_code=401, detail="请先登录")
        with self.repository.session() as db:
            req = self.repository.request(db, request_id)
            if not req:
                return JSONResponse(
                    {"success": False, "message": "审批请求不存在"}, status_code=404
                )
            if req.applicant_id != actor:
                return JSONResponse(
                    {"success": False, "message": "只有申请人可以撤回"}, status_code=403
                )
            if req.status not in (ApprovalStatus.PENDING.value, ApprovalStatus.IN_PROGRESS.value):
                return JSONResponse(
                    {"success": False, "message": f"当前状态不可撤回：{req.status}"},
                    status_code=400,
                )
            flow = req.flow
            if flow is not None and flow.allow_withdraw is False:
                return JSONResponse(
                    {"success": False, "message": "该流程不允许撤回"}, status_code=400
                )
            status_before = req.status
            current_node = req.current_node
            record = ApprovalRecord(
                request_id=req.id,
                node_id=current_node.id if current_node else 0,
                node_name=current_node.node_name if current_node else "",
                node_order=current_node.node_order if current_node else 0,
                approver_id=actor,
                action=ApprovalAction.WITHDRAW.value,
                opinion="申请人撤回",
                is_passed=False,
            )
            db.add(record)
            req.status = ApprovalStatus.WITHDRAWN.value
            self.audit(
                db,
                actor=actor,
                action="approval.withdraw",
                payload={
                    "request_id": req.id,
                    "request_no": req.request_no,
                    "flow_id": req.flow_id,
                    "status_before": status_before,
                    "status_after": req.status,
                },
            )
            db.commit()
            db.refresh(req)
            return {"success": True, "data": self.view(req, include_records=True)}

    def delete_request(
        self, request_id: int, http_request: Request, x_user_id: str | None
    ) -> WorkspaceResponse:
        """物理删除单个审批申请（仅申请人本人，且必须处于终态。

        级联删除 ``approval_records``；会写入一条 ``approval.delete`` 审计。
        """
        actor = self.access.actor(http_request, x_user_id)
        if actor is None:
            raise HTTPException(status_code=401, detail="请先登录")
        with self.repository.session() as db:
            req = self.repository.request(db, request_id)
            if not req:
                return JSONResponse(
                    {"success": False, "message": "审批请求不存在"}, status_code=404
                )
            if req.applicant_id != actor:
                return JSONResponse(
                    {"success": False, "message": "只有申请人可以删除自己的审批记录"},
                    status_code=403,
                )
            if req.status not in FINAL_STATUSES:
                return JSONResponse(
                    {
                        "success": False,
                        "message": f"进行中的审批不能删除，请先撤回（当前状态：{req.status}）",
                    },
                    status_code=400,
                )
            snapshot = {
                "request_id": req.id,
                "request_no": req.request_no,
                "flow_id": req.flow_id,
                "business_type": req.business_type,
                "business_id": req.business_id,
                "title": req.title,
                "status": req.status,
            }
            self.audit(db, actor=actor, action="approval.delete", payload=snapshot)
            db.delete(req)
            db.commit()
            return {"success": True, "data": {"deleted": 1, "request_id": request_id}}
