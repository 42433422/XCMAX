"""运营线健康度 API（供全景页 / MODstore admin 拉取）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.http.response_envelope import from_legacy_ok_payload

router = APIRouter(prefix="/api/operations-line", tags=["operations-line"])


@router.get("/health")
def operations_health():
    from app.application.operations_line_app_service import compute_operations_health

    return JSONResponse({"success": True, "data": compute_operations_health()})


@router.post("/contracts/scan-expiry")
def operations_scan_contract_expiry(days_ahead: int = 30, dry_run: bool = True):
    from app.application.operations_line_app_service import run_contract_expiry_scan

    return JSONResponse(
        {
            "success": True,
            "data": run_contract_expiry_scan(days_ahead=days_ahead, dry_run=dry_run),
        }
    )


@router.get("/signoff/status")
def operations_signoff_status():
    from app.application.operations_line_app_service import signoff_backend_info

    return JSONResponse({"success": True, "data": signoff_backend_info()})


@router.get("/reconciliation/status")
def operations_reconciliation_status():
    from app.application.operations_line_app_service import get_reconciliation_status

    return JSONResponse({"success": True, "data": get_reconciliation_status()})


@router.post("/reconciliation/run")
def operations_reconciliation_run(dry_run: bool = False):
    from app.application.operations_line_app_service import run_reconciliation

    data = run_reconciliation(dry_run=dry_run)
    return JSONResponse(
        from_legacy_ok_payload({"success": data.get("success", True), "data": data})
    )
