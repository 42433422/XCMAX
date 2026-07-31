"""管理端客户私有 Mod 交付只读 API（从 xcmax_admin 拆出以降债务）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.xcmax_admin import (
    _clean_string_list,
    _market_admin_proxy,
    _require_market_admin_session,
)

router = APIRouter(tags=["xcmax-admin"])

@router.get("/admin/market/users/{user_id}/private-delivery", response_model=None)
async def admin_get_user_private_delivery(request: Request, user_id: int):
    """管理端只读查看客户私有 Mod 的双轨交付状态与确认/返工记录。"""
    gate = _require_market_admin_session(request)
    if gate is not None:
        return gate
    from app.application.private_mod_delivery import (
        STAGE_LABELS,
        STAGES,
        TRACKS,
        account_projects,
        account_scope,
        overall_status,
        stage_label,
    )
    from app.mod_sdk.customer_delivery import delivery_for_account_custom_mod

    upstream = await _market_admin_proxy(request, "GET", f"/api/admin/users/{user_id}/mods")
    if isinstance(upstream, JSONResponse):
        return upstream
    raw_data = upstream.get("data") if isinstance(upstream, dict) else {}
    raw_mod_ids = (
        upstream.get("mod_ids") if isinstance(upstream, dict) else None
    ) or (raw_data.get("mod_ids") if isinstance(raw_data, dict) else None)
    mod_ids = _clean_string_list(raw_mod_ids)
    names: dict[str, str] = {}
    for mod_id in mod_ids:
        delivery = delivery_for_account_custom_mod(mod_id)
        if delivery:
            names[mod_id] = str(
                delivery.get("customer_brand") or delivery.get("customer_name") or mod_id
            ).strip()

    projects = []
    for project in account_projects(account_scope(user_id), mod_ids, names=names):
        status = overall_status(project)
        projects.append(
            {
                **project,
                "name": str(project.get("name") or names.get(project.get("mod_id"), project.get("mod_id"))),
                "overall_status": status,
                "overall_label": {
                    "production": "制作中",
                    "testing": "测试中",
                    "rework": "返工中",
                    "acceptance": "验收中",
                    "partial": "部分交付",
                    "delivered": "私有 Mod 已交付",
                }.get(status, "制作中"),
                "stage_labels": {
                    track: {stage: stage_label(track, stage) for stage in STAGES}
                    for track in TRACKS
                },
            }
        )
    return {
        "success": True,
        "data": {
            "market_user_id": user_id,
            "projects": projects,
            "tracks": TRACKS,
            "stages": STAGES,
            "stage_labels": STAGE_LABELS,
            "read_only": True,
        },
    }

