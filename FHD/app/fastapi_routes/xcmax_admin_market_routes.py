"""XCmax admin market routes."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.xcmax_admin_patch as _p

logger = logging.getLogger(__name__)
router = APIRouter()

_VALID_TIERS = {"personal", "enterprise", "admin"}
@router.get("/admin/market/users", response_model=None)
async def admin_list_market_users(request: Request):
    return await _p._market_admin_proxy(request, "GET", "/api/admin/users")

@router.post("/admin/market/users", response_model=None)
async def admin_create_market_user(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
):
    from app.application.session_account_meta import audit_admin_action
    from app.fastapi_routes.market_account import register_market_user

    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate

    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    email = str(payload.get("email") or "").strip()
    verification_code = str(payload.get("verification_code") or payload.get("code") or "").strip()
    if not username or not password:
        return JSONResponse(
            {"success": False, "message": "username、password 必填"},
            status_code=422,
        )
    if len(password) < 6:
        return JSONResponse(
            {"success": False, "message": "password 至少 6 位"},
            status_code=422,
        )
    if not email:
        email = f"{username.lower()}@xcagi.local"

    result = await register_market_user(username, password, email, verification_code)
    if not result.get("success"):
        return JSONResponse(
            {
                "success": False,
                "message": result.get("message") or "创建账号失败",
                "data": result.get("raw"),
            },
            status_code=400,
        )

    audit_admin_action(
        request,
        "create_market_user",
        target_user_id=result.get("market_user_id"),
        detail=f"username={username}",
    )
    return {
        "success": True,
        "data": {
            "market_user_id": result.get("market_user_id"),
            "username": username,
            "email": email,
            "market_base_url": result.get("market_base_url"),
            "raw": result.get("raw"),
        },
    }

@router.get("/admin/market/assignable-mods", response_model=None)
async def admin_list_assignable_mods(request: Request):
    return await _p._market_admin_proxy(request, "GET", "/api/admin/enterprise/assignable-mods")

@router.get("/admin/market/wallets", response_model=None)
async def admin_list_wallets(request: Request):
    """代理远端 ``/api/admin/wallets``，返回所有用户钱包余额。

    远端返回 ``{items: [{id, user_id, balance, updated_at}], total}``。
    """
    limit = request.query_params.get("limit", "500")
    offset = request.query_params.get("offset", "0")
    return await _p._market_admin_proxy(
        request, "GET", f"/api/admin/wallets?limit={limit}&offset={offset}"
    )

@router.post("/admin/market/users/{user_id}/wallet/credit", response_model=None)
async def admin_credit_user_wallet(
    request: Request,
    user_id: int,
    payload: dict[str, Any] = Body(default_factory=dict),
):
    from app.application.session_account_meta import audit_admin_action

    try:
        amount = float(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return JSONResponse(
            {"success": False, "message": "加款金额必须大于 0"},
            status_code=422,
        )
    description = str(payload.get("description") or "").strip() or "后台加款"
    out = await _p._market_admin_proxy(
        request,
        "POST",
        f"/api/admin/users/{user_id}/wallet/credit",
        json_body={"amount": amount, "description": description},
    )
    audit_admin_action(
        request,
        "credit_user_wallet",
        target_user_id=user_id,
        detail=f"amount={amount}",
    )
    return out

@router.get("/admin/market/users/{user_id}/mods", response_model=None)
async def admin_list_user_mods(request: Request, user_id: int):
    return await _p._market_admin_proxy(request, "GET", f"/api/admin/users/{user_id}/mods")

@router.post("/admin/market/users/{user_id}/mods/{mod_id}", response_model=None)
async def admin_bind_user_mod(request: Request, user_id: int, mod_id: str):
    from app.application.session_account_meta import audit_admin_action

    out = await _p._market_admin_proxy(request, "POST", f"/api/admin/users/{user_id}/mods/{mod_id}")
    audit_admin_action(request, "bind_user_mod", target_user_id=user_id, mod_id=mod_id)
    return out

@router.delete("/admin/market/users/{user_id}/mods/{mod_id}", response_model=None)
async def admin_unbind_user_mod(request: Request, user_id: int, mod_id: str):
    from app.application.session_account_meta import audit_admin_action

    out = await _p._market_admin_proxy(request, "DELETE", f"/api/admin/users/{user_id}/mods/{mod_id}")
    audit_admin_action(request, "unbind_user_mod", target_user_id=user_id, mod_id=mod_id)
    return out

@router.put("/admin/market/users/{user_id}/admin", response_model=None)
async def admin_set_user_admin(
    request: Request,
    user_id: int,
    is_admin: bool = Query(...),
):
    return await _p._market_admin_proxy(
        request,
        "PUT",
        f"/api/admin/users/{user_id}/admin?is_admin={'true' if is_admin else 'false'}",
    )

@router.put("/admin/market/users/{user_id}/enterprise", response_model=None)
async def admin_set_user_enterprise(
    request: Request,
    user_id: int,
    is_enterprise: bool = Query(...),
):
    return await _p._market_admin_proxy(
        request,
        "PUT",
        f"/api/admin/users/{user_id}/enterprise?is_enterprise={'true' if is_enterprise else 'false'}",
    )


_VALID_TIERS = {"personal", "enterprise", "admin"}

@router.put("/admin/users/{user_id}/profile", response_model=None)
async def admin_set_user_profile(
    request: Request,
    user_id: int,
    payload: dict = Body(...),
):
    """设置用户账号体系字段（本地 User 表持久化）。

    body: {
        username: str,
        tier?: personal|enterprise|admin,
        industry_id?: str,
        account_tier?: normal|pro|max|ultra,   # 仅 enterprise 可设
        budget_range?: str,
        entitled_industries?: list[str],
    }
    校验：account_tier 仅企业可设；industry_id 必须 ∈ entitled_industries（显式提供时）。
    """
    from app.application.account_tier_derivation import (
        VALID_ACCOUNT_TIERS,
        normalize_account_tier,
        should_have_account_tier,
    )
    from app.application.entitled_industries_init import (
        merge_entitled_industries,
        validate_industry_in_entitled,
    )

    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    username = str(payload.get("username") or "").strip()
    tier = str(payload.get("tier") or "").strip()
    industry_id = str(payload.get("industry_id") or "").strip()
    account_tier = str(payload.get("account_tier") or "").strip()
    budget_range = str(payload.get("budget_range") or "").strip()
    entitled_raw = payload.get("entitled_industries")
    entitled_provided = isinstance(entitled_raw, list)
    entitled_in = (
        merge_entitled_industries([str(x or "").strip() for x in entitled_raw], [])
        if entitled_provided
        else None
    )

    if not username:
        return JSONResponse({"success": False, "message": "username 必填"}, status_code=422)
    if tier and tier not in _VALID_TIERS:
        return JSONResponse(
            {"success": False, "message": f"tier 必须是 {sorted(_VALID_TIERS)} 之一"},
            status_code=422,
        )
    norm_account_tier = None
    if account_tier:
        norm_account_tier = normalize_account_tier(account_tier)
        if norm_account_tier is None:
            return JSONResponse(
                {
                    "success": False,
                    "message": f"account_tier 必须是 {sorted(VALID_ACCOUNT_TIERS)} 之一",
                },
                status_code=422,
            )
    try:
        from app.db.models.user import User
        from app.db.session import get_db

        with get_db() as db:
            user = db.query(User).filter(User.username == username).first()
            if user is None:
                user = User(username=username, password="", role="user")
                db.add(user)
                db.flush()

            final_tier = (
                (tier or str(getattr(user, "tier", "") or "") or "personal").strip().lower()
            )
            # account_tier 仅企业可设
            if norm_account_tier is not None and not should_have_account_tier(final_tier):
                return JSONResponse(
                    {"success": False, "message": "账号等级（account_tier）仅企业用户可设置"},
                    status_code=422,
                )

            # 计算最终 entitled 集合 + industry_id 校验
            current_entitled = list(getattr(user, "entitled_industries", None) or [])
            final_entitled = entitled_in if entitled_in is not None else current_entitled
            if industry_id:
                if entitled_provided:
                    if not validate_industry_in_entitled(industry_id, final_entitled):
                        return JSONResponse(
                            {
                                "success": False,
                                "message": "industry_id 必须在 entitled_industries 内",
                            },
                            status_code=422,
                        )
                else:
                    final_entitled = merge_entitled_industries(
                        final_entitled or ["通用"], [industry_id]
                    )

            if tier:
                user.tier = tier
            if industry_id:
                user.industry_id = industry_id
            if budget_range:
                user.budget_range = budget_range
            if norm_account_tier is not None:
                user.account_tier = norm_account_tier
            elif not should_have_account_tier(final_tier):
                user.account_tier = None
            if entitled_in is not None or industry_id:
                user.entitled_industries = final_entitled

            db.commit()
            result = {
                "username": username,
                "tier": user.tier,
                "industry_id": user.industry_id,
                "account_tier": user.account_tier,
                "budget_range": user.budget_range,
                "entitled_industries": list(getattr(user, "entitled_industries", None) or []),
            }
        return {"success": True, "data": result}
    except _p.RECOVERABLE_ERRORS as exc:
        logger.warning("设置用户 profile 失败: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

@router.get("/admin/users/profiles", response_model=None)
async def admin_list_user_profiles(request: Request):
    """返回本地所有用户的账号体系字段映射（按 username 索引）。

    前端拿到远端用户列表后，调此端点合并本地 profile。
    """
    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    try:
        from app.db.models.user import User
        from app.db.session import get_db

        with get_db() as db:
            rows = db.query(
                User.username,
                User.tier,
                User.industry_id,
                User.account_tier,
                User.budget_range,
                User.entitled_industries,
            ).all()
        data = {
            r[0]: {
                "tier": r[1],
                "industry_id": r[2],
                "account_tier": r[3],
                "budget_range": r[4],
                "entitled_industries": list(r[5] or []),
            }
            for r in rows
        }
        return {"success": True, "data": data}
    except _p.RECOVERABLE_ERRORS as exc:
        logger.warning("读取用户 profile 列表失败: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

@router.post("/admin/market/users/{user_id}/entitlements/push", response_model=None)
async def admin_force_push_user_entitlements(
    request: Request,
    user_id: int,
    payload: dict[str, Any] = Body(default_factory=dict),
):
    """把账号权益完整快照强制推送到企业端同步链路。

    这个接口服务管理端的“账号权益”页，不进入代管会话，也不污染桌面端当前登录态。
    """
    from app.application.session_account_meta import audit_admin_action
    from app.application.xcmax_sync_app import push_outbox, record_change

    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate

    user_data = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    profile_data = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    wallet_data = payload.get("wallet") if isinstance(payload.get("wallet"), dict) else None

    username = str(user_data.get("username") or payload.get("username") or "").strip()
    if not username:
        return JSONResponse({"success": False, "message": "username 必填"}, status_code=422)

    tier = str(profile_data.get("tier") or user_data.get("tier") or "").strip().lower()
    if tier not in _VALID_TIERS:
        tier = "enterprise" if _p._truthy(user_data.get("is_enterprise")) else "personal"
    industry_id = str(
        profile_data.get("industry_id") or user_data.get("industry_id") or "通用"
    ).strip()
    entitled_industries = _p._clean_string_list(profile_data.get("entitled_industries"))
    if industry_id and industry_id not in entitled_industries:
        entitled_industries.append(industry_id)

    snapshot = {
        "market_user_id": str(user_id),
        "username": username,
        "email": str(user_data.get("email") or payload.get("email") or "").strip(),
        "is_admin": _p._truthy(user_data.get("is_admin")),
        "is_enterprise": _p._truthy(user_data.get("is_enterprise")) or tier == "enterprise",
        "profile": {
            "username": username,
            "tier": tier,
            "industry_id": industry_id or "通用",
            "account_tier": str(profile_data.get("account_tier") or "").strip(),
            "budget_range": str(profile_data.get("budget_range") or "").strip(),
            "entitled_industries": entitled_industries,
        },
        "mod_ids": _p._clean_string_list(payload.get("mod_ids")),
        "wallet": wallet_data,
        "workflow_employees": payload.get("workflow_employees")
        if isinstance(payload.get("workflow_employees"), list)
        else [],
        "installed_mods": payload.get("installed_mods")
        if isinstance(payload.get("installed_mods"), list)
        else [],
        "source": "admin_entitlements_force_push",
        "meta": {
            "updated_at_ms": int(time.time() * 1000),
            "target": "enterprise",
            "push_mode": "forced",
        },
    }

    change_id = record_change(
        "account_entitlements",
        str(user_id),
        "sync",
        snapshot,
        actor="admin",
    )
    if change_id < 0:
        return JSONResponse(
            {"success": False, "message": "写入账号权益同步队列失败"},
            status_code=500,
        )

    push_result = push_outbox(remote_host=_p.REMOTE_HOST, remote_port=_p.REMOTE_PORT)
    if int(push_result.get("failed") or 0) > 0 or int(push_result.get("sent") or 0) <= 0:
        return JSONResponse(
            {
                "success": False,
                "message": "账号权益已写入本地队列，但推送企业端失败，请检查云端同步服务",
                "data": {
                    "change_id": change_id,
                    "snapshot": snapshot,
                    "push": push_result,
                },
            },
            status_code=502,
        )
    audit_admin_action(
        request,
        "force_push_user_entitlements",
        target_user_id=user_id,
        detail=f"username={username}; change_id={change_id}; sent={push_result.get('sent')}",
    )
    return {
        "success": True,
        "data": {
            "change_id": change_id,
            "snapshot": snapshot,
            "push": push_result,
        },
    }

@router.get("/admin/wechat/groups", response_model=None)
async def admin_list_wechat_groups(
    request: Request,
    keyword: str = Query(default=""),
    limit: int = Query(default=80, ge=1, le=200),
):
    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    try:
        from app.application.wechat_group_customer_app import list_group_contacts

        rows = list_group_contacts(keyword=keyword or None, limit=limit)
        return {"success": True, "data": rows, "total": len(rows)}
    except _p.RECOVERABLE_ERRORS as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

@router.get("/admin/market/users/{user_id}/wechat-customers", response_model=None)
async def admin_list_user_wechat_customers(request: Request, user_id: int):
    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    try:
        from app.application.wechat_group_customer_app import get_bindings_for_user

        return {"success": True, "data": get_bindings_for_user(user_id)}
    except _p.RECOVERABLE_ERRORS as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

@router.put("/admin/market/users/{user_id}/wechat-customers", response_model=None)
async def admin_save_user_wechat_customers(
    request: Request,
    user_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
):
    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    try:
        from app.application.wechat_group_customer_app import save_bindings_for_user

        ids = body.get("contact_ids") or body.get("wechat_contact_ids") or []
        if not isinstance(ids, list):
            ids = []
        result = save_bindings_for_user(user_id, ids)
        return result
    except _p.RECOVERABLE_ERRORS as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

@router.post("/admin/impersonate", response_model=None)
async def admin_start_impersonate(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    from app.application.impersonation_bridge import create_impersonation_bridge_token
    from app.application.session_account_meta import (
        audit_admin_action,
        load_session_account_meta,
        normalize_account_kind,
        persist_session_account_meta,
    )
    from app.enterprise.mod_entitlements import (
        persist_entitlements_to_session_row,
        refresh_session_entitlements_from_market,
        reload_enterprise_mods_after_login,
    )
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.fastapi_routes.market_account import resolve_valid_market_access_token

    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    sid = _session_id_from_request(request)
    target_id = body.get("market_user_id")
    target_name = str(body.get("username") or "").strip()
    target_company = str(body.get("company") or body.get("company_brand") or "").strip()
    if target_id is None:
        return JSONResponse({"success": False, "message": "market_user_id 必填"}, status_code=400)
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return JSONResponse({"success": False, "message": "market_user_id 无效"}, status_code=400)

    meta = load_session_account_meta(sid) or {}
    persist_session_account_meta(
        sid,
        account_kind=normalize_account_kind(meta.get("account_kind"), default="admin"),
        company_brand=target_company or str(meta.get("company_brand") or ""),
        market_user_id=meta.get("market_user_id"),
        market_is_admin=True,
        market_is_enterprise=bool(meta.get("market_is_enterprise")),
        impersonating_market_user_id=target_id,
        impersonating_username=target_name,
    )
    tok = await resolve_valid_market_access_token(sid)
    if tok:
        client_ids = await refresh_session_entitlements_from_market(
            market_token=tok,
            market_user_id=meta.get("market_user_id"),
            market_username=target_name,
            session_id=sid,
        )
        persist_entitlements_to_session_row(sid, client_ids)
        await reload_enterprise_mods_after_login()
    audit_admin_action(
        request,
        "impersonate_start",
        target_user_id=target_id,
        detail=target_name,
    )
    return {
        "success": True,
        "impersonating_market_user_id": target_id,
        "impersonating_username": target_name,
        "bridge_token": create_impersonation_bridge_token(sid),
    }

@router.post("/admin/impersonate/activate-enterprise", response_model=None)
async def admin_activate_enterprise_impersonation(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    from app.application.impersonation_bridge import (
        consume_impersonation_bridge_token,
        mirror_admin_impersonation_to_enterprise_session,
    )
    from app.config import Config

    token = str(body.get("bridge_token") or body.get("token") or "").strip()
    if not token:
        return JSONResponse({"success": False, "message": "bridge_token 必填"}, status_code=400)
    admin_sid = consume_impersonation_bridge_token(token)
    if not admin_sid:
        return JSONResponse(
            {"success": False, "message": "bridge_token 无效或已过期"}, status_code=400
        )
    enterprise_sid = str(
        body.get("enterprise_session_id")
        or request.cookies.get(getattr(Config, "SESSION_COOKIE_NAME", "session_id"))
        or ""
    ).strip()
    try:
        sid = mirror_admin_impersonation_to_enterprise_session(admin_sid, enterprise_sid or None)
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    return {"success": True, "session_id": sid}

@router.post("/admin/impersonate/end", response_model=None)
async def admin_end_impersonate(request: Request):
    from app.application.session_account_meta import (
        audit_admin_action,
        clear_impersonation,
        load_session_account_meta,
    )
    from app.enterprise.mod_entitlements import (
        persist_entitlements_to_session_row,
        refresh_session_entitlements_from_market,
        reload_enterprise_mods_after_login,
    )
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.fastapi_routes.market_account import resolve_valid_market_access_token

    gate = _p._require_market_admin_session(request)
    if gate is not None:
        return gate
    sid = _session_id_from_request(request)
    meta = load_session_account_meta(sid) or {}
    clear_impersonation(sid)
    tok = await resolve_valid_market_access_token(sid)
    if tok:
        client_ids = await refresh_session_entitlements_from_market(
            market_token=tok,
            market_user_id=meta.get("market_user_id"),
            session_id=sid,
        )
        persist_entitlements_to_session_row(sid, client_ids)
        await reload_enterprise_mods_after_login()
    audit_admin_action(request, "impersonate_end")
    return {"success": True}
