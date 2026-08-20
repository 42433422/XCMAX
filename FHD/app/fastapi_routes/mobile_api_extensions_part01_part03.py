# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.mobile_api_extensions")


@_facade().extension_router.get("/approval/requests")
async def mobile_approval_list(
    request: _facade().Request,
    status: str | None = None,
    page: int = _facade().Query(1, ge=1),
    page_size: int = _facade().Query(50, ge=1, le=200),
    user=_facade().Depends(_facade().get_mobile_user),
):
    if user is None:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    from app.db.models.approval import ApprovalRequest
    from app.db.session import get_db

    with get_db() as db:
        q = db.query(ApprovalRequest)
        if status:
            q = q.filter(ApprovalRequest.status == status)
        total = q.count()
        rows = (
            q.order_by(ApprovalRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [
            {
                "id": r.id,
                "title": r.title,
                "status": r.status,
                "request_no": r.request_no,
                "applicant_id": r.applicant_id,
            }
            for r in rows
        ]
    return _facade().format_mobile_response(
        data=_facade().paginate_list(items, total, page, page_size)
    )
