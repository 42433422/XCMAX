"""Discover separately installed conversion extensions; never run customer code here."""

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.mod_sdk.customer_features import attendance_custom_features, require_attendance_conversion


def register(router, **_legacy_options):
    @router.get("/attendance/capabilities")
    def capabilities(request: Request):
        from app.application.tenant_workspace_prefs import resolve_workspace_owner_id
        from app.infrastructure.auth.dependencies import get_logged_in_user
        from app.infrastructure.mods.install_receipts import read_verified_install

        result = attendance_custom_features(request)
        owner = resolve_workspace_owner_id(request, get_logged_in_user(request))
        receipt = read_verified_install("sunbird-attendance-custom")
        ready = bool(
            receipt and receipt.get("owner_scope") == owner and not receipt.get("requires_restart")
        )
        result["requires_install"] = bool(result["custom_features"] and not ready)
        if not ready:
            result["custom_features"] = []
        result["extension_path"] = "/mod/sunbird-attendance-custom/convert" if ready else ""
        return result

    @router.api_route(
        "/attendance/{operation}",
        methods=["GET", "POST"],
        dependencies=[Depends(require_attendance_conversion)],
    )
    def legacy_conversion(operation: str, request: Request):
        if operation not in {"rules", "policy", "template", "convert-upload"}:
            raise HTTPException(410, "旧转换结果路径已停用，请在独立定制 Mod 中重新生成")
        path = f"/api/mod/sunbird-attendance-custom/attendance/{operation}"
        if request.url.query:
            path += "?" + request.url.query
        return RedirectResponse(path, status_code=307)
