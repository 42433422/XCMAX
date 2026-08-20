# mypy: disable-error-code="misc, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.mobile_api_extensions")


@_facade().extension_router.get("/admin/home")
async def mobile_admin_home(
    request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)
):
    meta, err = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    (
        market_profiles,
        market_connected,
        market_error,
    ) = await _facade()._load_market_ai_employee_profile_index()
    employees = _facade()._admin_employee_items(market_profiles, market_connected=market_connected)
    uid = _facade()._mobile_request_user_id(request, user)
    im_summary: dict[str, dict[str, _facade().Any]] = {}
    if uid > 0 and employees:
        try:
            from app.application.im_app_service import ImApplicationService
            from app.db import SessionLocal

            db = SessionLocal()
            try:
                im_summary = ImApplicationService(db).employee_im_summary(uid, employees)
            finally:
                db.close()
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("employee_im_summary skipped", exc_info=True)
    employees = _facade()._admin_employee_items(
        market_profiles, market_connected=market_connected, im_summary=im_summary
    )
    return _facade().format_mobile_response(
        data={
            "account_kind": meta.get("account_kind") or "admin",
            "employees": employees,
            "employee_count": len(employees),
            "features": _facade().ADMIN_MOBILE_FEATURES,
            "feature_count": len(_facade().ADMIN_MOBILE_FEATURES),
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
        }
    )


@_facade().extension_router.get("/circle/posts")
async def mobile_ai_circle_posts(
    limit: int = _facade().Query(default=50, ge=1, le=100),
    user=_facade().Depends(_facade().get_mobile_user),
):
    if user is None:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    from app.application.ai_circle_service import list_posts

    try:
        import importlib

        employee_circle_sync = importlib.import_module("app.application.employee_circle_sync")
        await employee_circle_sync.sync_modstore_reports()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.warning("circle: modstore report sync skipped", exc_info=True)
    uid, _, _ = _facade()._ai_circle_user(user)
    posts = list_posts(user_id=uid, limit=limit)
    profiles = _facade()._ai_circle_employee_profiles()
    for post in posts:
        profile = profiles.get(str(post.get("employee_id") or ""))
        if profile:
            post["author_name"] = profile["name"]
            post["author_avatar"] = profile["avatar"] or post.get("author_avatar")
    return _facade().format_mobile_response(data={"items": posts, "count": len(posts)})


@_facade().extension_router.post("/circle/posts")
async def mobile_ai_circle_create_post(
    body: _facade().AiCirclePostBody, user=_facade().Depends(_facade().get_mobile_user)
):
    if user is None:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    from app.application.ai_circle_service import create_user_post

    uid, name, avatar = _facade()._ai_circle_user(user)
    try:
        post_id = create_user_post(user_id=uid, author_name=name, avatar=avatar, body=body.body)
        return _facade().format_mobile_response(data={"id": post_id}, message="发布成功")
    except ValueError:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "动态内容无效", success=False, code=400),
            status_code=400,
        )


@_facade().extension_router.post("/circle/posts/{post_id}/like")
async def mobile_ai_circle_toggle_like(
    post_id: int, user=_facade().Depends(_facade().get_mobile_user)
):
    if user is None:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    from app.application.ai_circle_service import toggle_like

    uid, _, _ = _facade()._ai_circle_user(user)
    try:
        liked = toggle_like(post_id=post_id, user_id=uid)
        return _facade().format_mobile_response(data={"liked": liked})
    except LookupError:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "动态不存在", success=False, code=404),
            status_code=404,
        )


@_facade().extension_router.post("/circle/posts/{post_id}/comments")
async def mobile_ai_circle_add_comment(
    post_id: int,
    body: _facade().AiCircleCommentBody,
    user=_facade().Depends(_facade().get_mobile_user),
):
    if user is None:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    from app.application.ai_circle_service import add_comment

    uid, name, _ = _facade()._ai_circle_user(user)
    try:
        comment_id = add_comment(post_id=post_id, user_id=uid, author_name=name, body=body.body)
        return _facade().format_mobile_response(data={"id": comment_id}, message="评论成功")
    except ValueError:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "评论内容无效", success=False, code=400),
            status_code=400,
        )
    except LookupError:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "动态不存在", success=False, code=404),
            status_code=404,
        )


@_facade().extension_router.get("/mods")
async def mobile_mods_summary(user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    (
        market_profiles,
        market_connected,
        market_error,
    ) = await _facade()._load_market_ai_employee_profile_index()
    return _facade().format_mobile_response(
        data={
            "items": _facade()._mobile_mod_items(
                market_profiles, market_connected=market_connected
            ),
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
        }
    )


@_facade().extension_router.get("/platform-shell")
async def mobile_platform_shell(user=_facade().Depends(_facade().get_mobile_user)):
    if user is None:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    installed = [m["id"] for m in _facade()._mobile_mod_items()]
    from app.mod_sdk.platform_shell import build_platform_shell_payload

    return _facade().format_mobile_response(data=build_platform_shell_payload(installed))


@_facade().extension_router.get("/onboarding/industries", response_model=dict[str, _facade().Any])
async def mobile_onboarding_industries(
    request: _facade().Request, user=_facade().Depends(_facade().get_mobile_user)
):
    """返回移动端首次开通可选行业目录。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    try:
        from app.mod_sdk.industry_baseline import build_onboarding_industry_catalog_for_request

        data = await build_onboarding_industry_catalog_for_request(request)
        return _facade().format_mobile_response(data=data)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile onboarding industries failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "行业目录加载失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.get(
    "/onboarding/industry-baseline", response_model=dict[str, _facade().Any]
)
async def mobile_industry_baseline(
    request: _facade().Request,
    industry_id: str = _facade().Query(default="通用"),
    user=_facade().Depends(_facade().get_mobile_user),
):
    """返回指定行业的移动端初始化方案。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    try:
        from app.mod_sdk.industry_baseline import build_industry_baseline_plan_for_request

        data = await build_industry_baseline_plan_for_request(request, industry_id)
        return _facade().format_mobile_response(data=data)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile industry baseline failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "行业基线加载失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.post(
    "/onboarding/select-industry", response_model=dict[str, _facade().Any]
)
async def mobile_select_onboarding_industry(
    body: dict[str, _facade().Any],
    request: _facade().Request,
    user=_facade().Depends(_facade().get_mobile_user),
):
    """Persist the mobile onboarding industry selection to the shared workspace SSOT."""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    industry_id = str(body.get("industry_id") or body.get("industryId") or "").strip()
    industry_mod_id = str(body.get("industry_mod_id") or body.get("industryModId") or "").strip()
    if not industry_id:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "缺少 industry_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.application.tenant_workspace_prefs import bind_selected_industry_for_user
        from app.fastapi_routes.market_account import (
            grant_market_enterprise_entitlements_for_session,
        )

        data = bind_selected_industry_for_user(user, industry_id, industry_mod_id=industry_mod_id)
        try:
            market_entitlements = await grant_market_enterprise_entitlements_for_session(
                _facade()._mobile_session_id_from_request(request), industry_id
            )
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("mobile select onboarding industry market sync failed")
            market_entitlements = {"success": False, "message": "市场权益同步失败"}
        if not market_entitlements.get("success"):
            _facade().logger.warning(
                "mobile onboarding industry saved while market entitlement sync failed: industry=%s message=%s",
                industry_id,
                market_entitlements.get("message"),
            )
        return _facade().format_mobile_response(
            data={**(data or {}), "market_entitlements": market_entitlements},
            message="行业已绑定到当前账号",
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile select onboarding industry failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "行业绑定失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.post(
    "/mod-store/install-host-foundation", response_model=dict[str, _facade().Any]
)
async def mobile_install_host_foundation(
    edition: str | None = _facade().Query(default=None),
    user=_facade().Depends(_facade().get_mobile_user),
):
    """为移动端账号安装宿主基础能力包。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    try:
        from app.fastapi_routes.mod_store_routes import _install_host_foundation_internal

        result = await _install_host_foundation_internal(edition)
        return _facade().format_mobile_response(
            data=result.data,
            message=result.message,
            success=bool(result.success),
            code=200 if result.success else 409,
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile install host foundation failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "基础员工包安装失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.post(
    "/mod-store/install-industry-seed", response_model=dict[str, _facade().Any]
)
async def mobile_install_industry_seed(
    body: dict[str, _facade().Any], user=_facade().Depends(_facade().get_mobile_user)
):
    """按行业安装移动端初始化种子包。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    raw = str(body.get("industry_id") or body.get("industryId") or body.get("mod_id") or "").strip()
    if not raw:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "缺少 industry_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.mod_sdk.industry_seed import install_industry_seed_with_fallback

        data = await install_industry_seed_with_fallback(raw)
        if data.get("success"):
            selected_industry = str(data.get("industry_id") or "").strip()
            if selected_industry:
                from app.application.account_registration import set_account_industry

                set_account_industry(str(getattr(user, "username", "") or ""), selected_industry)
        return _facade().format_mobile_response(
            data=data,
            message=str(data.get("message") or ""),
            success=bool(data.get("success")),
            code=200 if data.get("success") else 409,
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile install industry seed failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "行业种子安装失败", success=False, code=500),
            status_code=500,
        )
