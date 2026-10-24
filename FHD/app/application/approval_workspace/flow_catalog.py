"""Approval flow configuration and lifecycle, using explicit ORM factories."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.models.approval import ApprovalFlow, ApprovalFlowNode, ApprovalRequest, ApprovalStatus

from .ports import ApprovalAccess, AuditWriter, JsonObject, WorkspaceResponse
from .repository import ApprovalRepository


class FlowCatalog:
    def __init__(
        self,
        repository: ApprovalRepository,
        access: ApprovalAccess,
        audit: AuditWriter,
        flow_factory: type[ApprovalFlow],
        node_factory: type[ApprovalFlowNode],
        now: Callable[[], datetime],
    ) -> None:
        self.repository = repository
        self.access = access
        self.audit = audit
        self.flow_factory = flow_factory
        self.node_factory = node_factory
        self.now = now

    def create_flow(
        self, request: Request, body: JsonObject, x_user_id: str | None
    ) -> WorkspaceResponse:
        """创建审批流程；body 形如 ``{flow: {...}, nodes: [...]}``。"""
        flow_payload = body.get("flow") or {}
        nodes_payload = body.get("nodes") or []
        if not isinstance(flow_payload, dict) or not isinstance(nodes_payload, list):
            raise HTTPException(status_code=400, detail="flow / nodes 字段格式错误")
        flow_name = str(flow_payload.get("flow_name") or "").strip()
        flow_key = str(flow_payload.get("flow_key") or "").strip()
        business_type = str(flow_payload.get("business_type") or "general").strip() or "general"
        if not flow_name or not flow_key:
            raise HTTPException(status_code=400, detail="flow_name / flow_key 为必填项")
        if not nodes_payload:
            raise HTTPException(status_code=400, detail="至少需要一个审批节点")
        actor = self.access.actor(request, x_user_id, fallback=flow_payload.get("created_by"))
        with self.repository.session() as db:
            existed = (
                db.query(ApprovalFlow)
                .filter(ApprovalFlow.flow_key == flow_key, ApprovalFlow.is_deleted == False)
                .first()
            )
            if existed:
                return JSONResponse(
                    {"success": False, "message": f"flow_key 已存在：{flow_key}"}, status_code=409
                )
            flow = self.flow_factory(
                flow_key=flow_key,
                flow_name=flow_name,
                description=str(flow_payload.get("description") or "").strip() or None,
                industry=str(flow_payload.get("industry") or "通用").strip() or "通用",
                business_type=business_type,
                node_type=str(flow_payload.get("node_type") or "serial"),
                allow_transfer=bool(flow_payload.get("allow_transfer", True)),
                allow_delegate=bool(flow_payload.get("allow_delegate", False)),
                allow_withdraw=bool(flow_payload.get("allow_withdraw", True)),
                timeout_hours=int(flow_payload.get("timeout_hours") or 48),
                is_active=bool(flow_payload.get("is_active", True)),
                is_deleted=False,
                created_by=actor,
            )
            db.add(flow)
            db.flush()
            for idx, node_data in enumerate(nodes_payload, start=1):
                if not isinstance(node_data, dict):
                    continue
                approver_ids = node_data.get("approver_ids") or []
                if not isinstance(approver_ids, list):
                    approver_ids = []
                node = self.node_factory(
                    flow_id=flow.id,
                    node_name=str(node_data.get("node_name") or f"节点{idx}").strip(),
                    node_order=int(node_data.get("node_order") or idx),
                    node_type=str(node_data.get("node_type") or "serial"),
                    approver_type=str(node_data.get("approver_type") or "user"),
                    approver_ids=json.dumps(
                        [int(x) for x in approver_ids if str(x).strip().lstrip("-").isdigit()],
                        ensure_ascii=False,
                    ),
                    min_approvals=int(node_data.get("min_approvals") or 1),
                    condition_expression=node_data.get("condition_expression") or None,
                    condition_description=node_data.get("condition_description") or None,
                    timeout_hours=node_data.get("timeout_hours"),
                    timeout_action=str(node_data.get("timeout_action") or "notify"),
                    is_active=bool(node_data.get("is_active", True)),
                )
                db.add(node)
            self.audit(
                db,
                actor=actor,
                action="approval.flow.create",
                payload={
                    "flow_id": flow.id,
                    "flow_key": flow_key,
                    "flow_name": flow_name,
                    "business_type": business_type,
                    "node_count": len(nodes_payload),
                },
            )
            db.commit()
            db.refresh(flow)
            return {"success": True, "data": flow.to_dict()}

    def update_flow(
        self, flow_id: int, request: Request, body: JsonObject, x_user_id: str | None
    ) -> WorkspaceResponse:
        """更新审批流程基础信息（不含节点，节点暂由 POST /flows 重建）。"""
        actor = self.access.actor(request, x_user_id)
        with self.repository.session() as db:
            flow = self.repository.flow(db, flow_id, include_deleted=False)
            if not flow:
                return JSONResponse(
                    {"success": False, "message": "审批流程不存在"}, status_code=404
                )
            updatable = [
                "flow_name",
                "description",
                "industry",
                "business_type",
                "node_type",
                "allow_transfer",
                "allow_delegate",
                "allow_withdraw",
                "timeout_hours",
            ]
            for field in updatable:
                if field in body:
                    setattr(flow, field, body[field])
            self._commit_change(
                db, flow, actor, "approval_flow_update", {"flow_id": flow_id, **body}, refresh=True
            )
            return {"success": True, "data": flow.to_dict()}

    def toggle_flow_active(
        self, flow_id: int, request: Request, body: JsonObject, x_user_id: str | None
    ) -> WorkspaceResponse:
        """启用 / 停用审批流程。body: {is_active: bool}"""
        actor = self.access.actor(request, x_user_id)
        is_active = bool(body.get("is_active", True))
        with self.repository.session() as db:
            flow = self.repository.flow(db, flow_id, include_deleted=False)
            if not flow:
                return JSONResponse(
                    {"success": False, "message": "审批流程不存在"}, status_code=404
                )
            flow.is_active = is_active
            self._commit_change(
                db,
                flow,
                actor,
                "approval_flow_toggle_active",
                {"flow_id": flow_id, "is_active": is_active},
            )
            return {
                "success": True,
                "message": f"流程已{('启用' if is_active else '停用')}",
                "is_active": is_active,
            }

    def delete_flow(
        self, flow_id: int, request: Request, x_user_id: str | None
    ) -> WorkspaceResponse:
        """软删除审批流程（is_deleted = True）。"""
        actor = self.access.actor(request, x_user_id)
        with self.repository.session() as db:
            flow = self.repository.flow(db, flow_id, include_deleted=False)
            if not flow:
                return JSONResponse(
                    {"success": False, "message": "审批流程不存在或已删除"}, status_code=404
                )
            pending_count = (
                db.query(ApprovalRequest)
                .filter(
                    ApprovalRequest.flow_id == flow_id,
                    ApprovalRequest.status == ApprovalStatus.PENDING,
                )
                .count()
            )
            if pending_count > 0:
                return JSONResponse(
                    {
                        "success": False,
                        "message": f"流程下有 {pending_count} 条待审批请求，无法删除",
                    },
                    status_code=409,
                )
            flow.is_deleted = True
            flow.is_active = False
            self._commit_change(db, flow, actor, "approval_flow_delete", {"flow_id": flow_id})
            return {"success": True, "message": "审批流程已删除"}

    def _commit_change(
        self,
        db: Session,
        flow: ApprovalFlow,
        actor: int | None,
        action: str,
        payload: JsonObject,
        *,
        refresh: bool = False,
    ) -> None:
        flow.updated_at = self.now()
        self.audit(db, actor=actor, action=action, payload=payload)
        db.commit()
        if refresh:
            db.refresh(flow)
