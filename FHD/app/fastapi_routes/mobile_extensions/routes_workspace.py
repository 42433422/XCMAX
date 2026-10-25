"""WorkspaceRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_extensions.navigation_constants import (
    _ADMIN_NAV_ITEM,
    _CORE_NAV_ITEMS,
    _ROLE_VISIBLE_KEYS,
)
from app.application.mobile_extensions.protocols import (
    GrantEntitlementsCall,
    IndustryCatalogCall,
    IndustryPlanCall,
    InstallCustomerSeedCall,
    InstallFoundationCall,
    InstallIndustrySeedCall,
    InstallModCall,
    LoadMarketAiEmployeeProfileIndexCall,
    MobileModItemsCall,
    MobilePrincipal,
    MobileSessionIdFromRequestCall,
    MobileUnauthorizedResponseCall,
    PlatformShellCall,
    SelectIndustryCall,
    SetAccountIndustryCall,
    SyncDatabaseCall,
    UserDependency,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkspaceRoutesPorts:
    load_market_ai_employee_profile_index: LoadMarketAiEmployeeProfileIndexCall
    mobile_mod_items: MobileModItemsCall
    platform_shell: PlatformShellCall
    mobile_unauthorized_response: MobileUnauthorizedResponseCall
    industry_catalog: IndustryCatalogCall
    industry_plan: IndustryPlanCall
    mobile_session_id_from_request: MobileSessionIdFromRequestCall
    select_industry: SelectIndustryCall
    grant_entitlements: GrantEntitlementsCall
    install_foundation: InstallFoundationCall
    install_industry_seed: InstallIndustrySeedCall
    set_account_industry: SetAccountIndustryCall
    install_mod: InstallModCall
    install_customer_seed: InstallCustomerSeedCall
    sync_database: SyncDatabaseCall


class WorkspaceRoutes:
    def __init__(self, ports: WorkspaceRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        @router.get("/mods", response_model=None)
        async def mobile_mods_summary(user: MobilePrincipal | None = Depends(get_user)) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            (
                market_profiles,
                market_connected,
                market_error,
            ) = await ports.load_market_ai_employee_profile_index()
            return format_mobile_response(
                data={
                    "items": ports.mobile_mod_items(
                        market_profiles, market_connected=market_connected
                    ),
                    "market_connected": market_connected,
                    "market_profile_count": len(market_profiles),
                    "market_error": market_error,
                }
            )

        self.mobile_mods_summary = mobile_mods_summary

        @router.get("/platform-shell", response_model=None)
        async def mobile_platform_shell(user: MobilePrincipal | None = Depends(get_user)) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            installed = [m["id"] for m in ports.mobile_mod_items()]

            return format_mobile_response(data=ports.platform_shell(installed))

        self.mobile_platform_shell = mobile_platform_shell

        @router.get("/onboarding/industries", response_model=dict[str, Any])
        async def mobile_onboarding_industries(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """返回移动端首次开通可选行业目录。"""
            if user is None:
                return ports.mobile_unauthorized_response()
            try:
                data = await ports.industry_catalog(request)
                return format_mobile_response(data=data)
            except RECOVERABLE_ERRORS:
                logger.exception("mobile onboarding industries failed")
                return JSONResponse(
                    format_mobile_response(None, "行业目录加载失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_onboarding_industries = mobile_onboarding_industries

        @router.get("/onboarding/industry-baseline", response_model=dict[str, Any])
        async def mobile_industry_baseline(
            request: Request,
            industry_id: str = Query(default="通用"),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """返回指定行业的移动端初始化方案。"""
            if user is None:
                return ports.mobile_unauthorized_response()
            try:
                data = await ports.industry_plan(request, industry_id)
                return format_mobile_response(data=data)
            except RECOVERABLE_ERRORS:
                logger.exception("mobile industry baseline failed")
                return JSONResponse(
                    format_mobile_response(None, "行业基线加载失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_industry_baseline = mobile_industry_baseline

        @router.post("/onboarding/select-industry", response_model=dict[str, Any])
        async def mobile_select_onboarding_industry(
            body: dict[str, Any], request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """Persist the mobile onboarding industry selection to the shared workspace SSOT."""
            if user is None:
                return ports.mobile_unauthorized_response()
            industry_id = str(body.get("industry_id") or body.get("industryId") or "").strip()
            industry_mod_id = str(
                body.get("industry_mod_id") or body.get("industryModId") or ""
            ).strip()
            if not industry_id:
                return JSONResponse(
                    format_mobile_response(None, "缺少 industry_id", success=False, code=400),
                    status_code=400,
                )
            try:
                data = ports.select_industry(user, industry_id, industry_mod_id=industry_mod_id)
                try:
                    market_entitlements = await ports.grant_entitlements(
                        ports.mobile_session_id_from_request(request), industry_id
                    )
                except RECOVERABLE_ERRORS:
                    logger.exception("mobile select onboarding industry market sync failed")
                    market_entitlements = {"success": False, "message": "市场权益同步失败"}
                if not market_entitlements.get("success"):
                    logger.warning(
                        "mobile onboarding industry saved while market entitlement sync failed: industry=%s message=%s",
                        industry_id,
                        market_entitlements.get("message"),
                    )
                return format_mobile_response(
                    data={**(data or {}), "market_entitlements": market_entitlements},
                    message="行业已绑定到当前账号",
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile select onboarding industry failed")
                return JSONResponse(
                    format_mobile_response(None, "行业绑定失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_select_onboarding_industry = mobile_select_onboarding_industry

        @router.post("/mod-store/install-host-foundation", response_model=dict[str, Any])
        async def mobile_install_host_foundation(
            edition: str | None = Query(default=None),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """为移动端账号安装宿主基础能力包。"""
            if user is None:
                return ports.mobile_unauthorized_response()
            try:
                result = await ports.install_foundation(edition)
                return format_mobile_response(
                    data=result.data,
                    message=result.message,
                    success=bool(result.success),
                    code=200 if result.success else 409,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile install host foundation failed")
                return JSONResponse(
                    format_mobile_response(None, "基础员工包安装失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_install_host_foundation = mobile_install_host_foundation

        @router.post("/mod-store/install-industry-seed", response_model=dict[str, Any])
        async def mobile_install_industry_seed(
            body: dict[str, Any], user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """按行业安装移动端初始化种子包。"""
            if user is None:
                return ports.mobile_unauthorized_response()
            raw = str(
                body.get("industry_id") or body.get("industryId") or body.get("mod_id") or ""
            ).strip()
            if not raw:
                return JSONResponse(
                    format_mobile_response(None, "缺少 industry_id", success=False, code=400),
                    status_code=400,
                )
            try:
                data = await ports.install_industry_seed(raw)
                if data.get("success"):
                    selected_industry = str(data.get("industry_id") or "").strip()
                    if selected_industry:
                        ports.set_account_industry(
                            str(getattr(user, "username", "") or ""), selected_industry
                        )
                return format_mobile_response(
                    data=data,
                    message=str(data.get("message") or ""),
                    success=bool(data.get("success")),
                    code=200 if data.get("success") else 409,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile install industry seed failed")
                return JSONResponse(
                    format_mobile_response(None, "行业种子安装失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_install_industry_seed = mobile_install_industry_seed

        @router.post("/mod-store/install", response_model=dict[str, Any])
        async def mobile_install_mod(
            body: dict[str, Any], user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """从移动端安装指定市场 Mod。"""
            if user is None:
                return ports.mobile_unauthorized_response()
            mod_id = str(
                body.get("mod_id") or body.get("pkg_id") or body.get("package_file") or ""
            ).strip()
            if not mod_id:
                return JSONResponse(
                    format_mobile_response(None, "缺少 mod_id", success=False, code=400),
                    status_code=400,
                )
            try:
                result = await ports.install_mod(mod_id, "", activate=True)
                return format_mobile_response(
                    data=result.data,
                    message=result.message,
                    success=bool(result.success),
                    code=200 if result.success else 409,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile install mod failed")
                return JSONResponse(
                    format_mobile_response(None, "MOD 安装失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_install_mod = mobile_install_mod

        @router.post("/mod-store/install-customer-delivery-seed", response_model=dict[str, Any])
        async def mobile_install_customer_delivery_seed(
            request: Request, body: dict[str, Any], user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """安装客户交付场景的移动端种子包。"""
            if user is None:
                return ports.mobile_unauthorized_response()
            mod_id = str(body.get("mod_id") or body.get("pkg_id") or "").strip()
            industry_id = str(body.get("industry_id") or body.get("industryId") or "").strip()
            if not mod_id:
                return JSONResponse(
                    format_mobile_response(None, "缺少 mod_id", success=False, code=400),
                    status_code=400,
                )
            try:
                data = await ports.install_customer_seed(
                    request=request,
                    mod_id=mod_id,
                    industry_id=industry_id,
                    market_token=str(
                        body.get("market_access_token")
                        or body.get("market_token")
                        or body.get("token")
                        or ""
                    ),
                    account_username=str(getattr(user, "username", "") or "").strip(),
                )
                return format_mobile_response(
                    data=data,
                    message=str(data.get("message") or ""),
                    success=bool(data.get("success")),
                    code=200 if data.get("success") else 409,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile install customer delivery seed failed")
                return JSONResponse(
                    format_mobile_response(None, "客户交付包安装失败", success=False, code=500),
                    status_code=500,
                )

        self.mobile_install_customer_delivery_seed = mobile_install_customer_delivery_seed

        @router.get("/home", response_model=None)
        async def mobile_home(user: MobilePrincipal | None = Depends(get_user)) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            (
                market_profiles,
                market_connected,
                market_error,
            ) = await ports.load_market_ai_employee_profile_index()
            mod_items = ports.mobile_mod_items(market_profiles, market_connected=market_connected)
            installed = [m["id"] for m in mod_items]

            sync_data: dict[str, Any] = {}
            try:
                sync_data = ports.sync_database().get_status()
            except RECOVERABLE_ERRORS:
                sync_data = {"error": "市场同步失败"}
            return format_mobile_response(
                data={
                    "mods": mod_items,
                    "market_connected": market_connected,
                    "market_profile_count": len(market_profiles),
                    "market_error": market_error,
                    "platform_shell": ports.platform_shell(installed),
                    "sync": sync_data,
                }
            )

        self.mobile_home = mobile_home

        @router.get("/nav-menu", response_model=None)
        async def mobile_nav_menu(user: MobilePrincipal | None = Depends(get_user)) -> object:
            """返回当前用户可见的侧栏菜单项（核心菜单 + Mod 菜单）。

            供手机端"探索"Tab 配对后动态渲染工具列表，与桌面端侧栏对齐。
            """
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            user_role = str(getattr(user, "role", "") or "").strip().lower()
            is_admin = user_role in {"admin", "super_admin", "owner"}
            account_kind = "admin" if is_admin else "enterprise"
            visible_keys = _ROLE_VISIBLE_KEYS.get(account_kind)
            items: list[dict[str, Any]] = []
            for item in _CORE_NAV_ITEMS:
                if visible_keys is not None and item["key"] not in visible_keys:
                    continue
                items.append({**item, "source": "core"})
            if is_admin:
                items.append({**_ADMIN_NAV_ITEM, "source": "core"})
            try:
                mod_items = ports.mobile_mod_items()
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
                                "key": (
                                    f"mod-{menu_id}" if not menu_id.startswith("mod-") else menu_id
                                ),
                                "name": menu_label,
                                "icon": menu_icon,
                                "path": menu_path,
                                "source": "mod",
                                "mod_id": mod_id,
                            }
                        )
            except RECOVERABLE_ERRORS as exc:
                logger.warning("nav-menu mod items failed: %s", exc)
            return format_mobile_response(data={"items": items, "account_kind": account_kind})

        self.mobile_nav_menu = mobile_nav_menu
