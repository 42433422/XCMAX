# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.approval_workspace_app_service")


def _allow_x_user_id_header() -> bool:
    """测试/e2e 专用；生产环境不信任自报 X-User-ID。"""
    return _facade().os.environ.get("FHD_ALLOW_X_USER_ID_HEADER", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _resolve_actor(
    request: _facade().Request, x_user_id: str | None = None, fallback: int | None = None
) -> int | None:
    """优先从登录会话解析操作人；测试模式可回退 X-User-ID。"""
    from app.infrastructure.auth.dependencies import resolve_session_user

    user = resolve_session_user(request)
    if user is not None and getattr(user, "id", None) is not None:
        return int(user.id)
    if _facade()._allow_x_user_id_header() and x_user_id and str(x_user_id).strip().isdigit():
        return int(str(x_user_id).strip())
    if fallback is not None:
        try:
            return int(fallback)
        except (TypeError, ValueError):
            return None
    return None


def _audit(db, *, actor: int | None, action: str, payload: dict) -> None:
    """写入 ``ai_action_audit``：跨业务的 DB 操作轨迹。"""
    try:
        db.execute(
            _facade().text(
                "INSERT INTO ai_action_audit (actor, action, payload) VALUES (:actor, :action, :payload)"
            ),
            {
                "actor": str(actor) if actor is not None else None,
                "action": action,
                "payload": _facade().json.dumps(payload, ensure_ascii=False, default=str),
            },
        )
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning(
            "ai_action_audit 写入失败 action=%s type=%s", action, type(exc).__name__
        )


def _generate_request_no() -> str:
    """生成审批单号，例如 ``APR20260419-AB12CD``。"""
    return (
        f"APR{_facade().datetime.now().strftime('%Y%m%d')}-{_facade().secrets.token_hex(3).upper()}"
    )


def _node_query_for_user(node: _facade().ApprovalFlowNode, user_id: int) -> bool:
    """判断 ``user_id`` 是否在节点的审批人列表中。"""
    if not node or not node.approver_ids:
        return False
    try:
        ids = (
            _facade().json.loads(node.approver_ids)
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


def _ordered_nodes(db, flow_id: int) -> list[_facade().ApprovalFlowNode]:
    return _facade().cast(
        "list[ApprovalFlowNode]",
        db.query(_facade().ApprovalFlowNode)
        .filter(
            _facade().ApprovalFlowNode.flow_id == flow_id,
            _facade().ApprovalFlowNode.is_active == True,
        )
        .order_by(_facade().ApprovalFlowNode.node_order.asc())
        .all(),
    )


def _is_ai_workflow_request(req: _facade().ApprovalRequest) -> bool:
    return (
        str(getattr(req, "business_type", "") or "").strip() == _facade().AI_WORKFLOW_BUSINESS_TYPE
    )


def _can_review_ai_workflow_request(db, req: _facade().ApprovalRequest, actor: int) -> bool:
    if int(req.applicant_id or 0) == int(actor):
        return True
    user = (
        db.query(_facade().User)
        .filter(_facade().User.id == int(actor), _facade().User.is_active == True)
        .first()
    )
    return str(getattr(user, "role", "") or "").strip().lower() in {
        "admin",
        "superadmin",
        "super_admin",
        "owner",
    }


def _ai_workflow_audit_node(
    db, req: _facade().ApprovalRequest
) -> _facade().ApprovalFlowNode | None:
    return _facade().cast(
        "ApprovalFlowNode | None",
        db.query(_facade().ApprovalFlowNode)
        .filter(
            _facade().ApprovalFlowNode.flow_id == req.flow_id,
            _facade().ApprovalFlowNode.is_active == True,
        )
        .order_by(_facade().ApprovalFlowNode.node_order.asc())
        .first(),
    )


def _has_pending_ai_workflow(request_no: str | None) -> bool:
    approval_request_id = str(request_no or "").strip()
    if not approval_request_id:
        return False
    try:
        from app.application.workflow import get_approval_service
        from app.application.workflow.approval_persistence import load_durable_workflow_snapshot

        if bool(get_approval_service().get_pending_workflow(approval_request_id)):
            return True
        return load_durable_workflow_snapshot(approval_request_id, allow_terminal=False) is not None
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning(
            "check pending AI workflow failed request_no=%s", approval_request_id
        )
        return False


def _next_node(
    nodes: list[_facade().ApprovalFlowNode], current_order: int
) -> _facade().ApprovalFlowNode | None:
    for n in nodes:
        if n.node_order > current_order:
            return n
    return None


def _request_to_dict(
    req: _facade().ApprovalRequest, *, include_records: bool = False
) -> dict[str, _facade().Any]:
    """统一序列化（含 ``records`` 时间线，便于详情视图渲染）。"""
    base = req.to_dict()
    business_data = base.get("business_data")
    if isinstance(business_data, dict) and isinstance(
        business_data.get("workflow_execution"), dict
    ):
        base["workflow_execution"] = business_data["workflow_execution"]
    if _facade()._is_ai_workflow_request(req) and (not getattr(req, "current_node", None)):
        base["is_ai_workflow_approval"] = True
        base["current_node_name"] = base.get("current_node_name") or _facade().AI_WORKFLOW_NODE_NAME
        base["current_approvers"] = base.get("current_approvers") or []
    if include_records:
        records = (
            sorted(req.records or [], key=lambda r: r.action_time or _facade().datetime.min)
            if req.records
            else []
        )
        base["records"] = [r.to_dict() for r in records]
    return base


def list_requests(
    approver_id: int | None = _facade().Query(default=None),
    applicant_id: int | None = _facade().Query(default=None),
    status: str | None = _facade().Query(default=None),
    business_type: str | None = _facade().Query(default=None),
    page: int = _facade().Query(default=1, ge=1),
    page_size: int = _facade().Query(default=50, ge=1, le=500),
):
    """列表接口：支持按申请人 / 当前审批人 / 状态过滤。"""
    with _facade().get_db() as db:
        query = db.query(_facade().ApprovalRequest)
        if applicant_id is not None:
            query = query.filter(_facade().ApprovalRequest.applicant_id == applicant_id)
        if status:
            query = query.filter(_facade().ApprovalRequest.status == status)
        else:
            query = query.filter(
                _facade().ApprovalRequest.status.in_(
                    [
                        _facade().ApprovalStatus.PENDING.value,
                        _facade().ApprovalStatus.IN_PROGRESS.value,
                        _facade().ApprovalStatus.APPROVED.value,
                        _facade().ApprovalStatus.REJECTED.value,
                        _facade().ApprovalStatus.WITHDRAWN.value,
                        _facade().ApprovalStatus.CANCELLED.value,
                    ]
                )
            )
        if business_type:
            query = query.filter(_facade().ApprovalRequest.business_type == business_type)
        query = query.order_by(_facade().ApprovalRequest.created_at.desc())
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        result: list[dict[str, _facade().Any]] = []
        for req in items:
            data = _facade()._request_to_dict(req, include_records=False)
            if approver_id is not None:
                node = req.current_node
                if _facade()._is_ai_workflow_request(req) and (not node):
                    if req.status not in (
                        _facade().ApprovalStatus.PENDING.value,
                        _facade().ApprovalStatus.IN_PROGRESS.value,
                    ):
                        continue
                    if not _facade()._has_pending_ai_workflow(req.request_no):
                        continue
                    if not _facade()._can_review_ai_workflow_request(db, req, approver_id):
                        continue
                    data["current_node_name"] = _facade().AI_WORKFLOW_NODE_NAME
                    data["current_approvers"] = [int(approver_id)]
                    result.append(data)
                    continue
                if not node or not _facade()._node_query_for_user(node, approver_id):
                    continue
                if req.status not in (
                    _facade().ApprovalStatus.PENDING.value,
                    _facade().ApprovalStatus.IN_PROGRESS.value,
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


def cleanup_requests(
    request: _facade().Request,
    body: dict = _facade().Body(default_factory=dict),
    x_user_id: str | None = _facade().Header(default=None, alias="X-User-ID"),
):
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
    actor = _facade()._resolve_actor(request, x_user_id, fallback=body.get("user_id"))
    if actor is None:
        raise _facade().HTTPException(status_code=401, detail="请先登录")
    statuses = _facade()._normalize_statuses(body.get("statuses") or body.get("status"))
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
        return _facade().JSONResponse(
            {"success": False, "message": f"暂不支持的清理范围：{scope}"}, status_code=400
        )
    with _facade().get_db() as db:
        query = db.query(_facade().ApprovalRequest).filter(
            _facade().ApprovalRequest.applicant_id == actor,
            _facade().ApprovalRequest.status.in_(statuses),
        )
        if before_days is not None:
            from datetime import timedelta

            cutoff = _facade().datetime.now() - timedelta(days=before_days)
            query = query.filter(_facade().ApprovalRequest.created_at < cutoff)
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
        _facade()._audit(
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


def get_request_detail(request_id: int):
    with _facade().get_db() as db:
        req = (
            db.query(_facade().ApprovalRequest)
            .filter(_facade().ApprovalRequest.id == request_id)
            .first()
        )
        if not req:
            return _facade().JSONResponse(
                {"success": False, "message": "审批请求不存在", "data": None}, status_code=404
            )
        return {"success": True, "data": _facade()._request_to_dict(req, include_records=True)}
