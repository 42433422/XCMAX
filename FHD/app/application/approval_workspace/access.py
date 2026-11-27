"""Actor resolution and approval policy, independent of HTTP routing and storage factories."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.models.approval import ApprovalFlow, ApprovalFlowNode, ApprovalRequest, ApprovalStatus
from app.db.models.user import User

AI_WORKFLOW_BUSINESS_TYPE = "workflow_tool"
AI_WORKFLOW_NODE_NAME = "AI 工作流审批"
FINAL_STATUSES = (
    ApprovalStatus.APPROVED.value,
    ApprovalStatus.REJECTED.value,
    ApprovalStatus.WITHDRAWN.value,
    ApprovalStatus.CANCELLED.value,
)


def serial_approval_supported(node_type: object, min_approvals: object = 1) -> bool:
    return node_type in (None, "", "serial") and min_approvals in (None, "", 1, "1")


def supported_approval_flow(flow: ApprovalFlow | None, nodes: list[ApprovalFlowNode]) -> bool:
    return serial_approval_supported(getattr(flow, "node_type", None)) and all(
        serial_approval_supported(node.node_type, node.min_approvals) for node in nodes
    )


def unsupported_approval_policy() -> JSONResponse:
    return JSONResponse(
        {
            "success": False,
            "code": "unsupported_approval_policy",
            "message": "当前仅支持串行审批（serial），每个节点通过人数必须为 1。"
            "会签、并行和多票审批尚不支持；请使用受支持的流程配置并重新发起审批。",
        },
        status_code=409,
    )


def single_step_policy_required() -> JSONResponse:
    return JSONResponse(
        {
            "success": False,
            "code": "single_step_approval_required",
            "message": "新增审批仅允许一个串行节点、单人批准，不再支持多级、会签、并行、转签或委托；"
            "历史记录和在途请求保留。",
        },
        status_code=409,
    )


def allow_x_user_id_header() -> bool:
    """测试/e2e 专用；生产环境不信任自报 X-User-ID。"""
    return os.environ.get("FHD_ALLOW_X_USER_ID_HEADER", "").strip().lower() in {"1", "true", "yes"}


def node_has_reviewer(node: ApprovalFlowNode | None, user_id: int) -> bool:
    """判断 ``user_id`` 是否在节点的审批人列表中。"""
    if not node or not node.approver_ids:
        return False
    try:
        ids = (
            json.loads(node.approver_ids)
            if isinstance(node.approver_ids, str)
            else node.approver_ids
        )
    except (ValueError, TypeError):
        return False
    if not isinstance(ids, list):
        return False
    try:
        return int(user_id) in [int(x) for x in ids if x is not None]
    except (TypeError, ValueError):
        return False


def is_workflow_request(req: ApprovalRequest) -> bool:
    return str(getattr(req, "business_type", "") or "").strip() == AI_WORKFLOW_BUSINESS_TYPE


_WORKFLOW_REVIEW_ROLES = frozenset({"admin", "superadmin", "super_admin", "owner"})


def _request_tenant(req: ApprovalRequest) -> int | None:
    raw = getattr(req, "tenant_id", None)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _user_tenant(user: User) -> int | None:
    raw = getattr(user, "tenant_id", None)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _workflow_tool_action(req: ApprovalRequest) -> tuple[str, str]:
    tool_id = str(getattr(req, "tool_id", "") or "").strip()
    action = str(getattr(req, "action", "") or "").strip()
    raw = getattr(req, "business_data", None)
    business: dict[str, Any] = {}
    if isinstance(raw, dict):
        business = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            business = parsed
    return tool_id or str(business.get("tool_id") or "").strip(), action or str(
        business.get("action") or ""
    ).strip()


def approval_permission_codes(req: ApprovalRequest) -> frozenset[str]:
    """Business grant required when the actor is not a same-tenant review role."""
    tool_id, action = _workflow_tool_action(req)
    codes = {"approval.workflow"}
    if tool_id and action:
        codes.add(f"approval.{tool_id}.{action}")
    return frozenset(codes)


def _holds_approval_permission(user: User, req: ApprovalRequest) -> bool:
    direct = getattr(user, "permissions", None)
    if isinstance(direct, (set, list, tuple, frozenset)):
        return bool({str(item) for item in direct} & approval_permission_codes(req))
    if not isinstance(getattr(user, "role", None), str):
        return False
    try:
        from app.domain.shared_services.auth_service import get_auth_service

        held = {str(item) for item in get_auth_service().get_user_permissions(user)}
    except (AttributeError, LookupError, RuntimeError, TypeError, ValueError):
        return False
    return bool(held & approval_permission_codes(req))


def can_review_workflow(db: Session, req: ApprovalRequest, actor: int) -> bool:
    """申请人身份本身不构成审批权。同租户的审批角色或业务授权才可以批，包括批自己的申请。"""
    user = db.query(User).filter(User.id == int(actor), User.is_active == True).first()
    if user is None:
        return False
    request_tenant = _request_tenant(req)
    user_tenant = _user_tenant(user)
    if request_tenant is not None and user_tenant != request_tenant:
        return False
    role = str(getattr(user, "role", "") or "").strip().lower()
    if isinstance(getattr(user, "role", None), str) and role in _WORKFLOW_REVIEW_ROLES:
        return True
    return _holds_approval_permission(user, req)


def next_node(nodes: list[ApprovalFlowNode], current_order: int) -> ApprovalFlowNode | None:
    for n in nodes:
        if n.node_order > current_order:
            return n
    return None


def normalize_statuses(raw: Any) -> list[str]:
    """标准化前端传入的状态过滤参数。"""
    if raw is None:
        return list(FINAL_STATUSES)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw or raw in ("all", "completed", "final"):
            return list(FINAL_STATUSES)
        raw = [s.strip() for s in raw.split(",") if s.strip()]
    if not isinstance(raw, list):
        return list(FINAL_STATUSES)
    allowed = set(FINAL_STATUSES)
    result = [s for s in (str(x).strip() for x in raw) if s in allowed]
    return result or list(FINAL_STATUSES)


def resolve_actor(
    request: Request,
    x_user_id: str | None,
    fallback: int | None,
    *,
    session_user: Callable[[Request], User | None],
    allow_header: Callable[[], bool],
) -> int | None:
    user = session_user(request)
    if user is not None and getattr(user, "id", None) is not None:
        return int(user.id)
    if allow_header() and x_user_id and str(x_user_id).strip().isdigit():
        return int(str(x_user_id).strip())
    if fallback is not None:
        try:
            return int(fallback)
        except (TypeError, ValueError):
            return None
    return None
