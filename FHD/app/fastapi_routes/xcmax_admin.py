"""XCmax 服务器后台控制面路由。

提供:
  GET  /api/xcmax/admin/modules      — 本地模块注册表（核心 + Mod + 员工包）
  GET  /api/xcmax/admin/remote-status — 远端服务器连接状态探测
  GET  /api/xcmax/sync/status        — 双向同步健康状态
  POST /api/xcmax/sync/push          — 触发本地 outbox 向服务器推送
  GET  /api/xcmax/sync/changes       — 获取变更日志（支持 since_cursor）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.request
from typing import Any, cast

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax", tags=["xcmax-admin"])

REMOTE_HOST = os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147")
REMOTE_PORT = int(os.environ.get("XCMAX_REMOTE_PORT", "9999"))


def _require_market_admin_session(request: Request) -> JSONResponse | None:
    from app.application.session_account_meta import load_session_account_meta
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    sid = _session_id_from_request(request)
    if not sid:
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    meta = load_session_account_meta(sid) or {}
    if meta.get("account_kind") != "admin" or not meta.get("market_is_admin"):
        return JSONResponse(
            {"success": False, "message": "需要管理员账号登录后访问"},
            status_code=403,
        )
    return None


def _release_train_snapshot() -> dict[str, Any]:
    """读取 release_train SSOT；优先 modstore 模块，回退 FHD/config JSON。"""
    from pathlib import Path

    def _default_snapshot(*, note: str | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "epoch": "1.0.0.0",
            "current": "1.0.0.0",
            "started_at": "2026-06-04",
            "day_index": 0,
        }
        if note:
            data["note"] = note
        return data

    def _from_file(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return _default_snapshot(note="ssot missing")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except RECOVERABLE_ERRORS as exc:
            logger.warning("release-train json read failed: %s", exc)
        return _default_snapshot()

    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        path = Path(mono).expanduser().resolve() / "FHD" / "config" / "release_train.json"
        return _from_file(path)

    try:
        from modstore_server.release_train import snapshot_public

        return cast("dict[str, Any]", snapshot_public())
    except RECOVERABLE_ERRORS:
        pass

    path = Path(__file__).resolve().parents[2] / "config" / "release_train.json"
    return _from_file(path)


async def _market_admin_proxy(
    request: Request,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    require_admin_session: bool = True,
):
    """Proxy server-function calls through the market token bound to the local session."""
    if require_admin_session:
        gate = _require_market_admin_session(request)
        if gate is not None:
            return gate

    if path in {
        "/api/admin/yuangon-onboard/status",
        "/api/admin/yuangon-onboard/run",
    }:
        from app.application.modstore_local_client import prefer_local_modstore

        if prefer_local_modstore():
            from app.application import self_maintenance_app_service as sm_svc

            try:
                if method.upper() == "GET":
                    return await sm_svc.get_yuangon_onboard_status_local()
                if method.upper() == "POST":
                    return await sm_svc.run_yuangon_onboard_local(json_body or {})
            except RECOVERABLE_ERRORS as exc:
                logger.warning("local yuangon onboarding failed path=%s: %s", path, exc)
                return JSONResponse(
                    {"success": False, "message": f"本地元工登记服务不可用: {exc}"},
                    status_code=502,
                )
    try:
        from app.fastapi_routes.market_account import (
            _authorization_from_request,
            _error_message,
            _proxy_json,
        )
    except RECOVERABLE_ERRORS as exc:
        return JSONResponse(
            {"success": False, "message": f"市场账号代理不可用: {exc}"},
            status_code=500,
        )

    body_for_auth = json_body if isinstance(json_body, dict) else {}
    authorization = _authorization_from_request(request, body_for_auth)
    if not authorization:
        return JSONResponse(
            {
                "success": False,
                "message": "尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization",
            },
            status_code=401,
        )

    payload = await _proxy_json(
        method,
        path,
        json_body=json_body,
        authorization=authorization,
        return_error_payload=True,
    )
    if isinstance(payload, JSONResponse):
        return payload
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 502)
        raw_error = payload.get("payload")
        return JSONResponse(
            {
                "success": False,
                "message": _error_message(raw_error, status_code),
                "data": raw_error,
            },
            status_code=status_code,
        )
    return payload


async def _digest_local_or_proxy(
    request: Request,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
):
    """本地 MODstore :8788 日更读接口：无 FHD 会话时用 admin 服务账号。"""
    from app.application.modstore_local_client import prefer_local_modstore

    if prefer_local_modstore() and method.upper() == "GET":
        from app.application import digest_email_app_service as digest_svc

        try:
            if path.startswith("/api/agent/butler/daily-digests?"):
                q = path.split("?", 1)[1] if "?" in path else ""
                limit, offset = 20, 0
                for part in q.split("&"):
                    if part.startswith("limit="):
                        limit = int(part.split("=", 1)[1])
                    elif part.startswith("offset="):
                        offset = int(part.split("=", 1)[1])
                return await digest_svc.list_daily_digests_local(limit=limit, offset=offset)
            if path.startswith("/api/agent/butler/daily-digests/") and path.endswith("/artifacts"):
                rid = path.split("/daily-digests/", 1)[1].split("/", 1)[0]
                return await digest_svc.get_daily_digest_artifacts_local(int(rid))
            if path.startswith("/api/agent/butler/daily-digests/"):
                rid = path.rsplit("/", 1)[-1]
                return await digest_svc.get_daily_digest_local(int(rid))
            if path.startswith("/api/admin/action-items/stats?"):
                q = path.split("?", 1)[1] if "?" in path else ""
                kind = day = ""
                for part in q.split("&"):
                    if part.startswith("kind="):
                        kind = part.split("=", 1)[1]
                    elif part.startswith("day="):
                        day = part.split("=", 1)[1]
                return await digest_svc.action_items_stats_local(kind=kind, day=day)
            if path.startswith("/api/admin/action-items?"):
                q = path.split("?", 1)[1] if "?" in path else ""
                kind = day = ""
                for part in q.split("&"):
                    if part.startswith("kind="):
                        kind = part.split("=", 1)[1]
                    elif part.startswith("day="):
                        day = part.split("=", 1)[1]
                return await digest_svc.list_action_items_local(kind=kind, day=day)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("local digest/action-items read failed path=%s: %s", path, exc)
            return JSONResponse({"success": False, "message": str(exc)}, status_code=502)

    return await _market_admin_proxy(
        request,
        method,
        path,
        json_body=json_body,
        require_admin_session=not prefer_local_modstore(),
    )


async def _self_maintenance_local_or_proxy(
    request: Request,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
):
    """自维护 loop runtime：优先本地 MODstore :8788，远端 market-proxy 404 时再试本地。"""
    if not path.startswith("/api/ops/self-maintenance/"):
        return None

    from app.application import self_maintenance_app_service as sm_svc
    from app.application.modstore_local_client import prefer_local_modstore
    from app.fastapi_routes.market_account import _authorization_from_request

    authorization = _authorization_from_request(request, json_body or {})

    async def _call_local() -> dict[str, Any] | None:
        if path.startswith("/api/ops/self-maintenance/status"):
            limit = 80
            if "?" in path:
                for part in path.split("?", 1)[1].split("&"):
                    if part.startswith("limit="):
                        try:
                            limit = int(part.split("=", 1)[1])
                        except ValueError:
                            pass
            return await sm_svc.get_runtime_status_local(
                limit=limit,
                authorization=authorization,
            )
        if path == "/api/ops/self-maintenance/governance-review" and method.upper() == "POST":
            note = str((json_body or {}).get("note") or "")
            return await sm_svc.governance_review_local(
                note=note,
                authorization=authorization,
            )
        return None

    if prefer_local_modstore():
        try:
            local_payload = await _call_local()
            if local_payload is not None:
                return local_payload
        except RECOVERABLE_ERRORS as exc:
            logger.warning(
                "local self-maintenance failed path=%s: %s",
                path,
                exc,
            )

    proxied = await _market_admin_proxy(
        request,
        method,
        path,
        json_body=json_body,
    )
    if isinstance(proxied, JSONResponse) and proxied.status_code == 404:
        try:
            local_payload = await _call_local()
            if local_payload is not None:
                return local_payload
        except RECOVERABLE_ERRORS as exc:
            logger.warning(
                "self-maintenance local fallback after upstream 404 path=%s: %s",
                path,
                exc,
            )
    return proxied


async def _remote_duty_health(request: Request) -> dict[str, Any]:
    health_payload = await _market_admin_proxy(request, "GET", "/api/admin/duty-graph/health")
    if isinstance(health_payload, dict):
        return health_payload
    if hasattr(health_payload, "body"):
        try:
            return cast("dict[str, Any]", json.loads(getattr(health_payload, "body", b"") or b"{}"))
        except RECOVERABLE_ERRORS:
            return {}
    return {}


# ---------------------------------------------------------------------------
# 核心功能模块定义（与前端 Sidebar.menuItemsBase 对齐）
# ---------------------------------------------------------------------------
CORE_MODULES = [
    {
        "module_id": "xcmax-admin",
        "display_name": "服务器后台",
        "route": "/xcmax-admin",
        "source": "core",
        "sync_scope": "system",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "chat",
        "display_name": "智能对话",
        "route": "/",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "ai-ecosystem",
        "display_name": "智能生态",
        "route": "/ai-ecosystem",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "model-payment",
        "display_name": "模型服务",
        "route": "/model-payment",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "products",
        "display_name": "人员管理",
        "route": "/products",
        "source": "core",
        "sync_scope": "personnel,departments",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "materials-list",
        "display_name": "班次列表",
        "route": "/materials-list",
        "source": "core",
        "sync_scope": "materials",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "materials",
        "display_name": "排班资源",
        "route": "/materials",
        "source": "core",
        "sync_scope": "materials",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "server-functions",
        "display_name": "服务器功能模块",
        "route": "/server-functions",
        "source": "core",
        "sync_scope": "server,digest,all_hands",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "traditional-mode",
        "display_name": "表格模式",
        "route": "/traditional-mode",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "business-docking",
        "display_name": "业务对接",
        "route": "/business-docking",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "orders",
        "display_name": "考勤单管理",
        "route": "/orders",
        "source": "core",
        "sync_scope": "orders",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "shipment-records",
        "display_name": "考勤记录",
        "route": "/shipment-records",
        "source": "core",
        "sync_scope": "attendance",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "customers",
        "display_name": "部门管理",
        "route": "/customers",
        "source": "core",
        "sync_scope": "departments",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "data-sources",
        "display_name": "数据来源",
        "route": "/data-sources",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "print",
        "display_name": "考勤表打印",
        "route": "/print",
        "source": "core",
        "sync_scope": "templates",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "printer-list",
        "display_name": "打印机列表",
        "route": "/printer-list",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "template-preview",
        "display_name": "模板库",
        "route": "/template-preview",
        "source": "core",
        "sync_scope": "templates",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "settings",
        "display_name": "系统设置",
        "route": "/settings",
        "source": "core",
        "sync_scope": "system",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "tools",
        "display_name": "工具表",
        "route": "/tools",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "approval-hub",
        "display_name": "审批中心",
        "route": "/approval-hub",
        "source": "core",
        "sync_scope": "approvals",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "other-tools",
        "display_name": "员工工作流",
        "route": "/other-tools",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "enterprise-customer-service",
        "display_name": "外部客服",
        "route": "/enterprise-customer-service",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
]


def _collect_mod_modules() -> list[dict[str, Any]]:
    """从 mod_manager 读取已加载的本地 Mod，转换成 XCmax 模块格式。"""
    rows: list[dict[str, Any]] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mgr = get_mod_manager()
        if mgr is None:
            return rows
        registry = getattr(mgr, "_registry", None) or {}
        for mod_id, meta in registry.items() if hasattr(registry, "items") else []:
            name = str(getattr(meta, "name", None) or mod_id).strip()
            version = str(getattr(meta, "version", None) or "").strip()
            rows.append(
                {
                    "module_id": str(mod_id),
                    "display_name": name,
                    "route": f"/mod/{mod_id}",
                    "source": "local",
                    "sync_scope": "module_info",
                    "active": True,
                    "version": version,
                }
            )
    except RECOVERABLE_ERRORS as exc:
        logger.debug("collect_mod_modules failed: %s", exc)
    return rows


def _collect_employee_pack_modules() -> list[dict[str, Any]]:
    """从员工包注册表读取员工包，转换成 XCmax 模块格式。"""
    rows: list[dict[str, Any]] = []
    try:
        from app.infrastructure.mods.employee_registry import EmployeeRegistry
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mgr = get_mod_manager()
        mods_root = getattr(mgr, "mods_root", None) if mgr else None
        if mods_root:
            registry = EmployeeRegistry(mods_root)
            for pack in registry.list_packs():
                pack_id = str(pack.get("id") or "")
                name = str(pack.get("name") or pack_id).strip()
                rows.append(
                    {
                        "module_id": pack_id,
                        "display_name": name,
                        "route": "",
                        "source": "employee",
                        "sync_scope": "employee_pack",
                        "active": True,
                        "version": str(pack.get("version") or ""),
                    }
                )
    except RECOVERABLE_ERRORS as exc:
        logger.debug("collect_employee_pack_modules failed: %s", exc)
    return rows


@router.get("/admin/market/users", response_model=None)
async def admin_list_market_users(request: Request):
    return await _market_admin_proxy(request, "GET", "/api/admin/users")


@router.get("/admin/market/assignable-mods", response_model=None)
async def admin_list_assignable_mods(request: Request):
    return await _market_admin_proxy(request, "GET", "/api/admin/enterprise/assignable-mods")


@router.get("/admin/market/wallets", response_model=None)
async def admin_list_wallets(request: Request):
    """代理远端 ``/api/admin/wallets``，返回所有用户钱包余额。

    远端返回 ``{items: [{id, user_id, balance, updated_at}], total}``。
    """
    limit = request.query_params.get("limit", "500")
    offset = request.query_params.get("offset", "0")
    return await _market_admin_proxy(
        request, "GET", f"/api/admin/wallets?limit={limit}&offset={offset}"
    )


@router.get("/admin/market/users/{user_id}/mods", response_model=None)
async def admin_list_user_mods(request: Request, user_id: int):
    return await _market_admin_proxy(request, "GET", f"/api/admin/users/{user_id}/mods")


@router.post("/admin/market/users/{user_id}/mods/{mod_id}", response_model=None)
async def admin_bind_user_mod(request: Request, user_id: int, mod_id: str):
    from app.application.session_account_meta import audit_admin_action

    out = await _market_admin_proxy(request, "POST", f"/api/admin/users/{user_id}/mods/{mod_id}")
    audit_admin_action(request, "bind_user_mod", target_user_id=user_id, mod_id=mod_id)
    return out


@router.delete("/admin/market/users/{user_id}/mods/{mod_id}", response_model=None)
async def admin_unbind_user_mod(request: Request, user_id: int, mod_id: str):
    from app.application.session_account_meta import audit_admin_action

    out = await _market_admin_proxy(request, "DELETE", f"/api/admin/users/{user_id}/mods/{mod_id}")
    audit_admin_action(request, "unbind_user_mod", target_user_id=user_id, mod_id=mod_id)
    return out


@router.put("/admin/market/users/{user_id}/admin", response_model=None)
async def admin_set_user_admin(
    request: Request,
    user_id: int,
    is_admin: bool = Query(...),
):
    return await _market_admin_proxy(
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
    return await _market_admin_proxy(
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

    gate = _require_market_admin_session(request)
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
    except RECOVERABLE_ERRORS as exc:
        logger.warning("设置用户 profile 失败: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/admin/users/profiles", response_model=None)
async def admin_list_user_profiles(request: Request):
    """返回本地所有用户的账号体系字段映射（按 username 索引）。

    前端拿到远端用户列表后，调此端点合并本地 profile。
    """
    gate = _require_market_admin_session(request)
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
    except RECOVERABLE_ERRORS as exc:
        logger.warning("读取用户 profile 列表失败: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/admin/wechat/groups", response_model=None)
async def admin_list_wechat_groups(
    request: Request,
    keyword: str = Query(default=""),
    limit: int = Query(default=80, ge=1, le=200),
):
    gate = _require_market_admin_session(request)
    if gate is not None:
        return gate
    try:
        from app.services.wechat_group_customer_bridge import list_group_contacts

        rows = list_group_contacts(keyword=keyword or None, limit=limit)
        return {"success": True, "data": rows, "total": len(rows)}
    except RECOVERABLE_ERRORS as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/admin/market/users/{user_id}/wechat-customers", response_model=None)
async def admin_list_user_wechat_customers(request: Request, user_id: int):
    gate = _require_market_admin_session(request)
    if gate is not None:
        return gate
    try:
        from app.services.wechat_group_customer_bridge import get_bindings_for_user

        return {"success": True, "data": get_bindings_for_user(user_id)}
    except RECOVERABLE_ERRORS as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.put("/admin/market/users/{user_id}/wechat-customers", response_model=None)
async def admin_save_user_wechat_customers(
    request: Request,
    user_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
):
    gate = _require_market_admin_session(request)
    if gate is not None:
        return gate
    try:
        from app.services.wechat_group_customer_bridge import save_bindings_for_user

        ids = body.get("contact_ids") or body.get("wechat_contact_ids") or []
        if not isinstance(ids, list):
            ids = []
        result = save_bindings_for_user(user_id, ids)
        return result
    except RECOVERABLE_ERRORS as exc:
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

    gate = _require_market_admin_session(request)
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

    gate = _require_market_admin_session(request)
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


def _inject_digest_api_base(payload: dict[str, Any], base: str) -> dict[str, Any]:
    """在 ``data`` 中写入 ``digest_api_base``，供 XCmax 页眉与「打开市场」与解锁校验同源提示。"""
    data = payload.get("data")
    if isinstance(data, dict):
        data["digest_api_base"] = base
    return payload


@router.get("/admin/digest-identity", response_model=None)
async def get_digest_identity(request: Request):
    """透传远端「身份校验码」摘要；与修茈市场 ``verify-admin-digest-code`` 同一实现源。"""
    from app.fastapi_routes.market_account import _market_base_url

    api_base = _market_base_url()
    out = await _market_admin_proxy(
        request,
        "GET",
        "/api/xcmax/admin/digest-identity",
    )
    # 旧版或未挂载 xcmax_admin 的 MODstore 会对该路径返回 404；此处降级为 200 + 空 code，
    # 与前端 ServerFunctionsView「摘要 HTML 后备」一致，并避免控制台对可选接口报红。
    if isinstance(out, JSONResponse) and out.status_code == 404:
        logger.debug(
            "digest-identity: upstream 404, returning empty code payload for HTML fallback"
        )
        return {
            "success": True,
            "data": {
                "code": "",
                "expires_at": "",
                "valid": False,
                "daily_digest_id": None,
                "digest_api_base": api_base,
            },
        }
    if isinstance(out, dict):
        return _inject_digest_api_base(out, api_base)
    return out


@router.get("/release-train", response_model=None)
async def get_release_train():
    """release_train 四段 SSOT 快照（全景页 live 刷新，无需登录）。"""
    return {"success": True, "data": _release_train_snapshot()}


@router.get("/local/duty-graph/health", response_model=None)
async def local_duty_graph_health(request: Request):
    """本机编制图 health（不代理远端 MODstore）。"""
    from app.application.local_duty_graph_health import build_local_duty_graph_health
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    return build_local_duty_graph_health()


@router.get("/local/ops/self-maintenance/status", response_model=None)
async def local_self_maintenance_status(
    request: Request,
    limit: int = Query(default=80, ge=1, le=300),
):
    """本机自维护 loop runtime 状态（直连 MODstore :8788）。"""
    from app.application import self_maintenance_app_service as sm_svc
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.fastapi_routes.market_account import _authorization_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    authorization = _authorization_from_request(request, {})
    try:
        return await sm_svc.get_runtime_status_local(
            limit=limit,
            authorization=authorization,
        )
    except RECOVERABLE_ERRORS as exc:
        return JSONResponse(
            {"success": False, "message": str(exc)},
            status_code=502,
        )


@router.post("/local/ops/self-maintenance/governance-review", response_model=None)
async def local_self_maintenance_governance_review(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """本机自维护 loop 治理审计复核。"""
    from app.application import self_maintenance_app_service as sm_svc
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request
    from app.fastapi_routes.market_account import _authorization_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    authorization = _authorization_from_request(request, body if isinstance(body, dict) else {})
    try:
        return await sm_svc.governance_review_local(
            note=str(body.get("note") or ""),
            authorization=authorization,
        )
    except RECOVERABLE_ERRORS as exc:
        return JSONResponse(
            {"success": False, "message": str(exc)},
            status_code=502,
        )


@router.get("/local/employee-cron/jobs", response_model=None)
async def local_employee_cron_jobs(request: Request):
    """本机员工定时任务列表（管理端点火状态）。"""
    from app.application.employee_runtime.scheduler import get_employee_cron_jobs
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    return {"success": True, "source": "local", "jobs": get_employee_cron_jobs()}


@router.post("/local/employee-cron/jobs/{job_id}/run", response_model=None)
async def local_employee_cron_job_run(
    request: Request,
    job_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """手动触发本机员工定时任务，供管理端立即验证 daily 员工是否能跑。"""
    from app.application.employee_runtime.scheduler import run_employee_cron_job
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    sid = _session_id_from_request(request)
    if not sid:
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    payload = body.get("input_data") if isinstance(body.get("input_data"), dict) else {}
    task = str(body.get("task") or "").strip() or None
    try:
        user_id = int(body.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    result = run_employee_cron_job(
        job_id,
        task=task,
        input_data=payload,
        user_id=user_id,
        workspace_root=str(body.get("workspace_root") or "").strip() or None,
        session_id=str(body.get("session_id") or sid),
        source="manual",
    )
    if not result.get("success") and "unknown employee cron job" in str(result.get("error") or ""):
        return JSONResponse(result, status_code=404)
    return result


@router.get("/local/employees/{employee_id}/status", response_model=None)
async def local_employee_status(request: Request, employee_id: str):
    """本机员工包部署态与执行统计（编制图 Phase2，不代理 MODstore）。"""
    from app.application.local_duty_graph_health import build_local_employee_status
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    pid = str(employee_id or "").strip()
    if not pid:
        return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
    return build_local_employee_status(pid)


@router.post("/local/employees/{employee_id}/execute", response_model=None)
async def local_employee_execute(
    request: Request,
    employee_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """管理端本机员工执行入口：绕开远端代理，直接调用 FHD employee_runtime。"""
    from app.application.employee_runtime.executor import execute_employee_task_local
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    sid = _session_id_from_request(request)
    if not sid:
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    pid = str(employee_id or "").strip()
    if not pid:
        return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
    task = str(body.get("task") or "").strip()
    if not task:
        return JSONResponse({"success": False, "message": "task 必填"}, status_code=400)
    raw_input = body.get("input_data")
    if raw_input is not None and not isinstance(raw_input, dict):
        return JSONResponse({"success": False, "message": "input_data 必须是对象"}, status_code=400)
    payload = dict(raw_input or {})
    for key in ("approved_write", "allow_write", "write_token", "approval_token"):
        if key in body and key not in payload:
            payload[key] = body[key]
    payload.setdefault("trigger", "admin_execute")
    try:
        user_id = int(body.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    result = execute_employee_task_local(
        pid,
        task,
        payload,
        user_id=user_id,
        workspace_root=str(body.get("workspace_root") or "").strip() or None,
        session_id=str(body.get("session_id") or sid),
    )
    return {
        "success": bool(result.get("success")),
        "source": "local",
        "data": result,
    }


@router.get("/local/employees/{employee_id}/manifest", response_model=None)
async def local_employee_manifest(request: Request, employee_id: str):
    """读本机 mods/_employees/<id>/manifest.json（编制图 LLM/依赖解析）。"""
    from app.application.local_duty_graph_health import read_local_employee_manifest
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    pid = str(employee_id or "").strip()
    if not pid:
        return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
    row = read_local_employee_manifest(pid)
    if not row:
        return JSONResponse(
            {"success": False, "message": f"员工包不存在: {pid}"},
            status_code=404,
        )
    return row


@router.get("/admin/modules", response_model=None)
async def list_modules():
    """获取 XCmax 模块注册表（核心 + 本地 Mod + 员工包）。"""
    modules: list[dict[str, Any]] = list(CORE_MODULES)
    modules.extend(_collect_mod_modules())
    modules.extend(_collect_employee_pack_modules())
    return {"success": True, "data": modules, "total": len(modules)}


@router.get("/admin/daily-digests", response_model=None)
async def list_daily_digests(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """从服务器读取已保存的每日摘要邮件副本。"""
    return await _digest_local_or_proxy(
        request,
        "GET",
        f"/api/agent/butler/daily-digests?limit={limit}&offset={offset}",
    )


@router.get("/admin/daily-digests/{record_id}", response_model=None)
async def get_daily_digest(request: Request, record_id: int):
    """从服务器读取单条每日摘要完整正文。"""
    return await _digest_local_or_proxy(
        request,
        "GET",
        f"/api/agent/butler/daily-digests/{record_id}",
    )


@router.get("/admin/daily-digests/{record_id}/artifacts", response_model=None)
async def get_daily_digest_artifacts(request: Request, record_id: int):
    """日更各阶段产物清单（截图 / PPT / digest HTML 等）。"""
    return await _digest_local_or_proxy(
        request,
        "GET",
        f"/api/agent/butler/daily-digests/{record_id}/artifacts",
    )


@router.get("/admin/action-items", response_model=None)
async def list_action_items(
    request: Request,
    kind: str = Query("", description="patch | update"),
    day: str = Query("", description="YYYY-MM-DD"),
):
    """Vibe 预备双清单结构化条目（patch / update）。"""
    q = []
    if kind:
        q.append(f"kind={kind}")
    if day:
        q.append(f"day={day}")
    query = ("?" + "&".join(q)) if q else ""
    return await _digest_local_or_proxy(request, "GET", f"/api/admin/action-items{query}")


@router.get("/admin/action-items/stats", response_model=None)
async def action_items_stats(
    request: Request,
    kind: str = Query("", description="patch | update"),
    day: str = Query("", description="YYYY-MM-DD"),
):
    """行动条目完成率 / 分布。"""
    q = []
    if kind:
        q.append(f"kind={kind}")
    if day:
        q.append(f"day={day}")
    query = ("?" + "&".join(q)) if q else ""
    return await _digest_local_or_proxy(request, "GET", f"/api/admin/action-items/stats{query}")


@router.post("/admin/daily-digests/{record_id}/vibe-prep/sessions", response_model=None)
async def start_digest_vibe_prep_session(
    request: Request,
    record_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """基于每日摘要生成 Vibe-Coding 预备 Markdown（更新 + 补丁）后台会话。"""
    return await _market_admin_proxy(
        request,
        "POST",
        f"/api/agent/butler/daily-digests/{record_id}/vibe-prep/sessions",
        json_body=body,
    )


@router.post("/admin/daily-digests/{record_id}/line-execute", response_model=None)
async def start_digest_line_execute(
    request: Request,
    record_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """Phase A：消费 P-S（或指定产线）补丁清单并派发员工子任务。"""
    return await _market_admin_proxy(
        request,
        "POST",
        f"/api/agent/butler/daily-digests/{record_id}/line-execute",
        json_body=body,
    )


@router.get("/admin/digest-vibe-prep/sessions/{session_id}", response_model=None)
async def get_digest_vibe_prep_session(request: Request, session_id: str):
    """轮询 Vibe 预备文档生成会话（复用 workbench session 存储）。"""
    sid = "".join(ch for ch in str(session_id or "") if ch.isalnum())[:64]
    if not sid:
        return JSONResponse({"success": False, "message": "session_id 必填"}, status_code=400)
    return await _market_admin_proxy(
        request,
        "GET",
        f"/api/workbench/sessions/{sid}",
    )


@router.post("/admin/all-hands-report/sessions", response_model=None)
async def start_all_hands_report_session(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """启动服务器员工大会后台会话，返回远端 session_id。"""
    return await _market_admin_proxy(
        request,
        "POST",
        "/api/agent/butler/all-hands-report/sessions",
        json_body=body,
    )


@router.get("/admin/all-hands-report/sessions/{session_id}", response_model=None)
async def get_all_hands_report_session(request: Request, session_id: str):
    """轮询服务器员工大会后台会话。"""
    sid = "".join(ch for ch in str(session_id or "") if ch.isalnum())[:64]
    if not sid:
        return JSONResponse({"success": False, "message": "session_id 必填"}, status_code=400)
    return await _market_admin_proxy(
        request,
        "GET",
        f"/api/workbench/sessions/{sid}",
    )


def _probe_remote_health_sync() -> dict[str, Any]:
    """同步探测远端 HTTP /api/health；供 asyncio.to_thread 调用，避免阻塞事件循环。"""
    remote_url = f"http://{REMOTE_HOST}:{REMOTE_PORT}/api/health"
    t0 = time.time()
    try:
        req = urllib.request.Request(remote_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            latency_ms = round((time.time() - t0) * 1000)
            body = json.loads(resp.read(4096).decode("utf-8", errors="replace"))
            return {
                "success": True,
                "data": {
                    "reachable": True,
                    "latency_ms": latency_ms,
                    "version": body.get("version") or body.get("git_sha") or "",
                    "deploy_time": body.get("timestamp") or "",
                    "host": REMOTE_HOST,
                    "port": REMOTE_PORT,
                },
            }
    except RECOVERABLE_ERRORS as exc:
        logger.debug("remote_status probe failed: %s", exc)
        return {
            "success": True,
            "data": {
                "reachable": False,
                "latency_ms": None,
                "version": "",
                "deploy_time": "",
                "host": REMOTE_HOST,
                "port": REMOTE_PORT,
                "error": str(exc),
            },
        }


@router.get("/admin/remote-status", response_model=None)
async def remote_status():
    """探测远端服务器连接状态（轻量 HTTP GET /api/health）。"""
    return await asyncio.to_thread(_probe_remote_health_sync)


# ---------------------------------------------------------------------------
# 运维闭环代理（MODstore AdminDutyEmployees / duty-graph / orchestrate）
# ---------------------------------------------------------------------------


@router.get("/ops/duty-health", response_model=None)
async def ops_duty_health(request: Request):
    from app.application.ops_closure_status import build_ops_closure_status

    remote = await _remote_duty_health(request)
    closure = build_ops_closure_status(remote if isinstance(remote, dict) else {})
    if not isinstance(remote, dict):
        return closure.get("remote_health") or {
            "success": False,
            "staffing": closure.get("staffing") or {},
        }
    merged = {**remote, "staffing": closure.get("staffing") or remote.get("staffing") or {}}
    merged["planned_employee_ids"] = closure.get("planned_employee_ids")
    merged["registered_employee_ids"] = closure.get("registered_employee_ids")
    merged["planned_local_installed_count"] = closure.get("planned_local_installed_count")
    merged["extra_local_employee_pack_ids"] = closure.get("extra_local_employee_pack_ids")
    return merged


@router.post("/ops/dispatch", response_model=None)
async def ops_dispatch(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    payload = dict(body or {})
    payload.setdefault("dispatch_source", "desktop")
    return await _market_admin_proxy(
        request,
        "POST",
        "/api/ops/orchestrate/async",
        json_body=payload,
    )


@router.get("/ops/jobs", response_model=None)
async def ops_jobs(request: Request, limit: int = Query(20, ge=1, le=100)):
    return await _market_admin_proxy(
        request,
        "GET",
        f"/api/ops/orchestrate/jobs?limit={limit}",
    )


@router.get("/ops/jobs/{job_id}", response_model=None)
async def ops_job_detail(request: Request, job_id: str):
    jid = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in "-_")[:128]
    if not jid:
        return JSONResponse({"success": False, "message": "job_id 无效"}, status_code=400)
    return await _market_admin_proxy(request, "GET", f"/api/ops/orchestrate/jobs/{jid}")


@router.post("/ops/duty-runs", response_model=None)
async def ops_duty_runs(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    return await _market_admin_proxy(
        request,
        "POST",
        "/api/admin/duty-graph/runs",
        json_body=body,
    )


@router.get("/ops/duty-runs/{run_id}", response_model=None)
async def ops_duty_run_detail(request: Request, run_id: int):
    if run_id <= 0:
        return JSONResponse({"success": False, "message": "run_id 无效"}, status_code=400)
    return await _market_admin_proxy(request, "GET", f"/api/admin/duty-graph/runs/{run_id}")


@router.get("/ops/closure-status", response_model=None)
async def ops_closure_status(request: Request):
    from app.application.ops_closure_status import build_ops_closure_status

    gate = _require_market_admin_session(request)
    if gate is not None:
        return gate
    data = build_ops_closure_status(await _remote_duty_health(request))
    return {"success": True, "data": data}


@router.post("/ops/staffing/onboard", response_model=None)
async def ops_staffing_onboard(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    """将编制缺岗员工登记到 MODstore Catalog（代理 yuangon-onboard/run）。"""
    payload: dict[str, Any] = {
        "dry_run": bool(body.get("dry_run", False)),
        "force": bool(body.get("force", False)),
    }
    pkg_ids = body.get("employee_ids") or body.get("pkg_ids")
    if isinstance(pkg_ids, list):
        payload["pkg_ids"] = ",".join(str(x).strip() for x in pkg_ids if str(x).strip())
    elif isinstance(pkg_ids, str) and pkg_ids.strip():
        payload["pkg_ids"] = pkg_ids.strip()
    return await _market_admin_proxy(
        request,
        "POST",
        "/api/admin/yuangon-onboard/run",
        json_body=payload,
    )


@router.post("/ops/staffing/install-local", response_model=None)
async def ops_staffing_install_local(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    """从 MODstore Catalog 安装 employee_pack 到本地 mods/_employees/。"""
    gate = _require_market_admin_session(request)
    if gate is not None:
        return gate
    pkg_id = str(body.get("employee_id") or body.get("pkg_id") or "").strip()
    if not pkg_id:
        return JSONResponse({"success": False, "message": "employee_id 必填"}, status_code=400)
    try:
        from app.fastapi_routes.mod_store_routes import _install_from_catalog

        result = await _install_from_catalog(pkg_id, "", activate=True)
        if hasattr(result, "model_dump"):
            data = result.model_dump()
        elif isinstance(result, dict):
            data = result
        else:
            data = {"result": str(result)}
        return {"success": bool(data.get("success", True)), "data": data}
    except RECOVERABLE_ERRORS as exc:
        logger.warning("ops_staffing_install_local failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.post("/ops/staffing/close-gap", response_model=None)
async def ops_staffing_close_gap(
    request: Request, body: dict[str, Any] = Body(default_factory=dict)
):
    """补登记编制缺岗并安装本地缺失 employee_pack（桌面一键闭环）。"""
    from app.application.ops_closure_status import build_ops_closure_status

    gate = _require_market_admin_session(request)
    if gate is not None:
        return gate

    before = build_ops_closure_status(await _remote_duty_health(request))
    onboard_result: dict[str, Any] | None = None
    missing_remote = list(before.get("missing_remote_employees") or [])
    if missing_remote and not bool(body.get("skip_onboard", False)):
        onboard_result = await _market_admin_proxy(
            request,
            "POST",
            "/api/admin/yuangon-onboard/run",
            json_body={"pkg_ids": ",".join(missing_remote)},
        )
        if isinstance(onboard_result, JSONResponse):
            return onboard_result

    mid = build_ops_closure_status(await _remote_duty_health(request))
    install_results: list[dict[str, Any]] = []
    if not bool(body.get("skip_install", False)):
        from app.fastapi_routes.mod_store_routes import _install_from_catalog

        for employee_id in list(mid.get("missing_local_employee_packs") or []):
            try:
                result = await _install_from_catalog(employee_id, "", activate=True)
                if hasattr(result, "model_dump"):
                    data = result.model_dump()
                elif isinstance(result, dict):
                    data = result
                else:
                    data = {"result": str(result)}
                install_results.append(
                    {
                        "employee_id": employee_id,
                        "success": bool(data.get("success", True)),
                        "message": str(data.get("message") or ""),
                    }
                )
            except RECOVERABLE_ERRORS as exc:
                install_results.append(
                    {"employee_id": employee_id, "success": False, "message": str(exc)}
                )

    after = build_ops_closure_status(await _remote_duty_health(request))
    onboard_ok = True
    if isinstance(onboard_result, dict):
        onboard_ok = bool(onboard_result.get("success", True))
    return {
        "success": True,
        "data": {
            "before": before,
            "after": after,
            "onboard": onboard_result,
            "onboard_ok": onboard_ok,
            "install_results": install_results,
        },
    }


@router.get("/sync/status", response_model=None)
async def sync_status():
    """获取双向同步健康状态。"""
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
        info = db.get_status()
        return {"success": True, "data": info}
    except RECOVERABLE_ERRORS as exc:
        logger.debug("sync_status db read failed: %s", exc)
        return {
            "success": True,
            "data": {
                "healthy": False,
                "local_cursor": None,
                "remote_cursor": None,
                "outbox_count": 0,
                "last_sync_at": None,
                "conflict_count": 0,
                "note": "同步数据库尚未初始化，请先完成 sync-foundation 阶段。",
            },
        }


@router.post("/sync/push", response_model=None)
async def sync_push():
    """触发本地 outbox 向服务器推送。"""
    try:
        from app.application.xcmax_sync_app import push_outbox

        result = push_outbox(remote_host=REMOTE_HOST, remote_port=REMOTE_PORT)
        return {"success": True, "data": result}
    except RECOVERABLE_ERRORS as exc:
        logger.warning("sync_push failed: %s", exc)
        return JSONResponse(
            {"success": False, "message": f"推送失败: {exc}"},
            status_code=500,
        )


@router.get("/sync/changes", response_model=None)
async def sync_changes(since_cursor: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    """获取变更日志（支持断线补拉）。"""
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
        rows = db.get_changes(since_cursor=since_cursor, limit=limit)
        return {"success": True, "data": rows, "count": len(rows)}
    except RECOVERABLE_ERRORS as exc:
        logger.debug("sync_changes read failed: %s", exc)
        return {"success": True, "data": [], "count": 0, "note": str(exc)}


@router.post("/sync/receive", response_model=None)
async def sync_receive(body: dict | list):
    """接收远端推来的变更，写入 inbox，立即尝试应用，并记录审计日志。"""
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
        items = body if isinstance(body, list) else [body]
        written = db.enqueue_inbox(items)
        try:
            from app.application.xcmax_sync_app import apply_inbox

            result = apply_inbox(limit=len(items) + 50)
        except RECOVERABLE_ERRORS as ae:
            result = {"applied": 0, "error": str(ae)}
        # 写审计事件
        try:
            from app.mod_sdk.audit import write_audit_event

            write_audit_event(
                actor=None,
                action="xcmax.sync.receive",
                payload={"received": written, "apply": result},
            )
        except RECOVERABLE_ERRORS:
            pass
        return {"success": True, "received": written, "apply_result": result}
    except RECOVERABLE_ERRORS as exc:
        logger.warning("sync_receive failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.post("/sync/pull", response_model=None)
async def sync_pull():
    """主动从远端拉取增量变更并应用到本地。"""
    try:
        from app.application.xcmax_sync_app import apply_inbox, pull_from_remote

        pull_result = pull_from_remote(remote_host=REMOTE_HOST, remote_port=REMOTE_PORT)
        apply_result = apply_inbox()
        return {"success": True, "data": {"pull": pull_result, "apply": apply_result}}
    except RECOVERABLE_ERRORS as exc:
        logger.warning("sync_pull failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# 专用实时同步流 (SSE) — 独立于 AI chat streaming
# ---------------------------------------------------------------------------

SYNC_POLL_INTERVAL_S = float(os.environ.get("XCMAX_SYNC_POLL_S", "10"))


async def _sync_sse_generator(request: Request, since_cursor: int):
    """持续产生 SSE 事件：每隔 SYNC_POLL_INTERVAL_S 秒检查一次本地变更日志。"""
    import json as _json

    cursor = since_cursor
    connected = _json.dumps({"type": "connected", "cursor": since_cursor}, ensure_ascii=False)
    yield f"data: {connected}\n\n"
    while True:
        if await request.is_disconnected():
            break
        try:
            from app.db.xcmax_sync import SyncDb

            db = SyncDb()
            rows = db.get_changes(since_cursor=cursor, limit=50)
            if rows:
                cursor = rows[-1]["id"]
                data = _json.dumps(
                    {"cursor": cursor, "changes": rows}, ensure_ascii=False, default=str
                )
                yield f"data: {data}\n\n"
            else:
                status = db.get_status()
                heartbeat = _json.dumps(
                    {"type": "heartbeat", "cursor": cursor, "status": status},
                    ensure_ascii=False,
                    default=str,
                )
                yield f"data: {heartbeat}\n\n"
        except RECOVERABLE_ERRORS as exc:
            err = _json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
            yield f"data: {err}\n\n"
        await asyncio.sleep(SYNC_POLL_INTERVAL_S)


@router.get("/sync/conflicts", response_model=None)
async def list_conflicts(limit: int = Query(50, ge=1, le=500)):
    """列出 inbox 中待处理的冲突条目。"""
    try:
        from app.services.admin_sync_service import list_sync_conflicts

        data = list_sync_conflicts(limit=limit)
        return {"success": True, "data": data, "count": len(data)}
    except Exception as exc:  # noqa: BLE001
        return {"success": True, "data": [], "count": 0, "note": str(exc)}


@router.post("/sync/conflicts/{inbox_id}/resolve", response_model=None)
async def resolve_conflict(inbox_id: int, body: dict):
    """手动解决指定冲突（action: 'apply' | 'skip'）。"""
    action = str(body.get("action") or "skip").strip()
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
        if action == "apply":
            from app.application.xcmax_sync_app import entity_appliers
            from app.services.admin_sync_service import fetch_inbox_row

            row = fetch_inbox_row(inbox_id)
            if row:
                applier = entity_appliers().get(row["entity_type"])
                if applier:
                    applier(row)
            db.mark_inbox_applied(inbox_id)
        else:
            from app.services.admin_sync_service import mark_inbox_skipped

            mark_inbox_skipped(inbox_id)
        return {"success": True, "inbox_id": inbox_id, "action": action}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/sync/stream", response_model=None)
async def sync_stream(
    request: Request,
    since_cursor: int = Query(0, ge=0),
):
    """专用 SSE 同步流：服务端实时推送本地变更（与 AI chat streaming 完全分离）。

    客户端监听示例：
        const es = new EventSource('/api/xcmax/sync/stream?since_cursor=0')
        es.onmessage = e => { const d = JSON.parse(e.data); console.log(d) }
    """
    return StreamingResponse(
        _sync_sse_generator(request, since_cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _xcmax_market_proxy_impl(request: Request, subpath: str):
    """编制图 LLM / 员工执行等：经会话市场 token 转发至 MODstore ``/api/...``。"""
    method = request.method.upper()
    json_body: dict[str, Any] | None = None
    if method in {"POST", "PUT", "PATCH"}:
        try:
            body = await request.json()
            json_body = body if isinstance(body, dict) else None
        except RECOVERABLE_ERRORS:
            json_body = None
    api_path = f"/api/{str(subpath or '').lstrip('/')}"
    if api_path.startswith("/api/ops/self-maintenance/"):
        return await _self_maintenance_local_or_proxy(
            request,
            method,
            api_path,
            json_body=json_body,
        )
    return await _market_admin_proxy(request, method, api_path, json_body=json_body)


def _register_market_proxy_method(method: str) -> None:
    async def endpoint(request: Request, subpath: str):
        return await _xcmax_market_proxy_impl(request, subpath)

    endpoint.__name__ = f"xcmax_market_proxy_{method.lower()}"
    endpoint.__qualname__ = endpoint.__name__
    router.add_api_route(
        "/market-proxy/{subpath:path}",
        endpoint,
        methods=[method],
        response_model=None,
    )


for _market_proxy_method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
    _register_market_proxy_method(_market_proxy_method)


# ---------------------------------------------------------------------------
# Token 用量聚合（本地账本 + Cursor CLI + Codex JSONL + Trae state.vscdb）
# ---------------------------------------------------------------------------


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _collect_local_ledger() -> dict[str, Any]:
    """FHD 本地 token 账本（model_usage_ledger.json）。"""
    try:
        from app.infrastructure.billing.model_usage import list_model_usage_entries

        entries = list_model_usage_entries(limit=500)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        return {"available": False, "reason": f"读取账本失败: {exc}"}
    prompt = sum(_to_int(e.get("prompt_tokens")) for e in entries)
    completion = sum(_to_int(e.get("completion_tokens")) for e in entries)
    total = sum(_to_int(e.get("total_tokens")) for e in entries)
    cost = sum(_to_float(e.get("cost_units")) for e in entries)
    by_model: dict[str, dict[str, Any]] = {}
    for e in entries:
        key = f"{e.get('provider', '?')}/{e.get('model', '?')}"
        slot = by_model.setdefault(key, {"total": 0, "count": 0, "cost": 0.0})
        slot["total"] += _to_int(e.get("total_tokens"))
        slot["count"] += 1
        slot["cost"] += _to_float(e.get("cost_units"))
    return {
        "available": True,
        "source": "FHD 本地账本",
        "records": len(entries),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cost_units": cost,
        "by_model": dict(sorted(by_model.items(), key=lambda x: -x[1]["total"])),
    }


def _collect_cursor_usage() -> dict[str, Any]:
    """Cursor 用量（cursor-usage CLI）。"""
    import shutil
    import subprocess

    cli = shutil.which("cursor-usage") or str(
        os.path.expanduser("~/Library/Python/3.9/bin/cursor-usage")
    )
    if not os.path.exists(cli):
        return {"available": False, "reason": f"cursor-usage CLI 不存在: {cli}"}
    try:
        proc = subprocess.run(
            [cli, "--json", "--days", "30"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        return {"available": False, "reason": f"执行失败: {exc}"}
    if proc.returncode != 0:
        return {"available": False, "reason": f"exit={proc.returncode}"}
    try:
        raw = json.loads(proc.stdout)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        return {"available": False, "reason": f"JSON 解析失败: {exc}"}
    aggs = raw.get("aggregations", []) if isinstance(raw, dict) else []
    total_input = sum(_to_int(a.get("inputTokens")) for a in aggs)
    total_output = sum(_to_int(a.get("outputTokens")) for a in aggs)
    total_cache_read = sum(_to_int(a.get("cacheReadTokens")) for a in aggs)
    total_cache_write = sum(_to_int(a.get("cacheWriteTokens")) for a in aggs)
    total_cents = sum(_to_float(a.get("totalCents")) for a in aggs)
    by_model: dict[str, dict[str, Any]] = {}
    for a in aggs:
        m = a.get("modelIntent", "unknown")
        slot = by_model.setdefault(
            m, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cents": 0.0}
        )
        slot["input"] += _to_int(a.get("inputTokens"))
        slot["output"] += _to_int(a.get("outputTokens"))
        slot["cache_read"] += _to_int(a.get("cacheReadTokens"))
        slot["cache_write"] += _to_int(a.get("cacheWriteTokens"))
        slot["cents"] += _to_float(a.get("totalCents"))
    return {
        "available": True,
        "source": "Cursor (cursor-usage CLI, 最近 30 天)",
        "aggregations": len(aggs),
        "prompt_tokens": total_input,
        "completion_tokens": total_output,
        "cache_read_tokens": total_cache_read,
        "cache_write_tokens": total_cache_write,
        "total_tokens": total_input + total_output + total_cache_read + total_cache_write,
        "cost_cents": total_cents,
        "by_model": dict(
            sorted(
                by_model.items(),
                key=lambda x: -(x[1]["input"] + x[1]["output"] + x[1]["cache_read"]),
            )
        ),
    }


def _collect_codex_usage() -> dict[str, Any]:
    """Codex 用量（~/.codex/archived_sessions/*.jsonl）。"""
    archived = os.path.expanduser("~/.codex/archived_sessions")
    if not os.path.isdir(archived):
        return {"available": False, "reason": f"目录不存在: {archived}"}
    jsonl_files = sorted(
        f for f in (os.path.join(archived, x) for x in os.listdir(archived)) if f.endswith(".jsonl")
    )
    total_input = total_cached = total_output = total_reasoning = total_total = 0
    by_model: dict[str, dict[str, Any]] = {}
    session_count = 0
    for fpath in jsonl_files:
        session_model = "unknown"
        has_token = False
        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    try:
                        evt = json.loads(line)
                    except RECOVERABLE_ERRORS:
                        continue
                    if evt.get("type") == "session_meta":
                        payload = evt.get("payload") or {}
                        session_model = (
                            payload.get("model") or payload.get("model_provider") or "unknown"
                        )
                    if (
                        evt.get("type") == "event_msg"
                        and (evt.get("payload") or {}).get("type") == "token_count"
                    ):
                        info = (evt.get("payload") or {}).get("info") or {}
                        usage = info.get("total_token_usage") or {}
                        i = _to_int(usage.get("input_tokens"))
                        c = _to_int(usage.get("cached_input_tokens"))
                        o = _to_int(usage.get("output_tokens"))
                        r = _to_int(usage.get("reasoning_output_tokens"))
                        t = _to_int(usage.get("total_tokens"))
                        total_input += i
                        total_cached += c
                        total_output += o
                        total_reasoning += r
                        total_total += t
                        slot = by_model.setdefault(
                            session_model,
                            {
                                "input": 0,
                                "cached": 0,
                                "output": 0,
                                "reasoning": 0,
                                "total": 0,
                                "count": 0,
                            },
                        )
                        slot["input"] += i
                        slot["cached"] += c
                        slot["output"] += o
                        slot["reasoning"] += r
                        slot["total"] += t
                        slot["count"] += 1
                        has_token = True
        except RECOVERABLE_ERRORS:
            continue
        if has_token:
            session_count += 1
    return {
        "available": True,
        "source": "Codex (~/.codex/archived_sessions)",
        "jsonl_files": len(jsonl_files),
        "sessions_with_tokens": session_count,
        "prompt_tokens": total_input,
        "cached_tokens": total_cached,
        "completion_tokens": total_output,
        "reasoning_tokens": total_reasoning,
        "total_tokens": total_total,
        "by_model": dict(sorted(by_model.items(), key=lambda x: -x[1]["total"])),
    }


def _collect_trae_usage() -> dict[str, Any]:
    """Trae 用量（state.vscdb，API 403 无法获取精确 token）。"""
    import sqlite3

    state_db = os.path.expanduser(
        "~/Library/Application Support/Trae CN/User/globalStorage/state.vscdb"
    )
    if not os.path.exists(state_db):
        return {"available": False, "reason": f"state.vscdb 不存在: {state_db}"}
    total_turns = 0
    turn_details: dict[str, int] = {}
    current_models: Any = None
    available_models_count = 0
    try:
        conn = sqlite3.connect(state_db)
        cur = conn.cursor()
        cur.execute(
            "SELECT key, value FROM ItemTable WHERE key LIKE 'ai.chat.feedback%.accumulatedTurns'"
        )
        for key, value in cur.fetchall():
            n = _to_int(value)
            total_turns += n
            turn_details[key] = n
        cur.execute(
            "SELECT value FROM ItemTable WHERE key LIKE '%sessionRelation:globalModelMap%' LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            try:
                current_models = json.loads(row[0])
            except RECOVERABLE_ERRORS:
                current_models = None
        cur.execute("SELECT value FROM ItemTable WHERE key LIKE '%model_list_map%' LIMIT 1")
        row = cur.fetchone()
        if row:
            try:
                m = json.loads(row[0])
                if isinstance(m, dict):
                    for _mode, models in m.items():
                        if isinstance(models, list):
                            available_models_count += len(models)
            except RECOVERABLE_ERRORS:
                pass
        conn.close()
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        return {"available": False, "reason": f"读取 state.vscdb 失败: {exc}"}
    # Trae API 被 403 拦截，用轮次估算 token 用量
    # IDE AI 助手 Composer/Agent 模式每轮：prompt ~10000000（含多文件代码上下文+历史对话缓存）
    # + completion ~500000（AI 回复+代码生成）
    # 参照 Cursor 52 亿/30 天、Codex 84 亿/5 会话校准
    est_prompt_per_turn = 10_000_000
    est_completion_per_turn = 500_000
    est_prompt = total_turns * est_prompt_per_turn
    est_completion = total_turns * est_completion_per_turn
    est_total = est_prompt + est_completion
    return {
        "available": True,
        "source": "Trae (state.vscdb + 轮次估算)",
        "note": f"Trae API 被 WAF 403 拦截，按 {total_turns} 轮 × 1050 万 tokens/轮 估算"
        f"（prompt 1000 万 + completion 50 万）",
        "estimated": True,
        "total_chat_turns": total_turns,
        "turn_details": turn_details,
        "current_models": current_models,
        "available_models_count": available_models_count,
        "prompt_tokens": est_prompt,
        "completion_tokens": est_completion,
        "total_tokens": est_total,
    }


def _estimate_cost_usd(source_key: str, data: dict[str, Any]) -> float:
    """估算费用（美元）。Cursor 用精确 cents，其余按 API 单价估算。"""
    if not data.get("available"):
        return 0.0
    if source_key == "cursor":
        return _to_int(data.get("cost_cents")) / 100.0
    if source_key == "codex":
        # GPT-5: input $5/1M (uncached), $1.25/1M (cached), output+reasoning $10/1M
        prompt = _to_int(data.get("prompt_tokens"))
        cached = _to_int(data.get("cache_read_tokens"))
        output = _to_int(data.get("completion_tokens"))
        reasoning = _to_int(data.get("reasoning_tokens"))
        uncached = max(0, prompt - cached)
        return (
            uncached * 5 / 1_000_000
            + cached * 1.25 / 1_000_000
            + (output + reasoning) * 10 / 1_000_000
        )
    if source_key == "trae":
        # GLM-5.1: input ¥5/1M, output ¥5/1M, 1 USD ≈ 7.2 CNY
        prompt = _to_int(data.get("prompt_tokens"))
        output = _to_int(data.get("completion_tokens"))
        return (prompt + output) * 5 / 7.2 / 1_000_000
    if source_key == "local":
        return _to_int(data.get("cost_units")) / 100.0
    if source_key == "mimo":
        # mimo 套餐制，Credits 额度内不再单独计费
        return 0.0
    return 0.0


def _collect_mimo_usage() -> dict[str, Any]:
    """采集 mimo（小米 MiMo）用量。手动输入静态数据。"""
    # 用户手动提供：实际 token 80,621,905，Credits 额度 38,000,000,000
    credits_used = 22_070_888_859
    credits_quota = 38_000_000_000
    actual_tokens = 80_621_905
    usage_pct = round(credits_used / credits_quota * 100, 1) if credits_quota else 0
    return {
        "available": True,
        "source": "mimo (小米 MiMo, 手动输入)",
        "note": f"Credits {credits_used:,} / {credits_quota:,}（{usage_pct}%），"
        f"实际 token {actual_tokens:,}",
        "total_tokens": actual_tokens,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "credits_used": credits_used,
        "credits_quota": credits_quota,
        "usage_percent": usage_pct,
        "estimated": True,
    }


def _build_token_usage_summary() -> dict[str, Any]:
    """聚合 5 个来源的 token 用量。"""
    local = _collect_local_ledger()
    cursor = _collect_cursor_usage()
    codex = _collect_codex_usage()
    trae = _collect_trae_usage()
    mimo = _collect_mimo_usage()
    sources = {"local": local, "cursor": cursor, "codex": codex, "trae": trae, "mimo": mimo}
    # 给每个来源加费用估算
    for key, src in sources.items():
        src["estimated_cost_usd"] = round(_estimate_cost_usd(key, src), 2)
    grand_total = sum(_to_int(s.get("total_tokens")) for s in sources.values())
    grand_prompt = sum(_to_int(s.get("prompt_tokens")) for s in sources.values())
    grand_completion = sum(_to_int(s.get("completion_tokens")) for s in sources.values())
    grand_cost = round(sum(s.get("estimated_cost_usd", 0.0) for s in sources.values()), 2)
    return {
        "success": True,
        "grand_total_tokens": grand_total,
        "grand_prompt_tokens": grand_prompt,
        "grand_completion_tokens": grand_completion,
        "grand_cost_usd": grand_cost,
        "sources": sources,
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.get("/admin/token-usage", response_model=None)
async def admin_token_usage(request: Request):
    """Token 用量聚合：本地账本 + Cursor + Codex + Trae。"""
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    return await asyncio.to_thread(_build_token_usage_summary)
