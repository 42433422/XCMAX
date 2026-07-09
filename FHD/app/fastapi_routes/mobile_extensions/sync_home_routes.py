"""Mobile 交流圈 / Mod / 首页 / 导航 / 同步 routes (split from mobile_api_extensions).

Included into ``extension_router``; handlers and helpers are re-exported from
``mobile_api_extensions`` for tests and patch compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions import _ext as mext
from app.utils.mobile_api import format_mobile_response

logger = logging.getLogger(__name__)

sync_home_router = APIRouter()

from app.fastapi_routes.mobile_extensions.models import (
    AiCircleCommentBody,
    AiCirclePostBody,
    SyncAckBody,
    SyncPullBody,
    SyncPushBody,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

OPERATIONAL_ERRORS = RECOVERABLE_ERRORS
RECOVERABLE_ERRORS = RECOVERABLE_ERRORS

# ── MOD / 平台 / 首页 ──


@sync_home_router.get("/circle/posts")
async def mobile_ai_circle_posts(
    limit: int = Query(default=50, ge=1, le=100),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.ai_circle_service import list_posts

    try:
        import importlib

        employee_circle_sync = importlib.import_module("app.application.employee_circle_sync")

        await employee_circle_sync.sync_modstore_reports()
    except Exception:  # noqa: BLE001 - 同步失败不影响交流圈展示
        logger.warning("circle: modstore report sync skipped", exc_info=True)

    uid, _, _ = mext._ai_circle_user(user)
    posts = list_posts(user_id=uid, limit=limit)
    profiles = mext._ai_circle_employee_profiles()
    for post in posts:
        profile = profiles.get(str(post.get("employee_id") or ""))
        if profile:
            post["author_name"] = profile["name"]
            post["author_avatar"] = profile["avatar"] or post.get("author_avatar")
    return format_mobile_response(data={"items": posts, "count": len(posts)})


@sync_home_router.post("/circle/posts")
async def mobile_ai_circle_create_post(
    body: AiCirclePostBody,
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.ai_circle_service import create_user_post

    uid, name, avatar = mext._ai_circle_user(user)
    try:
        post_id = create_user_post(user_id=uid, author_name=name, avatar=avatar, body=body.body)
        return format_mobile_response(data={"id": post_id}, message="发布成功")
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )


@sync_home_router.post("/circle/posts/{post_id}/like")
async def mobile_ai_circle_toggle_like(post_id: int, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.ai_circle_service import toggle_like

    uid, _, _ = mext._ai_circle_user(user)
    try:
        liked = toggle_like(post_id=post_id, user_id=uid)
        return format_mobile_response(data={"liked": liked})
    except LookupError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=404), status_code=404
        )


@sync_home_router.post("/circle/posts/{post_id}/comments")
async def mobile_ai_circle_add_comment(
    post_id: int,
    body: AiCircleCommentBody,
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    from app.application.ai_circle_service import add_comment

    uid, name, _ = mext._ai_circle_user(user)
    try:
        comment_id = add_comment(post_id=post_id, user_id=uid, author_name=name, body=body.body)
        return format_mobile_response(data={"id": comment_id}, message="评论成功")
    except ValueError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=400), status_code=400
        )
    except LookupError as exc:
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=404), status_code=404
        )


@sync_home_router.get("/mods")
async def mobile_mods_summary(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    market_profiles, market_connected, market_error = await mext._load_market_ai_employee_profile_index()
    return format_mobile_response(
        data={
            "items": mext._mobile_mod_items(market_profiles, market_connected=market_connected),
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
        }
    )


@sync_home_router.get("/platform-shell")
async def mobile_platform_shell(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    installed = [m["id"] for m in mext._mobile_mod_items()]
    from app.mod_sdk.platform_shell import build_platform_shell_payload

    return format_mobile_response(data=build_platform_shell_payload(installed))


@sync_home_router.get("/onboarding/industries", response_model=dict[str, Any])
async def mobile_onboarding_industries(request: Request, user=Depends(get_mobile_user)):
    """返回移动端首次开通可选行业目录。"""
    if user is None:
        return mext._mobile_unauthorized_response()
    try:
        from app.mod_sdk.industry_baseline import build_onboarding_industry_catalog_for_request

        data = await build_onboarding_industry_catalog_for_request(request)
        return format_mobile_response(data=data)
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile onboarding industries failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@sync_home_router.get("/onboarding/industry-baseline", response_model=dict[str, Any])
async def mobile_industry_baseline(
    request: Request,
    industry_id: str = Query(default="通用"),
    user=Depends(get_mobile_user),
):
    """返回指定行业的移动端初始化方案。"""
    if user is None:
        return mext._mobile_unauthorized_response()
    try:
        from app.mod_sdk.industry_baseline import build_industry_baseline_plan_for_request

        data = await build_industry_baseline_plan_for_request(request, industry_id)
        return format_mobile_response(data=data)
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile industry baseline failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@sync_home_router.post("/onboarding/select-industry", response_model=dict[str, Any])
async def mobile_select_onboarding_industry(
    body: dict[str, Any],
    request: Request,
    user=Depends(get_mobile_user),
):
    """Persist the mobile onboarding industry selection to the shared workspace SSOT."""
    if user is None:
        return mext._mobile_unauthorized_response()
    industry_id = str(body.get("industry_id") or body.get("industryId") or "").strip()
    industry_mod_id = str(body.get("industry_mod_id") or body.get("industryModId") or "").strip()
    if not industry_id:
        return JSONResponse(
            format_mobile_response(None, "缺少 industry_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.application.tenant_workspace_prefs import bind_selected_industry_for_user
        from app.fastapi_routes.market_account import (
            grant_market_enterprise_entitlements_for_session,
        )

        data = bind_selected_industry_for_user(
            user,
            industry_id,
            industry_mod_id=industry_mod_id,
        )
        try:
            market_entitlements = await grant_market_enterprise_entitlements_for_session(
                mext._mobile_session_id_from_request(request),
                industry_id,
            )
        except mext.RECOVERABLE_ERRORS as exc:
            logger.exception("mobile select onboarding industry market sync failed")
            market_entitlements = {"success": False, "message": str(exc)}
        if not market_entitlements.get("success"):
            logger.warning(
                "mobile onboarding industry saved while market entitlement sync failed: "
                "industry=%s message=%s",
                industry_id,
                market_entitlements.get("message"),
            )
        return format_mobile_response(
            data={**(data or {}), "market_entitlements": market_entitlements},
            message="行业已绑定到当前账号",
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile select onboarding industry failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@sync_home_router.post("/mod-store/install-host-foundation", response_model=dict[str, Any])
async def mobile_install_host_foundation(
    edition: str | None = Query(default=None),
    user=Depends(get_mobile_user),
):
    """为移动端账号安装宿主基础能力包。"""
    if user is None:
        return mext._mobile_unauthorized_response()
    try:
        from app.fastapi_routes.mod_store_routes import _install_host_foundation_internal

        result = await _install_host_foundation_internal(edition)
        return format_mobile_response(
            data=result.data,
            message=result.message,
            success=bool(result.success),
            code=200 if result.success else 409,
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile install host foundation failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@sync_home_router.post("/mod-store/install-industry-seed", response_model=dict[str, Any])
async def mobile_install_industry_seed(body: dict[str, Any], user=Depends(get_mobile_user)):
    """按行业安装移动端初始化种子包。"""
    if user is None:
        return mext._mobile_unauthorized_response()
    raw = str(body.get("industry_id") or body.get("industryId") or body.get("mod_id") or "").strip()
    if not raw:
        return JSONResponse(
            format_mobile_response(None, "缺少 industry_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.mod_sdk.industry_seed import install_industry_seed_with_fallback

        data = await install_industry_seed_with_fallback(raw)
        if data.get("success"):
            # 选行业即把所选行业持久化到账号(否则账号 industry_id 停留在注册默认「通用」)。
            selected_industry = str(data.get("industry_id") or "").strip()
            if selected_industry:
                from app.application.account_registration import set_account_industry

                set_account_industry(str(getattr(user, "username", "") or ""), selected_industry)
        return format_mobile_response(
            data=data,
            message=str(data.get("message") or ""),
            success=bool(data.get("success")),
            code=200 if data.get("success") else 409,
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile install industry seed failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@sync_home_router.post("/mod-store/install", response_model=dict[str, Any])
async def mobile_install_mod(body: dict[str, Any], user=Depends(get_mobile_user)):
    """从移动端安装指定市场 Mod。"""
    if user is None:
        return mext._mobile_unauthorized_response()
    mod_id = str(body.get("mod_id") or body.get("pkg_id") or body.get("package_file") or "").strip()
    if not mod_id:
        return JSONResponse(
            format_mobile_response(None, "缺少 mod_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.fastapi_routes.mod_store_routes import _install_from_catalog

        result = await _install_from_catalog(mod_id, "", activate=True)
        return format_mobile_response(
            data=result.data,
            message=result.message,
            success=bool(result.success),
            code=200 if result.success else 409,
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile install mod failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@sync_home_router.post(
    "/mod-store/install-customer-delivery-seed",
    response_model=dict[str, Any],
)
async def mobile_install_customer_delivery_seed(
    body: dict[str, Any],
    user=Depends(get_mobile_user),
):
    """安装客户交付场景的移动端种子包。"""
    if user is None:
        return mext._mobile_unauthorized_response()
    mod_id = str(body.get("mod_id") or body.get("pkg_id") or "").strip()
    industry_id = str(body.get("industry_id") or body.get("industryId") or "").strip()
    if not mod_id:
        return JSONResponse(
            format_mobile_response(None, "缺少 mod_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.mod_sdk.customer_delivery_seed import install_customer_delivery_seed_package

        data = await install_customer_delivery_seed_package(
            mod_id=mod_id,
            industry_id=industry_id,
            market_token=str(
                body.get("market_access_token")
                or body.get("market_token")
                or body.get("token")
                or ""
            ),
        )
        return format_mobile_response(
            data=data,
            message=str(data.get("message") or ""),
            success=bool(data.get("success")),
            code=200 if data.get("success") else 409,
        )
    except mext.RECOVERABLE_ERRORS as exc:
        logger.exception("mobile install customer delivery seed failed")
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@sync_home_router.get("/home")
async def mobile_home(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    market_profiles, market_connected, market_error = await mext._load_market_ai_employee_profile_index()
    mod_items = mext._mobile_mod_items(market_profiles, market_connected=market_connected)
    installed = [m["id"] for m in mod_items]
    from app.mod_sdk.platform_shell import build_platform_shell_payload

    sync_data: dict[str, Any] = {}
    try:
        from app.db.xcmax_sync import SyncDb

        sync_data = SyncDb().get_status()
    except mext.OPERATIONAL_ERRORS as exc:
        sync_data = {"error": str(exc)}
    return format_mobile_response(
        data={
            "mods": mod_items,
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
            "platform_shell": build_platform_shell_payload(installed),
            "sync": sync_data,
        },
    )


# ── 侧栏菜单对齐（探索 Tab 配对后动态显示桌面端工具） ──

_CORE_NAV_ITEMS: list[dict[str, str]] = [
    {"key": "chat", "name": "智能对话", "icon": "fa-comments-o", "path": "/chat"},
    {"key": "im", "name": "信息", "icon": "fa-envelope-o", "path": "/im"},
    {"key": "ai-ecosystem", "name": "智能生态", "icon": "fa-sitemap", "path": "/ai-ecosystem"},
    {
        "key": "employee-workflow",
        "name": "员工工作台",
        "icon": "fa-users",
        "path": "/employee-workflow",
    },
    {"key": "products", "name": "业务对象", "icon": "fa-cubes", "path": "/products"},
    {"key": "customers", "name": "组织管理", "icon": "fa-users", "path": "/customers"},
    {"key": "orders", "name": "业务单据", "icon": "fa-file-text-o", "path": "/orders"},
    {
        "key": "shipment-records",
        "name": "业务记录",
        "icon": "fa-industry",
        "path": "/shipment-records",
    },
    {"key": "materials", "name": "资源库", "icon": "fa-archive", "path": "/materials"},
    {"key": "data-sources", "name": "数据来源", "icon": "fa-database", "path": "/data-sources"},
    {"key": "print", "name": "模板与打印", "icon": "fa-print", "path": "/print"},
    {"key": "settings", "name": "系统设置", "icon": "fa-cog", "path": "/settings"},
]

_ADMIN_NAV_ITEM = {
    "key": "admin-entitlements",
    "name": "用户管理",
    "icon": "fa-shield",
    "path": "/admin-entitlements",
}

# 角色 → 可见核心 key 白名单（None 表示全部可见）
_ROLE_VISIBLE_KEYS: dict[str, set[str] | None] = {
    "admin": None,  # 全部
    "enterprise": {
        "chat",
        "im",
        "ai-ecosystem",
        "employee-workflow",
        "products",
        "customers",
        "orders",
        "shipment-records",
        "materials",
        "data-sources",
        "print",
        "settings",
    },
    "personal": {"chat", "im", "ai-ecosystem", "settings"},
}


@sync_home_router.get("/nav-menu")
async def mobile_nav_menu(user=Depends(get_mobile_user)):
    """返回当前用户可见的侧栏菜单项（核心菜单 + Mod 菜单）。

    供手机端"探索"Tab 配对后动态渲染工具列表，与桌面端侧栏对齐。
    """
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )

    # 判断角色
    user_role = str(getattr(user, "role", "") or "").strip().lower()
    is_admin = user_role in {"admin", "super_admin", "owner"}
    account_kind = "admin" if is_admin else "enterprise"

    # 也可以从 session 获取 account_kind，这里简化用 role 判断
    visible_keys = _ROLE_VISIBLE_KEYS.get(account_kind)

    # 核心菜单
    items: list[dict[str, Any]] = []
    for item in _CORE_NAV_ITEMS:
        if visible_keys is not None and item["key"] not in visible_keys:
            continue
        items.append({**item, "source": "core"})

    # 管理员追加用户管理
    if is_admin:
        items.append({**_ADMIN_NAV_ITEM, "source": "core"})

    # Mod 菜单
    try:
        mod_items = mext._mobile_mod_items()
        for mod in mod_items:
            mod_id = str(mod.get("id") or "").strip()
            mod_name = str(mod.get("name") or mod_id).strip()
            frontend_menu = mod.get("frontend_menu") or mod.get("menu") or []
            if not isinstance(frontend_menu, list):
                continue
            for menu_entry in frontend_menu:
                if not isinstance(menu_entry, dict):
                    continue
                menu_id = str(menu_entry.get("id") or menu_entry.get("key") or "").strip()
                if not menu_id:
                    continue
                menu_label = str(
                    menu_entry.get("label") or menu_entry.get("name") or mod_name
                ).strip()
                menu_path = str(
                    menu_entry.get("path") or menu_entry.get("url") or f"/mod/{mod_id}"
                ).strip()
                menu_icon = str(
                    menu_entry.get("icon") or menu_entry.get("iconClass") or "fa-cube"
                ).strip()
                items.append(
                    {
                        "key": f"mod-{menu_id}" if not menu_id.startswith("mod-") else menu_id,
                        "name": menu_label,
                        "icon": menu_icon,
                        "path": menu_path,
                        "source": "mod",
                        "mod_id": mod_id,
                    }
                )
    except mext.OPERATIONAL_ERRORS as exc:
        logger.warning("nav-menu mod items failed: %s", exc)

    return format_mobile_response(data={"items": items, "account_kind": account_kind})


# ── 同步 ──


def _mobile_sync_runtime_contract() -> dict[str, Any]:
    return {
        "source": "cloud",
        "sync_mode": "cloud",
        "standalone_supported": True,
        "desktop_required": False,
        "executor_required": False,
        "mobile_flow_parity": True,
        "offline_cache_supported": True,
        "desktop_executor": {
            "required": False,
            "role": "optional_local_executor",
            "required_for": ["local_files", "local_cli", "local_printing", "lan_devices"],
        },
    }


async def _mobile_sync_circle_posts(user: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    try:
        import importlib

        from app.application.ai_circle_service import list_posts

        employee_circle_sync = importlib.import_module("app.application.employee_circle_sync")
        try:
            await employee_circle_sync.sync_modstore_reports()
        except Exception:  # noqa: BLE001 - 交流圈同步是拉取增强项，不能拖垮整次手机同步
            logger.warning("mobile sync: circle modstore report sync skipped", exc_info=True)

        uid, _, _ = mext._ai_circle_user(user)
        posts = list_posts(user_id=uid, limit=limit)
        profiles = mext._ai_circle_employee_profiles()
        for post in posts:
            profile = profiles.get(str(post.get("employee_id") or ""))
            if profile:
                post["author_name"] = profile["name"]
                post["author_avatar"] = profile["avatar"] or post.get("author_avatar")
        return posts
    except Exception as exc:  # noqa: BLE001 - 手机同步的其他数据不能被交流圈投影拖垮
        logger.warning("mobile sync: circle posts skipped: %s", exc)
        return []


@sync_home_router.get("/sync/status")
async def mobile_sync_status(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.db.xcmax_sync import SyncDb, _ensure_schema, _get_conn

        db = SyncDb()
        st = dict(db.get_status())
        with _get_conn() as conn:
            _ensure_schema(conn)
            st["inbox_pending"] = conn.execute(
                "SELECT COUNT(*) FROM sync_inbox WHERE status='pending'",
            ).fetchone()[0]
    except mext.OPERATIONAL_ERRORS as exc:
        st = {"error": str(exc), "healthy": False}
    st.update(_mobile_sync_runtime_contract())
    return format_mobile_response(data=st)


@sync_home_router.post("/sync/pull")
async def mobile_sync_pull(body: SyncPullBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.db.xcmax_sync import SyncDb

        sync_db = SyncDb()
        changes = sync_db.get_changes(since_cursor=body.since_cursor, limit=200)
        cursor = sync_db.get_status().get("local_cursor") or body.since_cursor
        if cursor:
            sync_db.update_remote_cursor(int(cursor))
        im_entity_types = {"im_message", "im_read_state"}
        im_changes = [c for c in changes if str(c.get("entity_type") or "") in im_entity_types]
        ai_changes = mext._ai_conversation_changes(user, limit=100)
        circle_posts = await _mobile_sync_circle_posts(user, limit=50)
        approvals = mext._safe_mobile_sync_items("approvals", mext._approval_items)
        shipments = mext._safe_mobile_sync_items("shipments", mext._shipment_items)
        return format_mobile_response(
            data={
                **_mobile_sync_runtime_contract(),
                "cursor": cursor,
                "changes": changes,
                "im_changes": im_changes,
                "im_change_count": len(im_changes),
                "ai_changes": ai_changes,
                "ai_change_count": len(ai_changes),
                "circle_posts": circle_posts,
                "circle_post_count": len(circle_posts),
                "approvals": approvals,
                "shipments": shipments,
            },
        )
    except mext.OPERATIONAL_ERRORS as exc:
        logger.warning("mobile_sync_pull: %s", exc)
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@sync_home_router.post("/sync/push")
async def mobile_sync_push(body: SyncPushBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    actor = getattr(user, "username", None) or f"user-{getattr(user, 'id', 0)}"
    written = 0
    try:
        from app.db.xcmax_sync import SyncDb

        sync_db = SyncDb()
        for item in body.items[:50]:
            sync_db.append_change(
                item.entity_type,
                item.entity_id,
                item.operation,
                item.payload,
                actor=actor,
                origin_node="mobile",
            )
            written += 1
        apply_result: dict[str, Any] = {}
        try:
            from app.application.xcmax_sync_app import apply_inbox

            apply_result = apply_inbox(limit=written + 50) or {}
        except mext.OPERATIONAL_ERRORS as ae:
            apply_result = {"error": str(ae)}
        return format_mobile_response(data={"written": written, "apply": apply_result})
    except mext.OPERATIONAL_ERRORS as exc:
        logger.warning("mobile_sync_push: %s", exc)
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@sync_home_router.post("/sync/ack")
async def mobile_sync_ack(body: SyncAckBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.db.xcmax_sync import SyncDb

        sync_db = SyncDb()
        sync_db.update_remote_cursor(int(body.cursor))
        return format_mobile_response(data={"acked": int(body.cursor)})
    except mext.OPERATIONAL_ERRORS as exc:
        logger.warning("mobile_sync_ack: %s", exc)
        return JSONResponse(
            format_mobile_response(None, str(exc), success=False, code=500),
            status_code=500,
        )


@sync_home_router.get("/sync/conflicts")
async def mobile_sync_conflicts(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    items: list[dict[str, Any]] = []
    try:
        from app.db.xcmax_sync import _ensure_schema, _get_conn

        with _get_conn() as conn:
            _ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT id, entity_type, entity_id, conflict_note, received_at
                FROM sync_inbox WHERE status='conflict' ORDER BY id DESC LIMIT 50
                """,
            ).fetchall()
            items = [dict(r) for r in rows]
    except mext.OPERATIONAL_ERRORS as exc:
        return format_mobile_response(data={"items": [], "error": str(exc)})
    return format_mobile_response(data={"items": items})
