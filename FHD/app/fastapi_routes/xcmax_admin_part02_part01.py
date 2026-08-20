# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.xcmax_admin")


async def _self_maintenance_local_or_proxy(
    request: _facade().Request,
    method: str,
    path: str,
    *,
    json_body: dict[str, _facade().Any] | None = None,
):
    """自维护 loop runtime：优先本地 MODstore :8788，远端 market-proxy 404 时再试本地。"""
    if not path.startswith("/api/ops/self-maintenance/"):
        return None
    from app.application import self_maintenance_app_service as sm_svc
    from app.application.modstore_local_client import prefer_local_modstore
    from app.fastapi_routes.market_account import _authorization_from_request

    authorization = _authorization_from_request(request, json_body or {})

    async def _call_local() -> dict[str, _facade().Any] | None:
        if path.startswith("/api/ops/self-maintenance/status"):
            limit = 80
            if "?" in path:
                for part in path.split("?", 1)[1].split("&"):
                    if part.startswith("limit="):
                        try:
                            limit = int(part.split("=", 1)[1])
                        except ValueError:
                            pass
            return await sm_svc.get_runtime_status_local(limit=limit, authorization=authorization)
        if path == "/api/ops/self-maintenance/governance-review" and method.upper() == "POST":
            note = str((json_body or {}).get("note") or "")
            return await sm_svc.governance_review_local(note=note, authorization=authorization)
        if path == "/api/ops/self-maintenance/run" and method.upper() == "POST":
            reason = str((json_body or {}).get("reason") or "admin_force_run")
            return await sm_svc.force_run_local(reason=reason, authorization=authorization)
        return None

    if prefer_local_modstore():
        try:
            local_payload = await _call_local()
            if local_payload is not None:
                return local_payload
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("local self-maintenance failed path=%s: %s", path, exc)
    proxied = await _facade()._market_admin_proxy(request, method, path, json_body=json_body)
    if isinstance(proxied, _facade().JSONResponse) and proxied.status_code == 404:
        try:
            local_payload = await _call_local()
            if local_payload is not None:
                return local_payload
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.warning(
                "self-maintenance local fallback after upstream 404 path=%s: %s", path, exc
            )
    return proxied


async def _remote_duty_health(request: _facade().Request) -> dict[str, _facade().Any]:
    health_payload = await _facade()._market_admin_proxy(
        request, "GET", "/api/admin/duty-graph/health"
    )
    if isinstance(health_payload, dict):
        return health_payload
    if hasattr(health_payload, "body"):
        try:
            return _facade().cast(
                "dict[str, Any]",
                _facade().json.loads(getattr(health_payload, "body", b"") or b"{}"),
            )
        except _facade().RECOVERABLE_ERRORS:
            return {}
    return {}


def _collect_mod_modules() -> list[dict[str, _facade().Any]]:
    """从 mod_manager 读取已加载的本地 Mod，转换成 XCmax 模块格式。"""
    rows: list[dict[str, _facade().Any]] = []
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
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("collect_mod_modules failed: %s", exc)
    return rows


def _collect_employee_pack_modules() -> list[dict[str, _facade().Any]]:
    """从员工包注册表读取员工包，转换成 XCmax 模块格式。"""
    rows: list[dict[str, _facade().Any]] = []
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
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug("collect_employee_pack_modules failed: %s", exc)
    return rows


@_facade().router.get("/admin/market/users", response_model=None)
async def admin_list_market_users(request: _facade().Request):
    return await _facade()._market_admin_proxy(request, "GET", "/api/admin/users")


@_facade().router.post("/admin/market/users", response_model=None)
async def admin_create_market_user(
    request: _facade().Request,
    payload: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    from app.application.session_account_meta import audit_admin_action
    from app.fastapi_routes.market_account import register_market_user

    gate = _facade()._require_market_admin_session(request)
    if gate is not None:
        return gate
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    email = str(payload.get("email") or "").strip()
    verification_code = str(payload.get("verification_code") or payload.get("code") or "").strip()
    if not username or not password:
        return _facade().JSONResponse(
            {"success": False, "message": "username、password 必填"}, status_code=422
        )
    if len(password) < 6:
        return _facade().JSONResponse(
            {"success": False, "message": "password 至少 6 位"}, status_code=422
        )
    if not email:
        email = f"{username.lower()}@xcagi.local"
    result = await register_market_user(username, password, email, verification_code)
    if not result.get("success"):
        return _facade().JSONResponse(
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


@_facade().router.get("/admin/market/assignable-mods", response_model=None)
async def admin_list_assignable_mods(request: _facade().Request):
    return await _facade()._market_admin_proxy(
        request, "GET", "/api/admin/enterprise/assignable-mods"
    )


@_facade().router.get("/admin/market/wallets", response_model=None)
async def admin_list_wallets(request: _facade().Request):
    """代理远端 ``/api/admin/wallets``，返回所有用户钱包余额。

    远端返回 ``{items: [{id, user_id, balance, updated_at}], total}``。
    """
    limit = request.query_params.get("limit", "500")
    offset = request.query_params.get("offset", "0")
    return await _facade()._market_admin_proxy(
        request, "GET", f"/api/admin/wallets?limit={limit}&offset={offset}"
    )


@_facade().router.get("/admin/market/orders", response_model=None)
async def admin_list_orders(request: _facade().Request):
    """经营看板：代理 MODstore ``/api/admin/orders``（订单列表 + 经营聚合）。

    打通「AI 不知道订单」断点：管理端经此接口读取平台订单数据，供 AI 员工感知与处理。
    """
    q = []
    if request.query_params.get("status"):
        q.append(f"status={request.query_params['status']}")
    if request.query_params.get("limit"):
        q.append(f"limit={request.query_params['limit']}")
    if request.query_params.get("offset"):
        q.append(f"offset={request.query_params['offset']}")
    query = "?" + "&".join(q) if q else ""
    return await _facade()._market_admin_proxy(request, "GET", f"/api/admin/orders{query}")


@_facade().router.post("/admin/market/users/{user_id}/wallet/credit", response_model=None)
async def admin_credit_user_wallet(
    request: _facade().Request,
    user_id: int,
    payload: dict[str, _facade().Any] = _facade().Body(default_factory=dict),
):
    from app.application.session_account_meta import audit_admin_action

    try:
        amount = float(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return _facade().JSONResponse(
            {"success": False, "message": "加款金额必须大于 0"}, status_code=422
        )
    description = str(payload.get("description") or "").strip() or "后台加款"
    out = await _facade()._market_admin_proxy(
        request,
        "POST",
        f"/api/admin/users/{user_id}/wallet/credit",
        json_body={"amount": amount, "description": description},
    )
    audit_admin_action(
        request, "credit_user_wallet", target_user_id=user_id, detail=f"amount={amount}"
    )
    return out


@_facade().router.get("/admin/market/users/{user_id}/mods", response_model=None)
async def admin_list_user_mods(request: _facade().Request, user_id: int):
    return await _facade()._market_admin_proxy(request, "GET", f"/api/admin/users/{user_id}/mods")


@_facade().router.post("/admin/market/users/{user_id}/mods/{mod_id}", response_model=None)
async def admin_bind_user_mod(request: _facade().Request, user_id: int, mod_id: str):
    from app.application.session_account_meta import audit_admin_action

    out = await _facade()._market_admin_proxy(
        request, "POST", f"/api/admin/users/{user_id}/mods/{mod_id}"
    )
    audit_admin_action(request, "bind_user_mod", target_user_id=user_id, mod_id=mod_id)
    return out


@_facade().router.delete("/admin/market/users/{user_id}/mods/{mod_id}", response_model=None)
async def admin_unbind_user_mod(request: _facade().Request, user_id: int, mod_id: str):
    from app.application.session_account_meta import audit_admin_action

    out = await _facade()._market_admin_proxy(
        request, "DELETE", f"/api/admin/users/{user_id}/mods/{mod_id}"
    )
    audit_admin_action(request, "unbind_user_mod", target_user_id=user_id, mod_id=mod_id)
    return out


@_facade().router.put("/admin/market/users/{user_id}/admin", response_model=None)
async def admin_set_user_admin(
    request: _facade().Request, user_id: int, is_admin: bool = _facade().Query(...)
):
    return await _facade()._market_admin_proxy(
        request,
        "PUT",
        f"/api/admin/users/{user_id}/admin?is_admin={('true' if is_admin else 'false')}",
    )


@_facade().router.put("/admin/market/users/{user_id}/enterprise", response_model=None)
async def admin_set_user_enterprise(
    request: _facade().Request, user_id: int, is_enterprise: bool = _facade().Query(...)
):
    return await _facade()._market_admin_proxy(
        request,
        "PUT",
        f"/api/admin/users/{user_id}/enterprise?is_enterprise={('true' if is_enterprise else 'false')}",
    )


def _clean_string_list(raw: _facade().Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _truthy(raw: _facade().Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False
