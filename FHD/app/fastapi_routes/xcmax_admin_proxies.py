"""XCmax admin proxy helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.request
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.xcmax_admin_patch as _p

logger = logging.getLogger(__name__)
router = APIRouter()

REMOTE_HOST = os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147")
REMOTE_PORT = int(os.environ.get("XCMAX_REMOTE_PORT", "9999"))
_DEFAULT_URLOPEN = urllib.request.urlopen
SYNC_POLL_INTERVAL_S = float(os.environ.get("XCMAX_SYNC_POLL_S", "10"))

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
        except _p.RECOVERABLE_ERRORS as exc:
            logger.warning("release-train json read failed: %s", exc)
        return _default_snapshot()

    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        path = Path(mono).expanduser().resolve() / "FHD" / "config" / "release_train.json"
        return _from_file(path)

    try:
        from modstore_server.release_train import snapshot_public

        return cast("dict[str, Any]", snapshot_public())
    except _p.RECOVERABLE_ERRORS:
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
        gate = _p._require_market_admin_session(request)
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
            except _p.RECOVERABLE_ERRORS as exc:
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
    except _p.RECOVERABLE_ERRORS as exc:
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
        except _p.RECOVERABLE_ERRORS as exc:
            logger.warning("local digest/action-items read failed path=%s: %s", path, exc)
            return JSONResponse({"success": False, "message": str(exc)}, status_code=502)

    return await _p._market_admin_proxy(
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
        except _p.RECOVERABLE_ERRORS as exc:
            logger.warning(
                "local self-maintenance failed path=%s: %s",
                path,
                exc,
            )

    proxied = await _p._market_admin_proxy(
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
        except _p.RECOVERABLE_ERRORS as exc:
            logger.warning(
                "self-maintenance local fallback after upstream 404 path=%s: %s",
                path,
                exc,
            )
    return proxied


async def _remote_duty_health(request: Request) -> dict[str, Any]:
    health_payload = await _p._market_admin_proxy(request, "GET", "/api/admin/duty-graph/health")
    if isinstance(health_payload, dict):
        return health_payload
    if hasattr(health_payload, "body"):
        try:
            return cast("dict[str, Any]", json.loads(getattr(health_payload, "body", b"") or b"{}"))
        except _p.RECOVERABLE_ERRORS:
            return {}
    return {}
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
    except _p.RECOVERABLE_ERRORS as exc:
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
    except _p.RECOVERABLE_ERRORS as exc:
        logger.debug("collect_employee_pack_modules failed: %s", exc)
    return rows

def _clean_string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _truthy(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False
def _inject_digest_api_base(payload: dict[str, Any], base: str) -> dict[str, Any]:
    """在 ``data`` 中写入 ``digest_api_base``，供 XCmax 页眉与「打开市场」与解锁校验同源提示。"""
    data = payload.get("data")
    if isinstance(data, dict):
        data["digest_api_base"] = base
    return payload
def _probe_remote_health_sync() -> dict[str, Any]:
    """同步探测远端 HTTP /api/health；供 asyncio.to_thread 调用，避免阻塞事件循环。"""
    import app.fastapi_routes.xcmax_admin as _facade

    urllib_request = _facade.urllib.request
    remote_url = f"http://{REMOTE_HOST}:{REMOTE_PORT}/api/health"
    t0 = time.time()
    try:
        req = urllib_request.Request(remote_url, method="GET")
        if urllib_request.urlopen is _facade._DEFAULT_URLOPEN:
            direct_opener = urllib_request.build_opener(urllib_request.ProxyHandler({}))
            response_ctx = direct_opener.open(req, timeout=5)
        else:
            response_ctx = urllib_request.urlopen(req, timeout=5)
        with response_ctx as resp:
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
    except _p.RECOVERABLE_ERRORS as exc:
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
        except _p.RECOVERABLE_ERRORS as exc:
            err = _json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
            yield f"data: {err}\n\n"
        await asyncio.sleep(SYNC_POLL_INTERVAL_S)
async def _xcmax_market_proxy_impl(request: Request, subpath: str):
    """编制图 LLM / 员工执行等：经会话市场 token 转发至 MODstore ``/api/...``。"""
    method = request.method.upper()
    json_body: dict[str, Any] | None = None
    if method in {"POST", "PUT", "PATCH"}:
        try:
            body = await request.json()
            json_body = body if isinstance(body, dict) else None
        except _p.RECOVERABLE_ERRORS:
            json_body = None
    api_path = f"/api/{str(subpath or '').lstrip('/')}"
    if api_path.startswith("/api/ops/self-maintenance/"):
        return await _p._self_maintenance_local_or_proxy(
            request,
            method,
            api_path,
            json_body=json_body,
        )
    return await _p._market_admin_proxy(request, method, api_path, json_body=json_body)
def _register_market_proxy_method(method: str, *, parent_router=None) -> None:
    async def endpoint(request: Request, subpath: str):
        return await _xcmax_market_proxy_impl(request, subpath)

    endpoint.__name__ = f"xcmax_market_proxy_{method.lower()}"
    endpoint.__qualname__ = endpoint.__name__
    target = parent_router if parent_router is not None else router
    target.add_api_route(
        "/market-proxy/{subpath:path}",
        endpoint,
        methods=[method],
        response_model=None,
    )






def _build_token_usage_summary() -> dict[str, Any]:
    """聚合 5 个来源的 token 用量。"""
    local = _p._collect_local_ledger()
    cursor = _p._collect_cursor_usage()
    codex = _p._collect_codex_usage()
    trae = _p._collect_trae_usage()
    mimo = _p._collect_mimo_usage()
    sources = {"local": local, "cursor": cursor, "codex": codex, "trae": trae, "mimo": mimo}
    # 给每个来源加费用估算
    for key, src in sources.items():
        src["estimated_cost_usd"] = round(_p._estimate_cost_usd(key, src), 2)
    grand_total = sum(_p._to_int(s.get("total_tokens")) for s in sources.values())
    grand_prompt = sum(_p._to_int(s.get("prompt_tokens")) for s in sources.values())
    grand_completion = sum(_p._to_int(s.get("completion_tokens")) for s in sources.values())
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
