"""客户私有 Mod 双轨交付 / 私有更新 API（从 mod_store_routes 拆出以降债务）。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.fastapi_routes.mod_store_routes import (
    ModStoreInstallResult,
    ModStoreSimpleResponse,
    _request_payload,
    _safe_text,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mod-store"])

async def _private_mod_context(request: Request) -> dict[str, Any]:
    """读取当前账号可见的客户私有 Mod，严格复用企业 entitlement。"""
    from app.enterprise.mod_entitlements import (
        enterprise_mod_filter_active,
        get_cached_entitled_client_mod_ids,
        get_cached_market_identity,
        sync_entitlements_from_request,
    )

    if enterprise_mod_filter_active():
        await sync_entitlements_from_request(request)
        entitled = get_cached_entitled_client_mod_ids() or set()
    else:
        # 非企业开发环境只从本地交付清单暴露客户 Mod，生产企业版仍以 entitlement 为准。
        from app.mod_sdk.customer_delivery import list_customer_deliveries

        entitled = {
            str(row.get("legacy_mod_id") or "").strip()
            for row in list_customer_deliveries()
            if str(row.get("legacy_mod_id") or "").strip()
        }
    market_user_id, username = get_cached_market_identity()
    return {
        "mod_ids": {str(x).strip() for x in entitled if str(x).strip()},
        "market_user_id": market_user_id,
        "username": username,
    }


def _private_mod_local_rows(mod_ids: set[str]) -> dict[str, dict[str, Any]]:
    from app.infrastructure.mods.mod_manager import get_mod_manager

    rows: dict[str, dict[str, Any]] = {}
    for row in get_mod_manager().list_all_mods():
        mid = str(row.get("id") or "").strip()
        if mid in mod_ids:
            rows[mid] = row
    return rows


def _private_mod_items(row: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    modules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in row.get("menu") or []:
        if not isinstance(item, dict):
            continue
        label = _safe_text(item.get("label") or item.get("name") or item.get("id"))
        if label and label not in seen:
            seen.add(label)
            modules.append({"id": _safe_text(item.get("id") or label), "label": label})
    for item in row.get("menu_overrides") or []:
        if not isinstance(item, dict) or item.get("hidden"):
            continue
        label = _safe_text(item.get("label") or item.get("key"))
        if label and label not in seen:
            seen.add(label)
            modules.append({"id": _safe_text(item.get("key") or label), "label": label})
    employees = [
        {
            "id": _safe_text(item.get("id")),
            "label": _safe_text(item.get("label") or item.get("id")),
            "summary": _safe_text(item.get("panel_summary") or item.get("summary")),
        }
        for item in (row.get("workflow_employees") or [])
        if isinstance(item, dict) and _safe_text(item.get("id") or item.get("label"))
    ]
    return modules, employees


@router.get("/private-delivery", response_model=ModStoreSimpleResponse)
async def mod_store_private_delivery(request: Request) -> ModStoreSimpleResponse:
    """生产员工专用：客户私有 Mod 双轨交付状态与私有更新信息。"""
    from app.mod_sdk.customer_delivery import delivery_for_account_custom_mod
    from app.services.private_mod_delivery import (
        STAGES,
        STAGE_LABELS,
        TRACKS,
        account_scope,
        fetch_private_mod_library,
        is_newer_version,
        overall_status,
        project_state,
        stage_label,
    )

    context = await _private_mod_context(request)
    mod_ids = context["mod_ids"]
    local_rows = _private_mod_local_rows(mod_ids)
    remote_rows: list[dict[str, Any]] = []
    remote_error = ""
    try:
        from app.fastapi_routes.market_account import resolve_valid_market_access_token
        from app.infrastructure.auth.dependencies import session_id_from_request

        sid = session_id_from_request(request)
        token = await resolve_valid_market_access_token(sid) if sid else ""
        if token:
            remote_rows = await fetch_private_mod_library(token)
        elif mod_ids:
            remote_error = "未检测到市场登录凭证"
    except RECOVERABLE_ERRORS as exc:
        remote_error = str(exc)[:240]
        logger.warning("private Mod update check failed: %s", exc)
    remote_by_id = {
        _safe_text(row.get("id")): row
        for row in remote_rows
        if _safe_text(row.get("id")) in mod_ids
    }
    scope = account_scope(context.get("market_user_id"), context.get("username"))
    projects: list[dict[str, Any]] = []
    for mod_id in sorted(mod_ids):
        row = local_rows.get(mod_id, {})
        remote = remote_by_id.get(mod_id, {})
        delivery = delivery_for_account_custom_mod(mod_id)
        local_version = _safe_text(row.get("version"))
        latest_version = _safe_text(remote.get("version"))
        project = project_state(
            scope,
            mod_id,
            name=_safe_text(row.get("name") or (delivery or {}).get("customer_brand") or mod_id),
            version=local_version,
        )
        modules, employees = _private_mod_items(row)
        projects.append(
            {
                "mod_id": mod_id,
                "name": _safe_text(row.get("name") or (delivery or {}).get("customer_brand") or mod_id),
                "description": _safe_text(row.get("description") or (delivery or {}).get("notes")),
                "installed": bool(row),
                "current_version": local_version,
                "latest_version": latest_version,
                "update_available": bool(latest_version and is_newer_version(latest_version, local_version)),
                "update_source": "private_mod_sync" if remote else "unavailable",
                "business_modules": modules,
                "ai_employees": employees,
                "tracks": project.get("tracks", {}),
                "overall_status": overall_status(project),
                "overall_label": {
                    "production": "制作中",
                    "testing": "测试中",
                    "rework": "返工中",
                    "acceptance": "验收中",
                    "partial": "部分交付",
                    "delivered": "私有 Mod 已交付",
                }.get(overall_status(project), "制作中"),
                "stage_labels": {
                    "business": {s: stage_label("business", s) for s in STAGES},
                    "employees": {s: stage_label("employees", s) for s in STAGES},
                },
            }
        )
    return ModStoreSimpleResponse(
        success=True,
        data={
            "projects": projects,
            "tracks": TRACKS,
            "stages": STAGES,
            "stage_labels": STAGE_LABELS,
            "update_count": sum(1 for p in projects if p["update_available"]),
            "remote_error": remote_error,
            "requires_login": bool(mod_ids and not remote_rows and remote_error),
        },
    )


@router.post("/private-delivery/status", response_model=ModStoreSimpleResponse)
async def mod_store_private_delivery_status(request: Request) -> ModStoreSimpleResponse:
    payload = await _request_payload(request)
    mod_id = _safe_text(payload.get("mod_id"))
    track = _safe_text(payload.get("track"))
    status = _safe_text(payload.get("status"))
    if not mod_id or not track or not status:
        raise HTTPException(status_code=400, detail="缺少 mod_id、track 或 status")
    context = await _private_mod_context(request)
    if mod_id not in context["mod_ids"]:
        raise HTTPException(status_code=403, detail="当前账号未授权该客户私有 Mod")
    from app.services.private_mod_delivery import account_scope, set_track_status

    local = _private_mod_local_rows({mod_id}).get(mod_id, {})
    scope_key = account_scope(context.get("market_user_id"), context.get("username"))
    try:
        project = set_track_status(
            scope_key,
            mod_id,
            track,
            status,
            note=_safe_text(payload.get("note")),
            name=_safe_text(local.get("name") or mod_id),
            version=_safe_text(local.get("version")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    market_user_id = context.get("market_user_id")
    try:
        uid = int(market_user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid > 0:
        try:
            from app.application.xcmax_sync_app import record_change
            from app.services.private_mod_delivery import export_account_state

            record_change(
                "private_mod_delivery",
                str(uid),
                "update",
                {
                    "market_user_id": str(uid),
                    "username": _safe_text(context.get("username")),
                    **export_account_state(scope_key),
                },
                actor="customer",
            )
        except RECOVERABLE_ERRORS as exc:
            logger.warning("private Mod delivery sync enqueue failed user=%s: %s", uid, exc)
    from app.services.private_mod_delivery import overall_status

    return ModStoreSimpleResponse(
        success=True,
        message="交付状态已更新",
        data={"mod_id": mod_id, "tracks": project.get("tracks", {}), "overall_status": overall_status(project)},
    )


@router.post("/private-mod/update", response_model=ModStoreInstallResult)
async def mod_store_private_mod_update(request: Request) -> ModStoreInstallResult:
    payload = await _request_payload(request)
    mod_id = _safe_text(payload.get("mod_id"))
    expected_version = _safe_text(payload.get("latest_version") or payload.get("version"))
    if not mod_id:
        raise HTTPException(status_code=400, detail="缺少 mod_id")
    context = await _private_mod_context(request)
    if mod_id not in context["mod_ids"]:
        raise HTTPException(status_code=403, detail="当前账号未授权该客户私有 Mod")
    try:
        from app.fastapi_routes.market_account import resolve_valid_market_access_token
        from app.infrastructure.auth.dependencies import session_id_from_request
        from app.services.private_mod_delivery import update_private_mod_from_library

        sid = session_id_from_request(request)
        token = await resolve_valid_market_access_token(sid) if sid else ""
        if not token:
            raise PermissionError("缺少市场登录凭证，无法更新客户私有 Mod")
        data = await update_private_mod_from_library(
            mod_id,
            token,
            expected_version=expected_version,
        )
        return ModStoreInstallResult(
            success=bool(data.get("success")),
            message=str(data.get("message") or "私有 Mod 更新完成"),
            data=data,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


