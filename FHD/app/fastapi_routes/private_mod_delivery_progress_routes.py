"""客户私有交付流程推进与私有 Mod 更新路由。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.fastapi_routes.mod_store_routes import (
    ModStoreInstallResult,
    ModStoreSimpleResponse,
    _request_payload,
)
from app.fastapi_routes.private_mod_delivery_context import (
    _enterprise_delivery_scope,
    _private_mod_context,
    _private_mod_local_rows,
    _safe_text,
    _schedule_delivery_outbox_push,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mod-store", "private-delivery"])


@router.post("/private-delivery/status", response_model=ModStoreSimpleResponse)
async def mod_store_private_delivery_status(request: Request) -> ModStoreSimpleResponse:
    payload = await _request_payload(request)
    mod_id = _safe_text(payload.get("mod_id"))
    track = _safe_text(payload.get("track"))
    status = _safe_text(payload.get("status"))
    node_id = _safe_text(payload.get("node_id"))
    note = _safe_text(payload.get("note") or payload.get("problem") or payload.get("description"))
    if not mod_id or not track or not status:
        raise HTTPException(status_code=400, detail="缺少 mod_id、track 或 status")
    context = await _private_mod_context(request)
    if mod_id not in context["mod_ids"]:
        raise HTTPException(status_code=403, detail="当前账号未授权该客户私有 Mod")
    # 返工必须写明问题，并走现有客服变更工单（不新造工单系统）
    rework_ticket: dict[str, Any] | None = None
    if status == "rework":
        if len(note) < 4:
            raise HTTPException(status_code=400, detail="转返工须填写问题说明（至少 4 个字）")
        try:
            uid = int(context.get("market_user_id") or 0)
        except (TypeError, ValueError):
            uid = 0
        if uid <= 0:
            raise HTTPException(status_code=401, detail="转返工须已绑定市场账号身份")
        from app.application.user_cs_change_request_app import create_change_request

        node_label = node_id or track
        try:
            rework_ticket = create_change_request(
                uid,
                change_type="bug_fix",
                title=f"定制交付返工 · {mod_id} · {node_label}",
                description=(
                    f"来源：企业端私有交付返工\n"
                    f"Mod：{mod_id}\n"
                    f"轨道：{track}\n"
                    f"节点：{node_id or '整轨'}\n"
                    f"问题：{note}"
                ),
                priority=_safe_text(payload.get("priority")) or "normal",
                username=_safe_text(context.get("username")),
                source="private_mod_rework",
            )
            ticket_no = _safe_text(rework_ticket.get("ticket_no") or rework_ticket.get("id"))
            if ticket_no:
                note = f"[客服工单 {ticket_no}] {note}"
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.application.private_mod_delivery_app import set_track_status

    local = _private_mod_local_rows({mod_id}).get(mod_id, {})
    scope_key = _enterprise_delivery_scope(context, {mod_id})
    try:
        project = set_track_status(
            scope_key,
            mod_id,
            track,
            status,
            note=note,
            name=_safe_text(local.get("name") or mod_id),
            version=_safe_text(local.get("version")),
            node_id=node_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 企业端出队 + best-effort 后台推送：进度不滞留本机等管理端手动拉
    uid = int(context.get("market_user_id") or 0)
    if uid > 0:
        try:
            from app.application.private_mod_delivery_app import export_account_state
            from app.application.xcmax_sync_app import record_change

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
            _schedule_delivery_outbox_push()
        except RECOVERABLE_ERRORS as exc:
            logger.warning("private Mod delivery sync enqueue failed user=%s: %s", uid, exc)
    from app.application.private_mod_delivery_app import overall_status

    data: dict[str, Any] = {
        "mod_id": mod_id,
        "tracks": project.get("tracks", {}),
        "overall_status": overall_status(project),
    }
    if rework_ticket:
        data["rework_ticket"] = {
            "id": _safe_text(rework_ticket.get("id")),
            "ticket_no": _safe_text(rework_ticket.get("ticket_no")),
            "status": _safe_text(rework_ticket.get("status")),
            "change_type": _safe_text(rework_ticket.get("change_type")),
            "source": "private_mod_rework",
        }
    return ModStoreSimpleResponse(
        success=True,
        message="交付状态已更新"
        + (f"；已开客服工单 {data['rework_ticket']['ticket_no']}" if rework_ticket else ""),
        data=data,
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
        from app.application.private_mod_delivery_app import update_private_mod_from_library
        from app.fastapi_routes.market_account import resolve_valid_market_access_token
        from app.infrastructure.auth.dependencies import session_id_from_request

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
