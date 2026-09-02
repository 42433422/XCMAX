"""
Mods API Routes - FastAPI Implementation

Provides endpoints for:
- GET /api/mods/ - List all mods
- GET /api/mods/loading-status - Get mod loading status
- GET /api/mods/routes - Get mod routes
"""

import hashlib
import json
import logging
import os
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.security.secure_filename import secure_filename

logger = logging.getLogger(__name__)

router = None
_MODS_UNAVAILABLE = "扩展服务暂时不可用，请稍后重试"


def _public_mod_errors(errors: list[Any]) -> list[dict[str, str]]:
    return [
        {"mod_id": str(item.get("mod_id") or "unknown"), "error": "加载失败"}
        for item in errors
        if isinstance(item, dict)
    ]


def get_mods_router() -> Any:
    global router
    if router is None:
        from fastapi import APIRouter

        router = APIRouter(prefix="/api/mods", tags=["mods"])
        _register_mods_endpoints(router)
    return router


async def _sync_enterprise_entitlements_from_request(request: Request) -> None:
    """已登录会话拉 Mod 列表前同步 entitlement，并自愈账号交付行业组合包。"""
    try:
        from app.enterprise.mod_entitlements import sync_entitlements_from_request

        await sync_entitlements_from_request(request)
    except RECOVERABLE_ERRORS:
        logger.exception("sync entitlements before list_mods failed")

    try:
        from app.infrastructure.auth.dependencies import resolve_session_user
        from app.mod_sdk.delivery_industry_runtime import (
            ensure_delivery_industry_bundle_for_account,
        )

        user = resolve_session_user(request)
        username = (
            str(user.get("username") or "").strip()
            if isinstance(user, dict)
            else str(getattr(user, "username", "") or "").strip()
        )
        if username:
            result = await ensure_delivery_industry_bundle_for_account(username)
            if not result.get("success") or result.get("runtime_ready") is False:
                logger.warning(
                    "customer delivery industry bundle self-heal failed account=%s industry=%s: %s",
                    username,
                    result.get("industry_id") or "",
                    result.get("message") or result.get("status") or "unknown",
                )
    except RECOVERABLE_ERRORS:
        # Mod 列表仍需可用；失败会写日志并由下一次请求重试自愈。
        logger.exception("customer delivery industry bundle self-heal before list_mods failed")


def _register_mods_endpoints(router) -> None:
    @router.get("/loading-status")
    async def get_loading_status():
        """Get mod loading status - returns discovered mods, load errors, etc."""
        try:
            from app.infrastructure.mods.mod_manager import get_mod_manager, is_mods_disabled

            if is_mods_disabled():
                return {
                    "success": True,
                    "data": {
                        "discovered_mod_ids": [],
                        "primary_mod_id": None,
                        "primary_mod_count": 0,
                        "mods_loaded": 0,
                        "load_mismatch": False,
                        "load_errors": [],
                        "manifest_errors": [],
                        "blueprint_errors": [],
                        "partial_failure": False,
                        "mods_disabled": True,
                    },
                }

            mm = get_mod_manager()
            mm._refresh_mods_root_if_needed()

            scanned = mm.scan_mods()
            installed_on_disk = [m.id for m in scanned if m.id]
            discovered_mod_ids = list(installed_on_disk)
            try:
                from app.enterprise.mod_entitlements import filter_mod_id_list_for_enterprise

                discovered_mod_ids = filter_mod_id_list_for_enterprise(discovered_mod_ids)
            except RECOVERABLE_ERRORS:
                pass

            loaded_mods = mm.list_loaded_mods()
            mods_loaded = len(loaded_mods)

            primary_mods = [m for m in scanned if m.primary and m.id]
            primary_mod_id = primary_mods[0].id if len(primary_mods) == 1 else None
            primary_mod_count = len(primary_mods)

            load_mismatch = len(scanned) > 0 and mods_loaded == 0

            manifest_errors = _public_mod_errors(mm._scan_manifest_errors)
            blueprint_errors = _public_mod_errors(mm._blueprint_failures)
            load_errors = _public_mod_errors(mm._recent_load_failures)

            partial_failure = len(load_errors) > 0 or len(blueprint_errors) > 0

            return {
                "success": True,
                "data": {
                    "mods_root": mm.mods_root,
                    "mods_search_roots": mm.all_mods_roots(),
                    "discovered_mod_ids": discovered_mod_ids,
                    "installed_mod_ids": installed_on_disk,
                    "primary_mod_id": primary_mod_id,
                    "primary_mod_count": primary_mod_count,
                    "mods_loaded": mods_loaded,
                    "load_mismatch": load_mismatch,
                    "load_errors": load_errors,
                    "manifest_errors": manifest_errors,
                    "blueprint_errors": blueprint_errors,
                    "partial_failure": partial_failure,
                    "mods_disabled": False,
                },
            }
        except RECOVERABLE_ERRORS:
            logger.exception("get_loading_status failed")
            return {
                "success": True,
                "data": {
                    "discovered_mod_ids": [],
                    "primary_mod_id": None,
                    "primary_mod_count": 0,
                    "mods_loaded": 0,
                    "load_mismatch": False,
                    "load_errors": [{"mod_id": "unknown", "error": "加载失败"}],
                    "manifest_errors": [],
                    "blueprint_errors": [],
                    "partial_failure": True,
                    "mods_disabled": False,
                    "error": _MODS_UNAVAILABLE,
                },
            }

    @router.get("")
    @router.get("/", include_in_schema=False)
    async def list_mods(request: Request, all: str | None = None):
        """List all loaded or discovered mods

        Args:
            all: 当传入 "1" 时，返回磁盘扫描的全部 Mod 列表（不受已加载状态影响）
        """
        await _sync_enterprise_entitlements_from_request(request)
        try:
            from app.infrastructure.mods.mod_manager import get_mod_manager

            mm = get_mod_manager()
            etag_src = mm._mods_scan_fingerprint()
            etag = hashlib.sha256(etag_src.encode("utf-8")).hexdigest()[:32]
            inm = (request.headers.get("if-none-match") or "").strip().strip('"')
            if inm and inm == etag:
                return Response(status_code=304, headers={"ETag": f'"{etag}"'})
            # 侧栏菜单/图标需要实时反映 manifest 变更，默认也走磁盘扫描。
            # 保留 ?all=1 兼容旧调用方；当前两者行为一致。
            mods = mm.list_all_mods()
            body = {"success": True, "data": mods}
            return JSONResponse(
                content=body,
                headers={"ETag": f'"{etag}"', "Cache-Control": "private, max-age=30"},
            )
        except RECOVERABLE_ERRORS:
            logger.exception("list_mods failed")
            return {
                "success": False,
                "message": _MODS_UNAVAILABLE,
                "error": _MODS_UNAVAILABLE,
                "data": [],
            }

    @router.get("/routes")
    async def list_routes():
        """Get mod routes for frontend registration"""
        try:
            from app.infrastructure.mods.mod_manager import get_mod_manager

            mm = get_mod_manager()
            routes = mm.get_routes()
            return {"success": True, "data": routes}
        except RECOVERABLE_ERRORS:
            logger.exception("list_routes failed")
            return {
                "success": False,
                "message": _MODS_UNAVAILABLE,
                "error": _MODS_UNAVAILABLE,
                "data": [],
            }

    @router.get("/comms/endpoints")
    async def list_comms_endpoints():
        """已注册的 Mod 间通信端点（与归档 ``/api/mods/comms/endpoints`` 对齐）。"""
        try:
            from app.infrastructure.mods.comms import get_mod_comms

            return {"success": True, "data": get_mod_comms().list_endpoints()}
        except RECOVERABLE_ERRORS:
            logger.exception("list_comms_endpoints failed")
            return {"success": False, "error": _MODS_UNAVAILABLE}

    @router.get("/employee-packs/{pack_id}/config-preview")
    async def employee_pack_config_preview(pack_id: str):
        """返回已安装 employee_pack 的 ``employee_config_v2`` 摘要（供宿主/MODstore 联调）。"""

        try:
            from app.infrastructure.mods.mod_manager import _default_mods_root
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            logger.exception("employee pack root unavailable")
            return {"success": False, "error": _MODS_UNAVAILABLE}
        safe_pack_id = secure_filename((pack_id or "").strip())
        if not safe_pack_id or safe_pack_id != (pack_id or "").strip():
            return {"success": False, "error": "员工包编号无效"}
        root = os.path.join(_default_mods_root(), "_employees", safe_pack_id, "manifest.json")
        if not os.path.isfile(root):
            return {"success": False, "error": "员工包未安装或 manifest 不存在"}
        try:
            with open(root, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.exception("employee pack manifest unreadable")
            return {"success": False, "error": _MODS_UNAVAILABLE}
        v2 = data.get("employee_config_v2")
        hp = data.get("xcagi_host_profile")
        cog = (v2 or {}).get("cognition") if isinstance(v2, dict) else {}
        agent = cog.get("agent") if isinstance(cog, dict) else {}
        model = agent.get("model") if isinstance(agent, dict) else {}
        return {
            "success": True,
            "data": {
                "pack_id": data.get("id") or pack_id,
                "has_employee_config_v2": isinstance(v2, dict),
                "cognition_model": model if isinstance(model, dict) else {},
                "system_prompt_preview": (
                    str(agent.get("system_prompt") or "")[:400] if isinstance(agent, dict) else ""
                ),
                "xcagi_host_profile": hp if isinstance(hp, dict) else None,
            },
        }

    @router.get("/{mod_id}")
    async def get_mod_detail(mod_id: str, request: Request):
        """单个 Mod 元数据（须注册在 ``/comms``、``/routes`` 等静态段之后）。"""
        try:
            from app.infrastructure.mods.mod_manager import get_mod_manager, is_mods_disabled

            if is_mods_disabled():
                return JSONResponse({"success": False, "error": "Mod not found"}, status_code=404)

            mm = get_mod_manager()
            mm.ensure_mods_loaded(request.app)
            mod = mm.get_mod(mod_id)
            if not mod:
                return JSONResponse({"success": False, "error": "Mod not found"}, status_code=404)

            return {
                "success": True,
                "data": {
                    "id": mod.id,
                    "name": mod.name,
                    "version": mod.version,
                    "author": mod.author,
                    "description": mod.description,
                    "menu": mod.frontend_menu,
                    "menu_overrides": mod.frontend_menu_overrides,
                    "comms_exports": mod.comms_exports,
                },
            }
        except RECOVERABLE_ERRORS:
            logger.exception("get_mod_detail failed")
            return JSONResponse({"success": False, "error": _MODS_UNAVAILABLE}, status_code=500)

    @router.delete("/{mod_id}")
    async def uninstall_mod_disk(mod_id: str):
        """从本机删除扩展包目录并解除加载（与 ``POST /api/mod-store/uninstall`` 同源逻辑）。"""
        try:
            from app.infrastructure.mods.mod_manager import get_mod_manager, is_mods_disabled

            if is_mods_disabled():
                return JSONResponse(
                    {"success": False, "message": "扩展已全局关闭（XCAGI_DISABLE_MODS）"},
                    status_code=403,
                )
            mid = (mod_id or "").strip()
            if not mid:
                return JSONResponse({"success": False, "message": "缺少 mod_id"}, status_code=400)
            mm = get_mod_manager()
            ok, msg = mm.uninstall_mod(mid, remove_files=True)
            if not ok:
                return JSONResponse({"success": False, "message": msg}, status_code=400)
            return {"success": True, "message": msg, "data": {"id": mid}}
        except RECOVERABLE_ERRORS:
            logger.exception("uninstall_mod_disk failed")
            return JSONResponse({"success": False, "message": _MODS_UNAVAILABLE}, status_code=500)
