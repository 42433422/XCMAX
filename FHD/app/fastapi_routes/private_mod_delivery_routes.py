"""客户定制申请、验收与桌面安装路由。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.fastapi_routes.mod_store_routes import ModStoreSimpleResponse, _request_payload
from app.fastapi_routes.private_mod_delivery_context import (
    _enterprise_delivery_scope,
    _private_delivery_market_token,
    _private_mod_context,
    _private_mod_declared_nodes,
    _private_mod_items,
    _private_mod_local_rows,
    _safe_text,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mod-store", "private-delivery"])


async def _market_token(request: Request) -> str:
    return await _private_delivery_market_token(request)


@router.get("/private-delivery", response_model=ModStoreSimpleResponse)
async def mod_store_private_delivery(request: Request) -> ModStoreSimpleResponse:
    """生产员工专用：客户私有 Mod 双轨交付状态与私有更新信息。"""
    from app.application.private_mod_delivery_app import (
        HAPPY_PATH,
        STAGE_LABELS,
        STAGES,
        TRACKS,
        attach_track_nodes,
        fetch_private_mod_library,
        is_newer_version,
        load_stage_flow_from_ssot,
        overall_status,
        project_state,
        stage_label,
    )
    from app.mod_sdk.customer_delivery import delivery_for_account_custom_mod

    context = await _private_mod_context(request)
    mod_ids = context["mod_ids"]
    deliveries = {mid: delivery_for_account_custom_mod(mid) or {} for mid in mod_ids}
    runtime_ids = {d.get("runtime_mod_id") for d in deliveries.values() if d.get("runtime_mod_id")}
    local_rows = _private_mod_local_rows(mod_ids | runtime_ids)
    remote_rows: list[dict[str, Any]] = []
    remote_error = ""
    request_error = ""
    custom_requests: list[dict[str, Any]] = []
    token = ""
    try:
        token = await _market_token(request)
        if token:
            from app.application.mod_delivery_receipt_outbox import (
                retry_delivery_receipts_best_effort,
            )

            await retry_delivery_receipts_best_effort(request, token)
            remote_rows = await fetch_private_mod_library(token)
        elif mod_ids:
            remote_error = "未检测到市场登录凭证"
    except RECOVERABLE_ERRORS as exc:
        remote_error = str(exc)[:240]
        logger.warning("private Mod update check failed: %s", exc)
    if token:
        try:
            from app.application.private_mod_delivery_app import (
                custom_delivery_remote_json,
            )

            request_rows = await custom_delivery_remote_json(
                token, "/api/customer-service/custom-deliveries"
            )
            custom_requests = [
                dict(row) for row in (request_rows.get("items") or []) if isinstance(row, dict)
            ]
        except RECOVERABLE_ERRORS as exc:
            request_error = str(exc)[:240]
            logger.warning("custom delivery request sync failed: %s", exc)
    remote_by_id = {
        _safe_text(row.get("id")): row
        for row in remote_rows
        if _safe_text(row.get("id")) in mod_ids | runtime_ids
    }
    scope = _enterprise_delivery_scope(context, mod_ids)
    projects: list[dict[str, Any]] = []
    for mod_id in sorted(mod_ids):
        delivery = deliveries[mod_id]
        integrated = delivery.get("delivery_mode") == "integrated_feature"
        runtime_id = _safe_text(delivery.get("runtime_mod_id")) or mod_id
        row = local_rows.get(runtime_id, {})
        remote = remote_by_id.get(runtime_id) or remote_by_id.get(mod_id, {})
        local_version = _safe_text(row.get("version"))
        latest_version = _safe_text(remote.get("version"))
        project = project_state(
            scope,
            mod_id,
            name=_safe_text(delivery.get("customer_brand") or row.get("name") or mod_id),
            version=local_version,
        )
        modules, employees = _private_mod_items(row)
        declared = _private_mod_declared_nodes(mod_id, row)
        track_nodes = attach_track_nodes(project, declared)
        projects.append(
            {
                "mod_id": mod_id,
                "runtime_mod_id": runtime_id,
                "delivery_mode": delivery.get("delivery_mode", "private_mod"),
                "custom_features": delivery.get("custom_features", []),
                "name": _safe_text(delivery.get("customer_brand") or row.get("name") or mod_id),
                "description": _safe_text(delivery.get("notes") or row.get("description")),
                "installed": bool(row),
                "current_version": local_version,
                "latest_version": latest_version,
                "update_available": bool(
                    not integrated
                    and latest_version
                    and is_newer_version(latest_version, local_version)
                ),
                "update_source": (
                    "shared_runtime"
                    if integrated
                    else ("private_mod_sync" if remote else "unavailable")
                ),
                "business_modules": modules,
                "ai_employees": employees,
                "track_nodes": track_nodes,
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
                    "modules": {s: stage_label("modules", s) for s in STAGES},
                    "business": {s: stage_label("modules", s) for s in STAGES},
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
            "happy_path": list(HAPPY_PATH),
            "stage_flow": load_stage_flow_from_ssot(),
            "stage_labels": STAGE_LABELS,
            "update_count": sum(1 for p in projects if p["update_available"]),
            "remote_error": remote_error,
            "request_error": request_error,
            "requests": custom_requests,
            "requires_login": bool(mod_ids and not remote_rows and remote_error),
        },
    )


@router.post("/private-delivery/requests", response_model=ModStoreSimpleResponse)
async def mod_store_create_private_delivery_request(
    request: Request,
) -> ModStoreSimpleResponse:
    payload = await _request_payload(request)
    kind = _safe_text(payload.get("kind"))
    title = _safe_text(payload.get("title"))
    requirements = _safe_text(payload.get("requirements"))
    acceptance_criteria = _safe_text(payload.get("acceptance_criteria"))
    if kind not in {"module", "employee", "bundle"}:
        raise HTTPException(status_code=400, detail="kind 必须是 module、employee 或 bundle")
    if len(title) < 2 or len(requirements) < 8 or len(acceptance_criteria) < 4:
        raise HTTPException(status_code=400, detail="请完整填写需求名称、需求说明和验收标准")
    token = await _market_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录并绑定修茈市场账号")
    from app.application.private_mod_delivery_app import custom_delivery_remote_json

    try:
        data = await custom_delivery_remote_json(
            token,
            "/api/customer-service/custom-deliveries",
            method="POST",
            payload={
                "kind": kind,
                "title": title,
                "requirements": requirements,
                "acceptance_criteria": acceptance_criteria,
                "suggested_id": _safe_text(payload.get("suggested_id")) or None,
            },
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (ConnectionError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ModStoreSimpleResponse(
        success=True, message="定制需求已受理，生产员工已开始制作", data=data
    )


@router.post(
    "/private-delivery/requests/{ticket_id}/decision",
    response_model=ModStoreSimpleResponse,
)
async def mod_store_decide_private_delivery_request(
    ticket_id: int,
    request: Request,
) -> ModStoreSimpleResponse:
    payload = await _request_payload(request)
    action = _safe_text(payload.get("action"))
    note = _safe_text(payload.get("note"))
    if action not in {"accept", "rework"}:
        raise HTTPException(status_code=400, detail="action 必须是 accept 或 rework")
    if action == "rework" and len(note) < 4:
        raise HTTPException(status_code=400, detail="返工意见至少 4 个字")
    token = await _market_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录并绑定修茈市场账号")
    from app.application.private_mod_delivery_app import custom_delivery_remote_json

    try:
        data = await custom_delivery_remote_json(
            token,
            f"/api/customer-service/custom-deliveries/{int(ticket_id)}/decision",
            method="POST",
            payload={"action": action, "note": note},
        )
    except (ConnectionError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    message = (
        "已确认验收，可安装交付" if action == "accept" else "已转返工，生产员工已开始新一轮制作"
    )
    return ModStoreSimpleResponse(success=True, message=message, data=data)


@router.post(
    "/private-delivery/requests/{ticket_id}/install",
    response_model=ModStoreSimpleResponse,
)
async def mod_store_install_private_delivery_request(
    ticket_id: int,
    request: Request,
) -> ModStoreSimpleResponse:
    payload = await _request_payload(request)
    artifact_kind = _safe_text(payload.get("artifact_kind"))
    artifact_id = _safe_text(payload.get("artifact_id"))
    token = await _market_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录并绑定修茈市场账号")
    from app.application.private_mod_delivery_app import (
        install_custom_delivery_artifact,
    )

    try:
        from app.application.mod_delivery_receipt_outbox import (
            retry_delivery_receipts_best_effort,
        )
        from app.application.tenant_workspace_prefs import resolve_workspace_owner_id
        from app.infrastructure.auth.dependencies import get_logged_in_user

        owner = resolve_workspace_owner_id(request, get_logged_in_user(request))
        if not owner:
            raise HTTPException(status_code=401, detail="无法确定当前工作空间")
        data = await install_custom_delivery_artifact(
            token,
            ticket_id,
            artifact_kind,
            owner_scope=owner,
            artifact_id=artifact_id,
        )
        from app.application.delivery_entitlements import refresh_delivery_entitlements

        data["entitlements_refreshed"] = await refresh_delivery_entitlements(request, token)
        data["receipts"] = await retry_delivery_receipts_best_effort(request, token)
    except (ConnectionError, LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ModStoreSimpleResponse(
        success=True,
        message=str(data.get("message") or "定制产物已安装"),
        data=data,
    )


from app.fastapi_routes.private_mod_delivery_progress_routes import (
    router as progress_router,
)

router.include_router(progress_router)
