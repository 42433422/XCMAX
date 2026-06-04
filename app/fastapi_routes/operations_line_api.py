"""运营线健康度 API（供全景页 / MODstore admin 拉取）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.application.operations_app_service import get_operations_app_service
from app.application.user_cs_app_service import get_user_cs_app_service

router = APIRouter(prefix="/api/operations-line", tags=["operations-line"])


@router.get("/health")
def operations_health():
    return JSONResponse(
        {"success": True, "data": get_operations_app_service().compute_operations_health()}
    )


@router.post("/contracts/scan-expiry")
def operations_scan_contract_expiry(days_ahead: int = 30, dry_run: bool = True):
    return JSONResponse(
        {
            "success": True,
            "data": get_operations_app_service().run_contract_expiry_scan(
                days_ahead=days_ahead, dry_run=dry_run
            ),
        }
    )


@router.get("/signoff/status")
def operations_signoff_status():
    return JSONResponse(
        {"success": True, "data": get_user_cs_app_service().signoff_backend_info()}
    )


@router.get("/reconciliation/status")
def operations_reconciliation_status():
    sched = get_operations_app_service().reconciliation_scheduler()
    return JSONResponse(
        {"success": True, "data": sched.get_reconciliation_status()}
    )


@router.post("/reconciliation/run")
def operations_reconciliation_run(dry_run: bool = False):
    sched = get_operations_app_service().reconciliation_scheduler()
    data = (
        sched.run_reconciliation_preview_cycle()
        if dry_run
        else sched.run_reconciliation_full_cycle()
    )
    return JSONResponse({"success": bool(data.get("ok")), "data": data})
