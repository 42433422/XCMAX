# mypy: disable-error-code="misc, no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.mobile_api_extensions")


@_facade().extension_router.post("/mod-store/install", response_model=dict[str, _facade().Any])
async def mobile_install_mod(
    body: dict[str, _facade().Any], user=_facade().Depends(_facade().get_mobile_user)
):
    """从移动端安装指定市场 Mod。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    mod_id = str(body.get("mod_id") or body.get("pkg_id") or body.get("package_file") or "").strip()
    if not mod_id:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "缺少 mod_id", success=False, code=400),
            status_code=400,
        )
    try:
        from app.fastapi_routes.mod_store_routes import _install_from_catalog

        result = await _install_from_catalog(mod_id, "", activate=True)
        return _facade().format_mobile_response(
            data=result.data,
            message=result.message,
            success=bool(result.success),
            code=200 if result.success else 409,
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile install mod failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "MOD 安装失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.post(
    "/mod-store/install-customer-delivery-seed", response_model=dict[str, _facade().Any]
)
async def mobile_install_customer_delivery_seed(
    body: dict[str, _facade().Any], user=_facade().Depends(_facade().get_mobile_user)
):
    """安装客户交付场景的移动端种子包。"""
    if user is None:
        return _facade()._mobile_unauthorized_response()
    mod_id = str(body.get("mod_id") or body.get("pkg_id") or "").strip()
    industry_id = str(body.get("industry_id") or body.get("industryId") or "").strip()
    if not mod_id:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "缺少 mod_id", success=False, code=400),
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
            account_username=str(getattr(user, "username", "") or "").strip(),
        )
        return _facade().format_mobile_response(
            data=data,
            message=str(data.get("message") or ""),
            success=bool(data.get("success")),
            code=200 if data.get("success") else 409,
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile install customer delivery seed failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "客户交付包安装失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.get("/home")
async def mobile_home(user=_facade().Depends(_facade().get_mobile_user)):
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
    mod_items = _facade()._mobile_mod_items(market_profiles, market_connected=market_connected)
    installed = [m["id"] for m in mod_items]
    from app.mod_sdk.platform_shell import build_platform_shell_payload

    sync_data: dict[str, _facade().Any] = {}
    try:
        from app.db.xcmax_sync import SyncDb

        sync_data = SyncDb().get_status()
    except _facade().RECOVERABLE_ERRORS:
        sync_data = {"error": "市场同步失败"}
    return _facade().format_mobile_response(
        data={
            "mods": mod_items,
            "market_connected": market_connected,
            "market_profile_count": len(market_profiles),
            "market_error": market_error,
            "platform_shell": build_platform_shell_payload(installed),
            "sync": sync_data,
        }
    )


@_facade().extension_router.get("/nav-menu")
async def mobile_nav_menu(user=_facade().Depends(_facade().get_mobile_user)):
    """返回当前用户可见的侧栏菜单项（核心菜单 + Mod 菜单）。

    供手机端"探索"Tab 配对后动态渲染工具列表，与桌面端侧栏对齐。
    """
    if user is None:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    user_role = str(getattr(user, "role", "") or "").strip().lower()
    is_admin = user_role in {"admin", "super_admin", "owner"}
    account_kind = "admin" if is_admin else "enterprise"
    visible_keys = _facade()._ROLE_VISIBLE_KEYS.get(account_kind)
    items: list[dict[str, _facade().Any]] = []
    for item in _facade()._CORE_NAV_ITEMS:
        if visible_keys is not None and item["key"] not in visible_keys:
            continue
        items.append({**item, "source": "core"})
    if is_admin:
        items.append({**_facade()._ADMIN_NAV_ITEM, "source": "core"})
    try:
        mod_items = _facade()._mobile_mod_items()
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
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("nav-menu mod items failed: %s", exc)
    return _facade().format_mobile_response(data={"items": items, "account_kind": account_kind})


def _modstore_platform_base() -> str:
    """获取 MODstore 后端 base url（如 http://127.0.0.1:8765）。"""
    return _facade().os.environ.get("MODSTORE_PLATFORM_URL", "http://localhost:8000").rstrip("/")


def _modstore_admin_token() -> str:
    """获取调 MODstore admin API 用的 Bearer token。"""
    return _facade().os.environ.get("MODSTORE_AUTH_TOKEN", "").strip()


async def _modstore_admin_proxy(
    method: str,
    path: str,
    *,
    params: dict[str, _facade().Any] | None = None,
    json_body: dict[str, _facade().Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, _facade().Any]:
    """通用代理：调 MODstore 后端 admin API。

    返回 {"ok": bool, "status": int, "data": ..., "error": str}。
    """
    import httpx

    url = f"{_facade()._modstore_platform_base()}{path}"
    headers = {"Accept": "application/json"}
    token = _facade()._modstore_admin_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, params=params, json=json_body, headers=headers)
        try:
            data = resp.json()
        except _facade().RECOVERABLE_ERRORS:
            data = {"raw": resp.text[:500]}
        if resp.is_success:
            return {"ok": True, "status": resp.status_code, "data": data}
        return {
            "ok": False,
            "status": resp.status_code,
            "error": str(data.get("detail") or data.get("error") or resp.text[:200])[:300],
        }
    except _facade().RECOVERABLE_ERRORS as exc:
        return {
            "ok": False,
            "status": 0,
            "error": f"无法连接 MODstore 后端：{_facade()._compact_text(exc)[:200]}",
        }


@_facade().extension_router.get("/admin/employee-pending-questions")
async def mobile_admin_employee_pending_questions(
    request: _facade().Request,
    limit: int = _facade().Query(default=50, ge=1, le=200),
    include_history: bool = _facade().Query(default=False),
    employee_id: str | None = _facade().Query(default=None),
    user=_facade().Depends(_facade().get_mobile_user),
):
    """拉员工 Phase-D 主动提问列表（pending 优先）。

    GET /api/mobile/v1/admin/employee-pending-questions
      ?limit=50&include_history=false&employee_id=llm-ops-engineer

    返回 {"items": [...], "count": N, "market_connected": bool}
    每个 item 含：id / employee_id / task / question / status / asked_at / answer / answered_at
    """
    meta, err = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    params: dict[str, _facade().Any] = {"limit": limit, "include_expired": bool(include_history)}
    if employee_id:
        params["employee_id"] = employee_id
    out = await _facade()._modstore_admin_proxy(
        "GET", "/api/admin/employee-autonomy/questions", params=params
    )
    if not out.get("ok"):
        return _facade().format_mobile_response(
            None,
            f"拉员工提问失败：{out.get('error') or '未知错误'}",
            success=False,
            code=out.get("status") or 502,
        )
    data = out.get("data") if isinstance(out.get("data"), dict) else {}
    if not isinstance(data, dict):
        data = {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    return _facade().format_mobile_response(
        data={
            "items": items,
            "count": int(data.get("count") or len(items or [])),
            "market_connected": bool(out.get("ok")),
        }
    )


@_facade().extension_router.post("/admin/employee-pending-questions/{question_id}/answer")
async def mobile_admin_employee_pending_question_answer(
    question_id: int,
    body: dict[str, _facade().Any],
    request: _facade().Request,
    user=_facade().Depends(_facade().get_mobile_user),
):
    """老板回答员工的 Phase-D 提问。

    POST /api/mobile/v1/admin/employee-pending-questions/{id}/answer
    body: {"answer": "先做 A，因为..."}

    成功后员工执行管道被阻塞的 ask_human_blocking() 会拿到答案继续执行。
    """
    meta, err = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    answer_text = str((body or {}).get("answer") or "").strip()
    if not answer_text:
        return _facade().format_mobile_response(
            None, "answer 字段不能为空", success=False, code=400
        )
    out = await _facade()._modstore_admin_proxy(
        "POST",
        f"/api/admin/employee-autonomy/questions/{int(question_id)}/answer",
        json_body={"answer": answer_text},
    )
    if not out.get("ok"):
        return _facade().format_mobile_response(
            None,
            f"回答失败：{out.get('error') or '未知错误'}",
            success=False,
            code=out.get("status") or 502,
        )
    data = out.get("data") if isinstance(out.get("data"), dict) else {}
    return _facade().format_mobile_response(data=data)


def _sse_line(payload: dict) -> bytes:
    """构造 SSE event line：data: {json}\\n\\n"""
    return ("data: " + _facade().json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


def _chunk_employee_reply(text: str) -> list[str]:
    """把员工完整回复切成 SSE chunk（按句号/换行，每块 <= 120 字）。"""
    if not text:
        return []
    parts = _facade().re.split("(?<=[。！？!?\\n])", text)
    chunks: list[str] = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) > 120:
            if buf:
                chunks.append(buf)
            if len(p) > 120:
                chunks.append(p)
                buf = ""
            else:
                buf = p
        else:
            buf += p
    if buf:
        chunks.append(buf)
    return chunks or [text]
