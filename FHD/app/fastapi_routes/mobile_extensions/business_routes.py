"""Approval / customer / shipment / employee-ssot routes (split from mobile_api_extensions).

Included into ``extension_router``; handlers are re-exported from
``mobile_api_extensions`` for tests and patch compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions import _ext as mext
from app.utils.mobile_api import format_mobile_response, paginate_list

logger = logging.getLogger(__name__)

business_router = APIRouter()


def _employee_ssot_payload() -> dict[str, Any]:
    """管理端 6 部门上岗 + 企业端 4 部门上架/未上架，自动派生自 SSOT。"""
    from app.application.ops_closure_status import _installed_employee_pack_ids
    from app.mod_sdk.employee_ssot import derive_employee_ssot

    installed: set[str] = set()
    try:
        installed = _installed_employee_pack_ids()
    except mext.OPERATIONAL_ERRORS as exc:
        logger.warning("mobile employee-ssot: 读取已安装 employee_pack 失败: %s", exc)
    return derive_employee_ssot(installed_ids=installed)


@business_router.get("/approval/requests")
async def mobile_approval_list(
    request: Request,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
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
    return format_mobile_response(data=paginate_list(items, total, page, page_size))


@business_router.get("/customers")
async def mobile_customers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.db.models import Customer
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import apply_tenant_filter

    with get_db() as db:
        q = apply_tenant_filter(db.query(Customer), Customer)
        total = q.count()
        rows = q.offset((page - 1) * per_page).limit(per_page).all()
        items = [
            {
                "id": c.id,
                "name": c.customer_name,
                "phone": c.contact_phone,
            }
            for c in rows
        ]
    return format_mobile_response(data=paginate_list(items, total, page, per_page))


@business_router.get("/shipments")
async def mobile_shipments(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.db.models.shipment import ShipmentRecord
    from app.db.session import get_db

    with get_db() as db:
        q = db.query(ShipmentRecord)
        total = q.count()
        rows = (
            q.order_by(ShipmentRecord.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        )
        items = [
            {
                "id": r.id,
                "order_number": getattr(r, "order_number", None) or getattr(r, "shipment_no", None),
                "status": getattr(r, "status", None),
            }
            for r in rows
        ]
    return format_mobile_response(data=paginate_list(items, total, page, per_page))


@business_router.get("/employee-ssot")
async def mobile_employee_ssot(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    return format_mobile_response(data=_employee_ssot_payload())
