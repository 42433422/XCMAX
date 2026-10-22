"""WorklistRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_extensions.ports import (
    DatabaseCall,
    EmployeeSsotPayloadCall,
    MobilePrincipal,
    UserDependency,
)
from app.utils.device_system.mobile_api import format_mobile_response, paginate_list

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorklistRoutesPorts:
    database: DatabaseCall
    employee_ssot_payload: EmployeeSsotPayloadCall


class WorklistRoutes:
    def __init__(self, ports: WorklistRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        @router.get("/approval/requests", response_model=None)
        async def mobile_approval_list(
            request: Request,
            status: str | None = None,
            page: int = Query(1, ge=1),
            page_size: int = Query(50, ge=1, le=200),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            from app.db.models.approval import ApprovalRequest

            with ports.database() as db:
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

        self.mobile_approval_list = mobile_approval_list

        @router.get("/customers", response_model=None)
        async def mobile_customers(
            page: int = Query(1, ge=1),
            per_page: int = Query(20, ge=1, le=100),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            from app.db.models import Customer
            from app.infrastructure.tenant_scope import apply_tenant_filter

            with ports.database() as db:
                q = apply_tenant_filter(db.query(Customer), Customer)
                total = q.count()
                rows = q.offset((page - 1) * per_page).limit(per_page).all()
                items = [
                    {"id": c.id, "name": c.customer_name, "phone": c.contact_phone} for c in rows
                ]
            return format_mobile_response(data=paginate_list(items, total, page, per_page))

        self.mobile_customers = mobile_customers

        @router.get("/shipments", response_model=None)
        async def mobile_shipments(
            page: int = Query(1, ge=1),
            per_page: int = Query(20, ge=1, le=100),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            from app.db.models.shipment import ShipmentRecord

            with ports.database() as db:
                q = db.query(ShipmentRecord)
                total = q.count()
                rows = (
                    q.order_by(ShipmentRecord.id.desc())
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                    .all()
                )
                items = [
                    {
                        "id": r.id,
                        "order_number": getattr(r, "order_number", None)
                        or getattr(r, "shipment_no", None),
                        "status": getattr(r, "status", None),
                    }
                    for r in rows
                ]
            return format_mobile_response(data=paginate_list(items, total, page, per_page))

        self.mobile_shipments = mobile_shipments

        @router.get("/employee-ssot", response_model=None)
        async def mobile_employee_ssot(user: MobilePrincipal | None = Depends(get_user)) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            return format_mobile_response(data=ports.employee_ssot_payload())

        self.mobile_employee_ssot = mobile_employee_ssot
