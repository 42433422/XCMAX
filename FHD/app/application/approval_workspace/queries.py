"""Read-side approval workspace queries, with per-call scoped sessions."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.models.approval import ApprovalFlow, ApprovalRequest, ApprovalStatus
from app.db.models.user import User

from .access import AI_WORKFLOW_NODE_NAME
from .ports import ApprovalAccess, RequestView, WorkspaceResponse
from .repository import ApprovalRepository


class ApprovalQueries:
    def __init__(
        self,
        repository: ApprovalRepository,
        access: ApprovalAccess,
        view: RequestView,
        pending: Callable[[str | None], bool],
        users: Callable[[Session], list[User]],
        roster: Callable[[], object],
        errors: tuple[type[Exception], ...],
    ) -> None:
        self.repository = repository
        self.access = access
        self.view = view
        self.pending = pending
        self.users = users
        self.roster = roster
        self.errors = errors

    def list_requests(
        self,
        approver_id: int | None,
        applicant_id: int | None,
        status: str | None,
        business_type: str | None,
        page: int,
        page_size: int,
    ) -> WorkspaceResponse:
        """列表接口：支持按申请人 / 当前审批人 / 状态过滤。"""
        with self.repository.session() as db:
            query = db.query(ApprovalRequest)
            if applicant_id is not None:
                query = query.filter(ApprovalRequest.applicant_id == applicant_id)
            if status:
                query = query.filter(ApprovalRequest.status == status)
            else:
                query = query.filter(
                    ApprovalRequest.status.in_(
                        [
                            ApprovalStatus.PENDING.value,
                            ApprovalStatus.IN_PROGRESS.value,
                            ApprovalStatus.APPROVED.value,
                            ApprovalStatus.REJECTED.value,
                            ApprovalStatus.WITHDRAWN.value,
                            ApprovalStatus.CANCELLED.value,
                        ]
                    )
                )
            if business_type:
                query = query.filter(ApprovalRequest.business_type == business_type)
            query = query.order_by(ApprovalRequest.created_at.desc())
            total = query.count()
            items = query.offset((page - 1) * page_size).limit(page_size).all()
            result: list[dict[str, Any]] = []
            for req in items:
                data = self.view(req, include_records=False)
                if approver_id is not None:
                    node = req.current_node
                    if self.access.is_workflow(req) and (not node):
                        if req.status not in (
                            ApprovalStatus.PENDING.value,
                            ApprovalStatus.IN_PROGRESS.value,
                        ):
                            continue
                        if not self.pending(req.request_no):
                            continue
                        if not self.access.workflow_reviewer(db, req, approver_id):
                            continue
                        data["current_node_name"] = AI_WORKFLOW_NODE_NAME
                        data["current_approvers"] = [int(approver_id)]
                        result.append(data)
                        continue
                    if not node or not self.access.node_reviewer(node, approver_id):
                        continue
                    if req.status not in (
                        ApprovalStatus.PENDING.value,
                        ApprovalStatus.IN_PROGRESS.value,
                    ):
                        continue
                result.append(data)
            return {
                "success": True,
                "data": result,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "returned": len(result),
                },
            }

    def get_request_detail(self, request_id: int) -> WorkspaceResponse:
        with self.repository.session() as db:
            req = self.repository.request(db, request_id)
            if not req:
                return JSONResponse(
                    {"success": False, "message": "审批请求不存在", "data": None}, status_code=404
                )
            return {"success": True, "data": self.view(req, include_records=True)}

    def list_flows(self, is_active: bool | None, business_type: str | None) -> WorkspaceResponse:
        with self.repository.session() as db:
            query = db.query(ApprovalFlow).filter(ApprovalFlow.is_deleted == False)
            if is_active is not None:
                query = query.filter(ApprovalFlow.is_active == bool(is_active))
            if business_type:
                query = query.filter(ApprovalFlow.business_type == business_type)
            query = query.order_by(ApprovalFlow.created_at.desc())
            flows = query.all()
            return {"success": True, "data": [flow.to_dict() for flow in flows]}

    def get_flow_detail(self, flow_id: int) -> WorkspaceResponse:
        with self.repository.session() as db:
            flow = self.repository.flow(db, flow_id, include_deleted=True)
            if not flow:
                return JSONResponse(
                    {"success": False, "message": "审批流程不存在", "data": None}, status_code=404
                )
            return {"success": True, "data": flow.to_dict()}

    def check_approver_orphan(self, user_id: int) -> WorkspaceResponse:
        """检查某用户 ID 是否出现在激活流程的审批节点但在用户表中已不存在（孤儿检测）。"""
        with self.repository.session() as db:
            active_flows = (
                db.query(ApprovalFlow)
                .filter(ApprovalFlow.is_active == True, ApprovalFlow.is_deleted == False)
                .all()
            )
            orphan_flows: list[dict] = []
            for flow in active_flows:
                for node in flow.nodes or []:
                    ids = []
                    try:
                        ids = json.loads(node.approver_ids or "[]")
                    except self.errors:
                        pass
                    if user_id in ids:
                        orphan_flows.append(
                            {"flow_id": flow.id, "flow_name": flow.flow_name, "node_id": node.id}
                        )
            is_orphan = len(orphan_flows) > 0
            return {
                "success": True,
                "user_id": user_id,
                "is_orphan_in_active_flows": is_orphan,
                "orphan_flows": orphan_flows,
                "message": f"用户 {user_id} {('出现在以下激活流程节点中但可能已不存在' if is_orphan else '未在任何激活流程节点中')}",
            }

    def get_approval_users(self) -> WorkspaceResponse:
        users: list[dict[str, Any]] = []
        try:
            with self.repository.session() as db:
                users = [
                    {
                        "id": user.id,
                        "name": getattr(user, "name", None)
                        or getattr(user, "username", "")
                        or f"用户{user.id}",
                        "email": getattr(user, "email", None),
                        "department": getattr(user, "department", None),
                    }
                    for user in self.users(db)
                ]
        except self.errors:
            pass
        if not users:
            try:
                products = self.roster()
                if isinstance(products, list):
                    for product in products[:50]:
                        name = str(product.get("name") or product.get("product_name") or "").strip()
                        if name:
                            users.append(
                                {"id": product.get("id"), "name": name, "source": "roster"}
                            )
            except self.errors:
                pass
        return {"success": True, "data": users, "count": len(users)}
