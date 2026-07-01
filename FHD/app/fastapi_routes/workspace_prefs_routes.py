"""工作区偏好 API — 租户级跨设备同步。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.application.tenant_workspace_prefs import (
    bind_selected_industry_for_user,
    get_workspace_prefs,
    patch_workspace_prefs,
    resolve_workspace_owner_id,
)
from app.infrastructure.auth.dependencies import (
    get_logged_in_user,
    resolve_session_user,
    session_id_from_request,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class WorkspacePrefsPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    selected_industry_id: str | None = None
    industry_mod_id: str | None = None
    workflow_ai_employees: dict[str, bool] | None = None
    product_flow_completed: bool | None = None
    host_pack_acknowledged: bool | None = None


async def _try_grant_market_entitlements(
    session_id: str,
    selected_industry_id: str,
) -> dict[str, Any] | None:
    industry_id = str(selected_industry_id or "").strip()
    if not industry_id:
        return None
    try:
        from app.fastapi_routes.market_account import (
            grant_market_enterprise_entitlements_for_session,
        )

        result = await grant_market_enterprise_entitlements_for_session(session_id, industry_id)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("workspace prefs market entitlement sync failed")
        result = {"success": False, "message": str(exc)}
    if not result.get("success"):
        logger.warning(
            "workspace prefs saved while market entitlement sync failed: industry=%s message=%s",
            industry_id,
            result.get("message"),
        )
    return result


@router.get("/prefs")
async def get_workspace_prefs_endpoint(request: Request):
    """读取当前登录用户所属租户/会话的工作区偏好。"""
    try:
        user = resolve_session_user(request)
        if user is None:
            return {"success": True, "data": {}, "owner_id": None}
        owner_id = resolve_workspace_owner_id(request, user)
        prefs = get_workspace_prefs(owner_id) if owner_id else {}
        return {"success": True, "data": prefs, "owner_id": owner_id}
    except RECOVERABLE_ERRORS:
        logger.exception("get_workspace_prefs_endpoint failed")
        return {"success": True, "data": {}, "owner_id": None}


@router.patch("/prefs")
async def patch_workspace_prefs_endpoint(body: WorkspacePrefsPatch, request: Request):
    """合并更新工作区偏好（跨设备同步）。"""
    try:
        user = get_logged_in_user(request)
        owner_id = resolve_workspace_owner_id(request, user)
        if not owner_id:
            raise HTTPException(status_code=400, detail="无法解析工作区归属，请先完成企业登录")

        partial: dict[str, Any] = body.model_dump(exclude_none=True)
        selected_industry_id = str(partial.get("selected_industry_id") or "").strip()
        prefs = patch_workspace_prefs(owner_id, partial)
        if selected_industry_id:
            prefs = bind_selected_industry_for_user(
                user,
                selected_industry_id,
                industry_mod_id=str(partial.get("industry_mod_id") or "").strip(),
                owner_id=owner_id,
            ) or prefs
        market_entitlements = await _try_grant_market_entitlements(
            session_id_from_request(request),
            selected_industry_id,
        )
        return {
            "success": True,
            "data": prefs,
            "owner_id": owner_id,
            "market_entitlements": market_entitlements,
        }
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
