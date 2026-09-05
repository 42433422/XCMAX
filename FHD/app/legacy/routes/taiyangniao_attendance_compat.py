"""Deprecated account endpoint forwarding to the independently delivered Mod."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.mod_sdk.customer_features import require_attendance_conversion

MOD_ID = "taiyangniao-pro"
router = APIRouter(
    prefix=f"/api/mod/{MOD_ID}",
    tags=["sunbird-attendance-compat"],
    dependencies=[Depends(require_attendance_conversion)],
)


@router.api_route("/attendance/{operation}", methods=["GET", "POST"])
def attendance_compat(operation: str, request: Request):
    if operation not in {"rules", "policy", "template", "convert-upload"}:
        raise HTTPException(410, "旧考勤转换文件路径已停用，请从定制 Mod 重新生成")
    target = f"/api/mod/sunbird-attendance-custom/attendance/{operation}"
    if request.url.query:
        target += "?" + request.url.query
    return RedirectResponse(target, status_code=307)
