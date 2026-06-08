#!/usr/bin/env python3
"""为 MODstore daily_digest_surface_audit 注入 AI 市场登录（modstore_token）。"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py"
)

MARKER = "_path_needs_market_auth"

DOC_OLD = "- ``MODSTORE_DAILY_SURFACE_ANALYSIS_USER_ID``：分析调用 bench LLM 使用的用户 ID（默认同 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。\n\"\"\""
DOC_NEW = """- ``MODSTORE_DAILY_SURFACE_ANALYSIS_USER_ID``：分析调用 bench LLM 使用的用户 ID（默认同 ``MODSTORE_DAILY_BRIEF_USER_ID`` 或 ``0``）。
- ``MODSTORE_SURFACE_AUDIT_USER`` / ``MODSTORE_SURFACE_AUDIT_PASSWORD``：AI 市场 SPA 截图前登录（默认 ``admin`` / ``admin123``）。
- ``MODSTORE_SURFACE_AUDIT_API_URL``：登录 API 根（默认 ``MODSTORE_INTERNAL_API_BASE`` 或站点 ``base_url``）。
\"\"\""""

HELPERS = '''

_MARKET_AUTH_SKIP_PREFIXES: Tuple[str, ...] = (
    "/market/login",
    "/market/register",
    "/market/login-email",
    "/market/forgot-password",
)


def _path_needs_market_auth(path: str) -> bool:
    """除登录/注册外，/market/* SPA 页注入 modstore_token（workbench/download 等需登录）。"""
    p = str(path or "").strip()
    if not p.startswith("/market"):
        return False
    for skip in _MARKET_AUTH_SKIP_PREFIXES:
        if p == skip or p.startswith(skip + "/") or p.startswith(skip + "?"):
            return False
    return True


def _parse_set_cookie_headers(headers: Any) -> Dict[str, str]:
    jar: Dict[str, str] = {}
    raw_lines: List[str] = []
    if headers is None:
        return jar
    if hasattr(headers, "get_all"):
        try:
            raw_lines = list(headers.get_all("Set-Cookie") or [])
        except Exception:
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


def _login_surface_audit_sync() -> Dict[str, str]:
    """Playwright 截图前登录 MODstore，写入 modstore_token（对齐 FHD surface_audit_auth.mjs）。"""
    api_base = (
        os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
        or os.environ.get("MODSTORE_INTERNAL_API_BASE")
        or _base_url()
    ).strip().rstrip("/")
    user = (os.environ.get("MODSTORE_SURFACE_AUDIT_USER") or "admin").strip()
    password = (os.environ.get("MODSTORE_SURFACE_AUDIT_PASSWORD") or "admin123").strip()
    account_kind = (os.environ.get("MODSTORE_SURFACE_AUDIT_ACCOUNT_KIND") or "admin").strip()

    cookies: Dict[str, str] = {}

    def _req(url: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, str]]:
        headers = {"User-Agent": "MODstore-surface-audit/1.0", "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
            csrf = cookies.get("csrf_token") or ""
            if csrf:
                headers["X-CSRF-Token"] = csrf
            cookie_hdr = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
            if cookie_hdr:
                headers["Cookie"] = cookie_hdr
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        else:
            req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            cookies.update(_parse_set_cookie_headers(resp.headers))
            return body, cookies

    try:
        _req(f"{api_base}/api/health")
        web, _ = _req(
            f"{api_base}/api/auth/login",
            {"username": user, "password": password, "account_kind": account_kind},
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("surface audit: market login failed base=%s err=%s", api_base, exc)
        return {}

    ok = bool(web.get("ok") or web.get("success"))
    access = str(web.get("access_token") or web.get("token") or "").strip()
    refresh = str(web.get("refresh_token") or "").strip()
    if not ok or not access:
        logger.warning(
            "surface audit: market login rejected base=%s msg=%s",
            api_base,
            web.get("message") or web.get("error") or "no access_token",
        )
        return {}
    return {"access_token": access, "refresh_token": refresh, "username": user}


async def _inject_market_auth(context: Any, auth: Dict[str, str]) -> None:
    access = str(auth.get("access_token") or "").strip()
    if not access:
        return
    refresh = str(auth.get("refresh_token") or "").strip()
    script = (
        "(function(){"
        f"localStorage.setItem('modstore_token', {json.dumps(access)});"
        + (
            f"localStorage.setItem('modstore_refresh_token', {json.dumps(refresh)});"
            if refresh
            else ""
        )
        + "})();"
    )
    await context.add_init_script(script)

'''

LOOP_OLD = """                context = await browser.new_context(**ctx_kwargs)
                page = await context.new_page()
                row = await _capture_one("""

LOOP_NEW = """                context = await browser.new_context(**ctx_kwargs)
                if market_auth and _path_needs_market_auth(target.path):
                    await _inject_market_auth(context, market_auth)
                page = await context.new_page()
                row = await _capture_one("""

LOGIN_BLOCK = """    market_auth = _login_surface_audit_sync()
    if market_auth:
        logger.info("surface audit: market login ok user=%s", market_auth.get("username"))
    else:
        logger.warning("surface audit: market login skipped/failed; /market/* may capture login redirect")

    async with async_playwright() as pw:"""


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("already patched", TARGET)
        return

    if DOC_OLD in text:
        text = text.replace(DOC_OLD, DOC_NEW, 1)

    anchor = "async def _wait_page_ready(page: Any, *, timeout_ms: int) -> None:"
    if anchor not in text:
        raise SystemExit("anchor _wait_page_ready not found")
    text = text.replace(anchor, HELPERS.strip() + "\n\n\n" + anchor, 1)

    if LOOP_OLD not in text:
        raise SystemExit("capture loop anchor not found")
    text = text.replace(LOOP_OLD, LOOP_NEW, 1)

    old_pw = "    async with async_playwright() as pw:"
    if LOGIN_BLOCK.split("\n")[0] not in text:
        if old_pw not in text:
            raise SystemExit("async_playwright block not found")
        text = text.replace(old_pw, LOGIN_BLOCK, 1)

    TARGET.write_text(text, encoding="utf-8")
    print("patched", TARGET)


if __name__ == "__main__":
    main()
