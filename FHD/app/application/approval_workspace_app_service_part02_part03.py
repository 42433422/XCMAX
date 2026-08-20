# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.approval_workspace_app_service")


def update_flow(
    flow_id: int,
    request: _facade().Request,
    body: dict = _facade().Body(default_factory=dict),
    x_user_id: str | None = _facade().Header(default=None, alias="X-User-ID"),
):
    """更新审批流程基础信息（不含节点，节点暂由 POST /flows 重建）。"""
    actor = _facade()._resolve_actor(request, x_user_id)
    with _facade().get_db() as db:
        flow = (
            db.query(_facade().ApprovalFlow)
            .filter(
                _facade().ApprovalFlow.id == flow_id, _facade().ApprovalFlow.is_deleted == False
            )
            .first()
        )
        if not flow:
            return _facade().JSONResponse(
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
        flow.updated_at = _facade().utc_now_naive()
        _facade()._audit(
            db, actor=actor, action="approval_flow_update", payload={"flow_id": flow_id, **body}
        )
        db.commit()
        db.refresh(flow)
        return {"success": True, "data": flow.to_dict()}


def toggle_flow_active(
    flow_id: int,
    request: _facade().Request,
    body: dict = _facade().Body(default_factory=dict),
    x_user_id: str | None = _facade().Header(default=None, alias="X-User-ID"),
):
    """启用 / 停用审批流程。body: {is_active: bool}"""
    actor = _facade()._resolve_actor(request, x_user_id)
    is_active = bool(body.get("is_active", True))
    with _facade().get_db() as db:
        flow = (
            db.query(_facade().ApprovalFlow)
            .filter(
                _facade().ApprovalFlow.id == flow_id, _facade().ApprovalFlow.is_deleted == False
            )
            .first()
        )
        if not flow:
            return _facade().JSONResponse(
                {"success": False, "message": "审批流程不存在"}, status_code=404
            )
        flow.is_active = is_active
        flow.updated_at = _facade().utc_now_naive()
        _facade()._audit(
            db,
            actor=actor,
            action="approval_flow_toggle_active",
            payload={"flow_id": flow_id, "is_active": is_active},
        )
        db.commit()
        return {
            "success": True,
            "message": f"流程已{('启用' if is_active else '停用')}",
            "is_active": is_active,
        }


def delete_flow(
    flow_id: int,
    request: _facade().Request,
    x_user_id: str | None = _facade().Header(default=None, alias="X-User-ID"),
):
    """软删除审批流程（is_deleted = True）。"""
    actor = _facade()._resolve_actor(request, x_user_id)
    with _facade().get_db() as db:
        flow = (
            db.query(_facade().ApprovalFlow)
            .filter(
                _facade().ApprovalFlow.id == flow_id, _facade().ApprovalFlow.is_deleted == False
            )
            .first()
        )
        if not flow:
            return _facade().JSONResponse(
                {"success": False, "message": "审批流程不存在或已删除"}, status_code=404
            )
        pending_count = (
            db.query(_facade().ApprovalRequest)
            .filter(
                _facade().ApprovalRequest.flow_id == flow_id,
                _facade().ApprovalRequest.status == _facade().ApprovalStatus.PENDING,
            )
            .count()
        )
        if pending_count > 0:
            return _facade().JSONResponse(
                {"success": False, "message": f"流程下有 {pending_count} 条待审批请求，无法删除"},
                status_code=409,
            )
        flow.is_deleted = True
        flow.is_active = False
        flow.updated_at = _facade().utc_now_naive()
        _facade()._audit(
            db, actor=actor, action="approval_flow_delete", payload={"flow_id": flow_id}
        )
        db.commit()
        return {"success": True, "message": "审批流程已删除"}
