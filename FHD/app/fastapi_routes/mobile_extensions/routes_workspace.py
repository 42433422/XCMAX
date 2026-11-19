"""WorkspaceRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

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
from app.fastapi_routes.mobile_extensions.navigation_constants import resolve_mobile_navigation
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _has_personal_plan(user: MobilePrincipal) -> bool:
    return getattr(user, "account_tier", None) == "personal"


def _personal_mod_denied() -> JSONResponse:
    return JSONResponse(
        format_mobile_response(None, "个人使用版无 Mod 权限", success=False, code=403),
        status_code=403,
    )


class MobileWorkspacePrefsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_ai_employees: dict[str, bool]


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

        async def require_workspace_account(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ):
            if user is None:
                raise HTTPException(status_code=401, detail="请先登录")
            tenant_id = getattr(user, "tenant_id", None)
            if type(tenant_id) is not int or tenant_id <= 0:
                raise HTTPException(status_code=403, detail="无法确认企业数据归属")
            request.state.tenant_id = tenant_id
            return user

        @router.get("/workspace/templates", response_model=None)
        async def workspace_templates(
            request: Request, user: MobilePrincipal = Depends(require_workspace_account)
        ):
            from app.fastapi_routes.template_api import templates_list_compat
            from app.infrastructure.tenant_scope import owned_tenant_scope

            # Keep account-owned templates and the shared starter catalog. The
            # outer Mod middleware retains entitlement and database selection.
            with owned_tenant_scope(request.state.tenant_id):
                return await run_in_threadpool(templates_list_compat, request)

        from app.fastapi_routes.domains.shipment.shipment_orders import router as shipment_router

        shipment_paths = {
            "/api/shipment/shipment-records/record",
            "/api/shipment/shipment-records/export",
        }
        for route in shipment_router.routes:
            if not isinstance(route, APIRoute) or route.path not in shipment_paths:
                continue
            router.add_api_route(
                "/workspace" + route.path.removeprefix("/api"),
                route.endpoint,
                methods=list(route.methods or ()),
                dependencies=[Depends(require_workspace_account), *route.dependencies],
                response_model=None,
            )

        @router.get("/workspace/prefs", response_model=None)
        async def workspace_prefs(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ):
            if user is None:
                return ports.mobile_unauthorized_response()
            from app.fastapi_routes.workspace_prefs_routes import get_workspace_prefs_endpoint

            result = await run_in_threadpool(get_workspace_prefs_endpoint, request)
            if not result.get("owner_id"):
                return JSONResponse(
                    format_mobile_response(
                        None, "无法确认工作区归属，请重新登录", success=False, code=403
                    ),
                    status_code=403,
                )
            return result

        @router.patch("/workspace/prefs", response_model=None)
        async def update_workspace_prefs(
            body: MobileWorkspacePrefsPatch,
            request: Request,
            user: MobilePrincipal | None = Depends(get_user),
        ):
            if user is None:
                return ports.mobile_unauthorized_response()
            from app.fastapi_routes.workspace_prefs_routes import (
                WorkspacePrefsPatch,
                patch_workspace_prefs_endpoint,
            )

            return await patch_workspace_prefs_endpoint(
                WorkspacePrefsPatch(workflow_ai_employees=body.workflow_ai_employees), request
            )

        @router.get("/mods", response_model=None)
        async def mobile_mods_summary(user: MobilePrincipal | None = Depends(get_user)) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            if _has_personal_plan(user):
                return format_mobile_response(
                    data={
                        "items": [],
                        "market_connected": False,
                        "market_profile_count": 0,
                        "market_error": "",
                    }
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
            installed = [] if _has_personal_plan(user) else [m["id"] for m in ports.mobile_mod_items()]

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
            if _has_personal_plan(user):
                return _personal_mod_denied()
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
            if _has_personal_plan(user):
                return _personal_mod_denied()
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
            if _has_personal_plan(user):
                return _personal_mod_denied()
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
            if _has_personal_plan(user):
                return _personal_mod_denied()
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
            if _has_personal_plan(user):
                return _personal_mod_denied()
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
            mod_items = (
                []
                if _has_personal_plan(user)
                else ports.mobile_mod_items(market_profiles, market_connected=market_connected)
            )
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
        async def mobile_nav_menu(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """返回当前用户可见的侧栏菜单项（核心菜单 + Mod 菜单）。

            供手机端工作台按任务、业务、资料和电脑能力分组，与桌面端侧栏对齐。
            """
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )
            user_role = str(getattr(user, "role", "") or "").strip().lower()
            tier = str(getattr(user, "tier", "") or "").strip().lower()
            account_kind = tier if tier in {"personal", "enterprise", "admin"} else "enterprise"
            if user_role in {"admin", "super_admin", "owner"}:
                account_kind = "admin"
            elif user_role == "personal":
                account_kind = "personal"
            tenant_id = getattr(user, "tenant_id", None)
            tenant_member = user_role.startswith("tenant:")
            tenant = tenant_member or (type(tenant_id) is int and tenant_id > 0)
            permissions: list[str] = []
            if tenant_member:
                from app.application.auth_app_service import get_auth_app_service
                from app.db.models import User

                try:
                    if isinstance(user, User):
                        permissions = get_auth_app_service().get_user_permissions(user)
                except RECOVERABLE_ERRORS:
                    logger.warning("nav-menu tenant permissions unavailable")
            mod_items: list[dict[str, Any]] = []
            try:
                from app.enterprise.mod_entitlements import (
                    clear_session_entitlements,
                    sync_entitlements_for_session,
                )

                clear_session_entitlements()
                sid = ports.mobile_session_id_from_request(request)
                if sid:
                    await sync_entitlements_for_session(sid)
                    from app.application.session_account_meta import load_session_account_meta
                    from app.enterprise.mod_entitlements import is_admin_account_session

                    session_kind = (load_session_account_meta(sid) or {}).get("account_kind")
                    if is_admin_account_session():
                        account_kind = "admin"
                    elif account_kind != "admin" and session_kind in {"personal", "enterprise"}:
                        account_kind = session_kind
                if not _has_personal_plan(user):
                    mod_items = ports.mobile_mod_items()
            except RECOVERABLE_ERRORS as exc:
                logger.warning("nav-menu mod items failed: %s", exc)
            items = resolve_mobile_navigation(
                mod_items,
                account_kind=account_kind,
                tenant=tenant,
                tenant_member=tenant_member,
                permissions=permissions,
            )
            return format_mobile_response(data={"items": items, "account_kind": account_kind})

        self.mobile_nav_menu = mobile_nav_menu
