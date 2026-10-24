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


def can_review_workflow(db: Session, req: ApprovalRequest, actor: int) -> bool:
    if int(req.applicant_id or 0) == int(actor):
        return True
    user = db.query(User).filter(User.id == int(actor), User.is_active == True).first()
    return str(getattr(user, "role", "") or "").strip().lower() in {
        "admin",
        "superadmin",
        "super_admin",
        "owner",
    }


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
