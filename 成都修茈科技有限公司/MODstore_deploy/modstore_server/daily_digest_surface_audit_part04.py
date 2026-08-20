# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


def _path_needs_market_auth(path: str) -> bool:
    """除登录/注册外，/market/* SPA 页注入 modstore_token（workbench/download 等需登录）。"""
    p = str(path or "").strip()
    if not p.startswith("/market"):
        return False
    for skip in _facade()._MARKET_AUTH_SKIP_PREFIXES:
        if p == skip or p.startswith(skip + "/") or p.startswith(skip + "?"):
            return False
    return True


def _parse_set_cookie_headers(headers: _facade().Any) -> _facade().Dict[str, str]:
    jar: _facade().Dict[str, str] = {}
    raw_lines: _facade().List[str] = []
    if headers is None:
        return jar
    if hasattr(headers, "get_all"):
        try:
            raw_lines = list(headers.get_all("Set-Cookie") or [])
        except RECOVERABLE_ERRORS:
            raw_lines = []
    if not raw_lines:
        one = headers.get("Set-Cookie") if hasattr(headers, "get") else None
        if one:
            raw_lines = [one] if isinstance(one, str) else list(one)
    for line in raw_lines:
        part = str(line).split(";")[0]
        idx = part.find("=")
        if idx > 0:
            jar[part[:idx].strip()] = part[idx + 1 :].strip()
    return jar


def _surface_demo_account_defaults() -> _facade().Tuple[str, str]:
    fallback = ("xcagi-enterprise-demo", "Demo@2026")
    candidates: _facade().List[_facade().Path] = []
    raw_cfg = (_facade().os.environ.get("MODSTORE_RUNTIME_CONFIG_ROOT") or "").strip()
    if raw_cfg:
        candidates.append(
            _facade().Path(raw_cfg).expanduser().resolve() / "surface_audit_demo_account.json"
        )
    try:
        candidates.append(
            _facade()._repo_root() / "FHD" / "config" / "surface_audit_demo_account.json"
        )
    except RECOVERABLE_ERRORS:
        pass
    for path in candidates:
        try:
            cfg = _facade().json.loads(path.read_text(encoding="utf-8"))
            user = str(cfg.get("username") or fallback[0]).strip()
            password = str(cfg.get("password") or fallback[1])
            if user and password:
                return (user, password)
        except RECOVERABLE_ERRORS:
            continue
    return fallback


def _surface_audit_login_api_base(account_kind: str) -> str:
    """按巡检对象选择登录 API 根。

    P-W/MODstore 市场页使用 MODstore 内部 API（默认 :8788）；P-S 企业客户端页面
    使用 FHD API（默认 SURFACE_AUDIT_API_URL/:5102）。两者 session/token 存储不共用。
    """
    if account_kind == "enterprise":
        raw = (
            _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_ENTERPRISE_API_URL")
            or _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_PS_API_URL")
            or _facade().os.environ.get("SURFACE_AUDIT_API_URL")
            or "http://127.0.0.1:5102"
        )
        return str(raw).strip().rstrip("/")
    raw = (
        _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL") or _facade()._internal_api_base()
    )
    return str(raw).strip().rstrip("/")


def _login_surface_audit_sync(
    *,
    account_kind: _facade().Optional[str] = None,
    user: _facade().Optional[str] = None,
    password: _facade().Optional[str] = None,
    label: str = "market",
) -> _facade().Dict[str, _facade().Any]:
    """Playwright 截图前登录对应系统，并返回可注入的 token/cookie/session。"""
    account_kind = (
        account_kind or _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_ACCOUNT_KIND") or "admin"
    ).strip()
    api_base = _facade()._surface_audit_login_api_base(account_kind)
    if account_kind == "enterprise":
        demo_user, demo_password = _facade()._surface_demo_account_defaults()
        user = (
            user
            or _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_ENTERPRISE_USER")
            or _facade().os.environ.get("SURFACE_AUDIT_ENTERPRISE_USER")
            or _facade().os.environ.get("SURFACE_AUDIT_USER")
            or demo_user
        )
        password = (
            password
            or _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_ENTERPRISE_PASSWORD")
            or _facade().os.environ.get("SURFACE_AUDIT_ENTERPRISE_PASSWORD")
            or _facade().os.environ.get("SURFACE_AUDIT_PASSWORD")
            or demo_password
        )
    else:
        user = user or _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_USER") or "admin"
        password = (
            password or _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_PASSWORD") or "admin123"
        )
    user = str(user).strip()
    password = str(password).strip()
    cookies: _facade().Dict[str, str] = {}

    def _req(
        url: str, payload: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    ) -> _facade().Tuple[_facade().Dict[str, _facade().Any], _facade().Dict[str, str]]:
        headers = {
            "User-Agent": "MODstore-surface-audit/1.0",
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
            csrf = cookies.get("csrf_token") or ""
            if csrf:
                headers["X-CSRF-Token"] = csrf
            cookie_hdr = "; ".join((f"{k}={v}" for (k, v) in cookies.items() if v))
            if cookie_hdr:
                headers["Cookie"] = cookie_hdr
            data = _facade().json.dumps(payload).encode("utf-8")
            req = _facade().urllib.request.Request(url, data=data, headers=headers, method="POST")
        else:
            req = _facade().urllib.request.Request(url, headers=headers, method="GET")
        with _facade().urllib.request.urlopen(req, timeout=45) as resp:
            body = _facade().json.loads(resp.read().decode("utf-8", errors="replace"))
            cookies.update(_facade()._parse_set_cookie_headers(resp.headers))
            return (body, cookies)

    try:
        _req(f"{api_base}/api/health")
        web, _ = _req(
            f"{api_base}/api/auth/login",
            {"username": user, "password": password, "account_kind": account_kind},
        )
    except (
        _facade().urllib.error.URLError,
        TimeoutError,
        _facade().json.JSONDecodeError,
        ValueError,
    ) as exc:
        _facade().logger.warning(
            "surface audit: %s login failed base=%s err=%s", label, api_base, exc
        )
        return {}
    ok = bool(web.get("ok") or web.get("success"))
    data = web.get("data") if isinstance(web.get("data"), dict) else {}
    access = str(
        web.get("access_token")
        or web.get("token")
        or web.get("market_access_token")
        or data.get("access_token")
        or data.get("token")
        or data.get("market_access_token")
        or ""
    ).strip()
    refresh = str(
        web.get("refresh_token")
        or web.get("market_refresh_token")
        or data.get("refresh_token")
        or data.get("market_refresh_token")
        or ""
    ).strip()
    session_id = str(
        web.get("session_id")
        or data.get("session_id")
        or cookies.get("session_id")
        or cookies.get("admin_session_id")
        or ""
    ).strip()
    csrf = str(cookies.get("csrf_token") or "").strip()
    if account_kind == "enterprise" and ok and session_id and (not access):
        try:
            handoff, _ = _req(f"{api_base}/api/market/session-handoff")
            handoff_data = handoff.get("data") if isinstance(handoff.get("data"), dict) else {}
            access = str(
                handoff_data.get("market_access_token") or handoff_data.get("token") or ""
            ).strip()
            refresh = str(
                handoff_data.get("market_refresh_token")
                or handoff_data.get("refresh_token")
                or refresh
            ).strip()
        except RECOVERABLE_ERRORS as exc:
            _facade().logger.warning(
                "surface audit: %s session-handoff failed base=%s err=%s",
                label,
                api_base,
                exc,
            )
    has_required_state = bool(access) or (account_kind == "enterprise" and bool(session_id))
    if not ok or not has_required_state:
        _facade().logger.warning(
            "surface audit: %s login rejected base=%s msg=%s",
            label,
            api_base,
            web.get("message") or web.get("error") or "no access_token",
        )
        return {}
    return {
        "access_token": access,
        "refresh_token": refresh,
        "session_id": session_id,
        "csrf_token": csrf,
        "username": user,
        "account_kind": account_kind,
        "api_base": api_base,
        "cookies": cookies,
        "raw": web,
    }


def _fetch_admin_digest_code_sync(auth: _facade().Dict[str, str]) -> str:
    """从 MODstore API 拉取管理端 6 位校验码（对齐 FHD digest-identity 自签发）。"""
    api_base = (
        (
            _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
            or _facade()._internal_api_base()
        )
        .strip()
        .rstrip("/")
    )
    headers = {"Accept": "application/json", "User-Agent": "MODstore-surface-audit/1.0"}
    token = str(auth.get("access_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    csrf = str(auth.get("csrf_token") or "").strip()
    if csrf:
        headers["X-CSRF-Token"] = csrf
    try:
        req = _facade().urllib.request.Request(
            f"{api_base}/api/xcmax/admin/digest-identity", headers=headers, method="GET"
        )
        with _facade().urllib.request.urlopen(req, timeout=30) as resp:
            body = _facade().json.loads(resp.read().decode("utf-8", errors="replace"))
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        code = str(data.get("code") or "").strip().upper()
        if len(code) == 6:
            return code
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("surface audit: digest-identity fetch failed: %s", exc)
    return ""


async def _inject_admin_digest(context: _facade().Any, code: str) -> None:
    c = str(code or "").strip().upper()
    if not c:
        return
    payload = _facade().json.dumps({"code": c, "ts": int(__import__("time").time() * 1000)})
    script = (
        "(function(){try{localStorage.setItem('xcmax_digest_identity_code',"
        + _facade().json.dumps(payload)
        + ");}catch(e){}})();"
    )
    await context.add_init_script(script)


async def _prepare_admin_digest(context: _facade().Any, auth: _facade().Dict[str, str]) -> None:
    code = _facade()._fetch_admin_digest_code_sync(auth)
    if code:
        try:
            api_base = (
                (
                    _facade().os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
                    or _facade()._internal_api_base()
                )
                .strip()
                .rstrip("/")
            )
            payload = _facade().json.dumps({"code": code}).encode("utf-8")
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            csrf = str(auth.get("csrf_token") or "").strip()
            if csrf:
                headers["X-CSRF-Token"] = csrf
            req = _facade().urllib.request.Request(
                f"{api_base}/api/auth/verify-admin-digest-code",
                data=payload,
                headers=headers,
                method="POST",
            )
            with _facade().urllib.request.urlopen(req, timeout=30):
                pass
        except RECOVERABLE_ERRORS as exc:
            _facade().logger.warning("surface audit: verify-admin-digest-code failed: %s", exc)
    await _facade()._inject_admin_digest(context, code)


def _cookie_url_for_auth(target_url: str, auth: _facade().Dict[str, _facade().Any]) -> str:
    for candidate in (target_url, str(auth.get("api_base") or "")):
        try:
            parsed = _facade().urllib.parse.urlsplit(candidate)
        except RECOVERABLE_ERRORS:
            continue
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/"
    return "http://127.0.0.1/"


async def _inject_market_auth(
    context: _facade().Any,
    auth: _facade().Dict[str, _facade().Any],
    target_url: str = "",
) -> None:
    cookies = auth.get("cookies") if isinstance(auth.get("cookies"), dict) else {}
    session_id = str(auth.get("session_id") or cookies.get("session_id") or "").strip()
    csrf = str(auth.get("csrf_token") or cookies.get("csrf_token") or "").strip()
    cookie_rows: _facade().List[_facade().Dict[str, str]] = []
    cookie_url = _facade()._cookie_url_for_auth(target_url, auth)
    for name, value in {
        **cookies,
        "session_id": session_id,
        "csrf_token": csrf,
    }.items():
        v = str(value or "").strip()
        if name and v:
            cookie_rows.append({"name": str(name), "value": v, "url": cookie_url})
    if cookie_rows:
        try:
            await context.add_cookies(cookie_rows)
        except RECOVERABLE_ERRORS as exc:
            _facade().logger.warning(
                "surface audit: inject auth cookies failed url=%s err=%s",
                cookie_url,
                type(exc).__name__,
            )
    access = str(auth.get("access_token") or "").strip()
    if not access and (not session_id):
        return
    refresh = str(auth.get("refresh_token") or "").strip()
    account_kind = str(auth.get("account_kind") or "").strip()
    username = str(auth.get("username") or "").strip()
    market_user = {
        "username": username,
        "account_kind": account_kind,
        "market_is_enterprise": account_kind == "enterprise",
        "is_admin": account_kind == "admin",
    }
    script = (
        "(function(){try{"
        + (
            f"localStorage.setItem('modstore_token', {_facade().json.dumps(access)});"
            if access
            else ""
        )
        + (
            f"localStorage.setItem('xcagi_market_access_token', {_facade().json.dumps(access)});"
            if access
            else ""
        )
        + (
            f"localStorage.setItem('modstore_refresh_token', {_facade().json.dumps(refresh)});localStorage.setItem('xcagi_market_refresh_token', {_facade().json.dumps(refresh)});"
            if refresh
            else ""
        )
        + (
            f"localStorage.setItem('xcagi_surface_audit_session_id', {_facade().json.dumps(session_id)});"
            if session_id
            else ""
        )
        + f"localStorage.setItem('xcagi_market_user_json', {_facade().json.dumps(_facade().json.dumps(market_user, ensure_ascii=False))});"
        + "}catch(e){}})();"
    )
    await context.add_init_script(script)


async def _goto_with_retry(page: _facade().Any, url: str, *, timeout_ms: int) -> _facade().Any:
    """远程站点易抖动：domcontentloaded 失败后降级 commit 再试（对齐 run_surface_audit.mjs）。"""
    try:
        return await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except RECOVERABLE_ERRORS as first_exc:
        try:
            resp = await page.goto(url, wait_until="commit", timeout=timeout_ms)
        except RECOVERABLE_ERRORS:
            raise first_exc
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except RECOVERABLE_ERRORS:
            pass
        return resp
