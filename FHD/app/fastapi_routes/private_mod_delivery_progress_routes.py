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
    from app.application.private_mod_delivery_app import (
        STAGES,
        TRACKS,
        account_projects,
        assert_stage_transition,
        normalize_track,
    )

    track = normalize_track(track)
    if track not in TRACKS or status not in STAGES:
        raise HTTPException(status_code=400, detail="未知交付轨道或阶段")
    scope_key = _enterprise_delivery_scope(context, {mod_id})
    prior = account_projects(scope_key, {mod_id})[0]
    track_row = (prior.get("tracks") or {}).get(track) or {}
    target_row = (track_row.get("nodes") or {}).get(node_id) or {} if node_id else track_row
    try:
        assert_stage_transition(str(target_row.get("status") or "production"), status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
        from app.application.customer_issue_intake_app import submit_private_rework
        from app.fastapi_routes.private_mod_delivery_context import (
            _private_delivery_market_token,
        )
        from app.mod_sdk.customer_delivery import delivery_for_account_custom_mod

        runtime_id = str(
            (delivery_for_account_custom_mod(mod_id) or {}).get("runtime_mod_id") or mod_id
        )
        local_row = _private_mod_local_rows({runtime_id}).get(runtime_id, {})
        try:
            rework_ticket = await submit_private_rework(
                market_user_id=uid,
                token=await _private_delivery_market_token(request),
                mod_id=mod_id,
                track=track,
                node_id=node_id,
                note=note,
                version=_safe_text(local_row.get("version")),
                username=_safe_text(context.get("username")),
            )
            note = f"[客服工单 {rework_ticket['ticket_no']}] {note}"
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except (ConnectionError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=f"返工未成功受理，可重试：{exc}") from exc
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
    expected_version = _safe_text(
        payload.get("expected_version") or payload.get("latest_version") or payload.get("version")
    )
    if not mod_id:
        raise HTTPException(status_code=400, detail="缺少 mod_id")
    context = await _private_mod_context(request)
    if mod_id not in context["mod_ids"]:
        raise HTTPException(status_code=403, detail="当前账号未授权该客户私有 Mod")
    from app.mod_sdk.customer_delivery import delivery_for_account_custom_mod

    delivery = delivery_for_account_custom_mod(mod_id) or {}
    if delivery.get("delivery_mode") == "integrated_feature":
        raise HTTPException(
            status_code=409,
            detail="该定制功能集成于共享工作区，请更新标准客户端；不安装独立客户 Mod",
        )
    from app.application.tenant_workspace_prefs import resolve_workspace_owner_id
    from app.infrastructure.auth.dependencies import get_logged_in_user

    owner_scope = resolve_workspace_owner_id(request, get_logged_in_user(request))
    if not owner_scope:
        raise HTTPException(status_code=401, detail="无法确定当前工作空间")
    try:
        from app.application.private_mod_delivery_app import (
            update_private_mod_from_library,
        )
        from app.fastapi_routes.market_account import resolve_valid_market_access_token
        from app.infrastructure.auth.dependencies import session_id_from_request

        sid = session_id_from_request(request)
        token = await resolve_valid_market_access_token(sid) if sid else ""
        if not token:
            raise PermissionError("缺少市场登录凭证，无法更新客户私有 Mod")
        data = await update_private_mod_from_library(
            _safe_text(delivery.get("runtime_mod_id")) or mod_id,
            token,
            expected_version=expected_version,
            owner_scope=owner_scope,
        )
        from app.application.mod_delivery_receipt_outbox import (
            retry_delivery_receipts_best_effort,
        )

        if data.get("success"):
            from app.application.delivery_entitlements import (
                refresh_delivery_entitlements,
            )

            data["entitlements_refreshed"] = await refresh_delivery_entitlements(request, token)
            data["receipts"] = await retry_delivery_receipts_best_effort(request, token)
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
