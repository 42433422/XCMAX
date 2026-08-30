# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.xcmax_admin")


@_facade().router.put("/admin/users/{user_id}/profile", response_model=None)
async def admin_set_user_profile(
    request: _facade().Request, user_id: int, payload: dict = _facade().Body(...)
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

    gate = _facade()._require_market_admin_session(request)
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
        merge_entitled_industries([str(x or "").strip() for x in entitled_raw or []], [])
        if entitled_provided
        else None
    )
    if not username:
        return _facade().JSONResponse(
            {"success": False, "message": "username 必填"}, status_code=422
        )
    if tier and tier not in _facade()._VALID_TIERS:
        return _facade().JSONResponse(
            {"success": False, "message": f"tier 必须是 {sorted(_facade()._VALID_TIERS)} 之一"},
            status_code=422,
        )
    norm_account_tier = None
    if account_tier:
        norm_account_tier = normalize_account_tier(account_tier)
        if norm_account_tier is None:
            return _facade().JSONResponse(
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
            user_by_market_id = db.query(User).filter(User.market_user_id == int(user_id)).first()
            user_by_username = db.query(User).filter(User.username == username).first()
            user = user_by_market_id or user_by_username
            if (
                user_by_market_id is not None
                and user_by_username is not None
                and user_by_username is not user_by_market_id
            ):
                return _facade().JSONResponse(
                    {
                        "success": False,
                        "message": "市场用户 ID 与用户名分别绑定了不同的本地资料，请先合并冲突账号",
                    },
                    status_code=409,
                )
            bound_market_user_id = (
                getattr(user_by_username, "market_user_id", None)
                if user_by_username is not None
                else None
            )
            if (
                user_by_market_id is None
                and user_by_username is not None
                and isinstance(bound_market_user_id, int)
                and bound_market_user_id != int(user_id)
            ):
                return _facade().JSONResponse(
                    {
                        "success": False,
                        "message": "该用户名已经绑定其他市场用户 ID",
                    },
                    status_code=409,
                )
            if user is None:
                user = User(
                    username=username,
                    password="",
                    role="user",
                    market_user_id=int(user_id),
                )
                db.add(user)
                db.flush()
            else:
                user.market_user_id = int(user_id)
                # 市场用户 ID 是身份，用户名只是可变资料；同步改名但不创建第二份 profile。
                user.username = username
            final_tier = (
                (tier or str(getattr(user, "tier", "") or "") or "personal").strip().lower()
            )
            if norm_account_tier is not None and (not should_have_account_tier(final_tier)):
                return _facade().JSONResponse(
                    {"success": False, "message": "账号等级（account_tier）仅企业用户可设置"},
                    status_code=422,
                )
            current_entitled = list(getattr(user, "entitled_industries", None) or [])
            final_entitled = entitled_in if entitled_in is not None else current_entitled
            if industry_id:
                if entitled_provided:
                    if not validate_industry_in_entitled(industry_id, final_entitled):
                        return _facade().JSONResponse(
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
                "market_user_id": int(user_id),
                "username": username,
                "tier": user.tier,
                "industry_id": user.industry_id,
                "account_tier": user.account_tier,
                "budget_range": user.budget_range,
                "entitled_industries": list(getattr(user, "entitled_industries", None) or []),
            }
        return {"success": True, "data": result}
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("设置用户 profile 失败: %s", exc)
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@_facade().router.get("/admin/users/profiles", response_model=None)
async def admin_list_user_profiles(request: _facade().Request):
    """返回本地所有用户的账号体系字段映射（按 username 索引）。

    前端拿到远端用户列表后，调此端点合并本地 profile。
    """
    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    try:
        from app.db.models.user import User
        from app.db.session import get_db

        with get_db() as db:
            rows = db.query(
                User.market_user_id,
                User.username,
                User.tier,
                User.industry_id,
                User.account_tier,
                User.budget_range,
                User.entitled_industries,
            ).all()
        data = {
            r[1]: {
                "market_user_id": r[0],
                "tier": r[2],
                "industry_id": r[3],
                "account_tier": r[4],
                "budget_range": r[5],
                "entitled_industries": list(r[6] or []),
            }
            for r in rows
        }
        by_market_user_id = {str(r[0]): data[r[1]] for r in rows if r[0] is not None}
        return {
            "success": True,
            "data": data,
            "by_market_user_id": by_market_user_id,
        }
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("读取用户 profile 列表失败: %s", exc)
        return _facade().JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@_facade().router.post("/admin/market/users/{user_id}/entitlements/push", response_model=None)
async def admin_force_push_user_entitlements(
    request: _facade().Request,
    user_id: int,
    payload: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """把账号权益完整快照强制推送到企业端同步链路。

    这个接口服务管理端的“账号权益”页，不进入代管会话，也不污染桌面端当前登录态。
    """
    from app.application.session_account_meta import audit_admin_action
    from app.application.xcmax_sync_app import push_outbox, record_change

    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    user_data = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    profile_data = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    wallet_data = payload.get("wallet") if isinstance(payload.get("wallet"), dict) else None
    if not isinstance(user_data, dict):
        user_data = {}
    username = str(user_data.get("username") or payload.get("username") or "").strip()
    if not username:
        return _facade().JSONResponse(
            {"success": False, "message": "username 必填"}, status_code=422
        )
    if not isinstance(profile_data, dict):
        profile_data = {}
    tier = str(profile_data.get("tier") or user_data.get("tier") or "").strip().lower()
    if tier not in _facade()._VALID_TIERS:
        tier = "enterprise" if _facade()._truthy(user_data.get("is_enterprise")) else "personal"
    industry_id = str(
        profile_data.get("industry_id") or user_data.get("industry_id") or "通用"
    ).strip()
    entitled_industries = _facade()._clean_string_list(profile_data.get("entitled_industries"))
    if industry_id and industry_id not in entitled_industries:
        entitled_industries.append(industry_id)
    snapshot = {
        "market_user_id": str(user_id),
        "username": username,
        "email": str(user_data.get("email") or payload.get("email") or "").strip(),
        "is_admin": _facade()._truthy(user_data.get("is_admin")),
        "is_enterprise": _facade()._truthy(user_data.get("is_enterprise")) or tier == "enterprise",
        "profile": {
            "username": username,
            "tier": tier,
            "industry_id": industry_id or "通用",
            "account_tier": str(profile_data.get("account_tier") or "").strip(),
            "budget_range": str(profile_data.get("budget_range") or "").strip(),
            "entitled_industries": entitled_industries,
        },
        "mod_ids": _facade()._clean_string_list(payload.get("mod_ids")),
        "wallet": wallet_data,
        "workflow_employees": payload.get("workflow_employees")
        if isinstance(payload.get("workflow_employees"), list)
        else [],
        "installed_mods": payload.get("installed_mods")
        if isinstance(payload.get("installed_mods"), list)
        else [],
        "source": "admin_entitlements_force_push",
        "meta": {
            "updated_at_ms": int(_facade().time.time() * 1000),
            "target": "enterprise",
            "push_mode": "forced",
        },
    }
    change_id = record_change("account_entitlements", str(user_id), "sync", snapshot, actor="admin")
    if change_id < 0:
        return _facade().JSONResponse(
            {"success": False, "message": "写入账号权益同步队列失败"}, status_code=500
        )
    push_result = push_outbox(remote_host=_facade().REMOTE_HOST, remote_port=_facade().REMOTE_PORT)
    if int(push_result.get("failed") or 0) > 0 or int(push_result.get("sent") or 0) <= 0:
        return _facade().JSONResponse(
            {
                "success": False,
                "message": "账号权益已写入本地队列，但推送企业端失败，请检查云端同步服务",
                "data": {"change_id": change_id, "snapshot": snapshot, "push": push_result},
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
        "data": {"change_id": change_id, "snapshot": snapshot, "push": push_result},
    }


@_facade().router.post("/admin/impersonate", response_model=None)
async def admin_start_impersonate(
    request: _facade().Request,
    body: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
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

    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    sid = _session_id_from_request(request)
    target_id = body.get("market_user_id")
    target_name = str(body.get("username") or "").strip()
    target_company = str(body.get("company") or body.get("company_brand") or "").strip()
    if target_id is None:
        return _facade().JSONResponse(
            {"success": False, "message": "market_user_id 必填"}, status_code=400
        )
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return _facade().JSONResponse(
            {"success": False, "message": "market_user_id 无效"}, status_code=400
        )
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
    audit_admin_action(request, "impersonate_start", target_user_id=target_id, detail=target_name)
    return {
        "success": True,
        "impersonating_market_user_id": target_id,
        "impersonating_username": target_name,
        "bridge_token": create_impersonation_bridge_token(sid),
    }


@_facade().router.get("/admin/market/diagnostic-terminal/commands", response_model=None)
async def admin_list_diagnostic_terminal_commands(request: _facade().Request):
    """List the allow-listed read-only diagnostic commands from MODstore."""

    return await _facade()._market_admin_proxy(
        request,
        "GET",
        "/api/admin/diagnostic-terminal/commands",
    )


@_facade().router.post("/admin/market/diagnostic-terminal/execute", response_model=None)
async def admin_execute_diagnostic_terminal_command(
    request: _facade().Request,
    payload: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    """Execute one allow-listed read-only diagnostic command."""

    return await _facade()._market_admin_proxy(
        request,
        "POST",
        "/api/admin/diagnostic-terminal/execute",
        json_body=payload,
    )
