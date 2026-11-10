"""Actor resolution and approval policy, independent of HTTP routing and storage factories."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.models.approval import ApprovalFlowNode, ApprovalRequest, ApprovalStatus
from app.db.models.user import User

AI_WORKFLOW_BUSINESS_TYPE = "workflow_tool"
AI_WORKFLOW_NODE_NAME = "AI 工作流审批"
FINAL_STATUSES = (
    ApprovalStatus.APPROVED.value,
    ApprovalStatus.REJECTED.value,
    ApprovalStatus.WITHDRAWN.value,
    ApprovalStatus.CANCELLED.value,
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


def _approver_id_list(raw: Any) -> list[int]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    ids: list[int] = []
    for item in parsed:
        if item is None or isinstance(item, bool):
            continue
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _designated_reviewer_ids(db: Session, req: ApprovalRequest) -> list[int] | None:
    """Explicit approver ids on the flow. None when this request has no flow to read."""
    raw_flow = getattr(req, "flow_id", None)
    if raw_flow is None or isinstance(raw_flow, bool):
        return None
    try:
        flow_id = int(raw_flow)
    except (TypeError, ValueError):
        return None
    if flow_id <= 0:
        return None
    rows = (
        db.query(ApprovalFlowNode)
        .filter(ApprovalFlowNode.flow_id == flow_id, ApprovalFlowNode.is_active == True)
        .all()
    )
    if not isinstance(rows, list):
        return None
    designated: list[int] = []
    for node in rows:
        designated.extend(_approver_id_list(getattr(node, "approver_ids", None)))
    return designated


def can_review_workflow(db: Session, req: ApprovalRequest, actor: int) -> bool:
    """没指定审批人时，同租户申请人可以直接批。指定了审批人后，申请人身份本身不能批。"""
    user = db.query(User).filter(User.id == int(actor), User.is_active == True).first()
    if user is None:
        return False
    request_tenant = _request_tenant(req)
    user_tenant = _user_tenant(user)
    if request_tenant is not None and user_tenant != request_tenant:
        return False
    designated = _designated_reviewer_ids(db, req)
    if designated == [] and int(getattr(req, "applicant_id", 0) or 0) == int(actor):
        return True
    if designated and int(actor) in designated:
        return True
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
