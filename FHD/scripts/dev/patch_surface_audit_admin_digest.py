#!/usr/bin/env python3
"""P-W 管理端截图：admin 登录 + digest-identity 解锁 + 10 个 /market/admin 路由。"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py",
)

MARKER = "_fetch_admin_digest_code_sync"

ADMIN_PAGES = '''    for name, admin_path in (
        ("管理端·数据库管理", "/admin/database"),
        ("管理端·值班员工", "/admin/duty-employees"),
        ("管理端·运维审计", "/admin/ops-audit"),
        ("管理端·员工自主决策", "/admin/employee-autonomy"),
        ("管理端·变更请求", "/admin/change-requests"),
        ("管理端·员工入职", "/admin/yuangon-onboard"),
        ("管理端·编排任务", "/admin/orchestrate-jobs"),
        ("管理端·客服审核", "/admin/customer-service"),
        ("管理端·管家技能", "/admin/butler-skills"),
        ("管理端·AI 账号池", "/admin/ai-accounts"),
    ):
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                name,
                f"market:{admin_path}",
                "desktop",
                prepare="admin_digest",
            )
        )
'''

HELPERS = '''

def _fetch_admin_digest_code_sync(auth: Dict[str, str]) -> str:
    """从 MODstore 内网 API 拉取管理端 6 位校验码（对齐 FHD digest-identity）。"""
    api_base = (
        os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
        or os.environ.get("MODSTORE_INTERNAL_API_BASE")
        or "http://127.0.0.1:9990"
    ).strip().rstrip("/")
    headers = {"Accept": "application/json", "User-Agent": "MODstore-surface-audit/1.0"}
    token = str(auth.get("access_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    csrf = str(auth.get("csrf_token") or "").strip()
    if csrf:
        headers["X-CSRF-Token"] = csrf
    cookie_hdr = "; ".join(f"{k}={v}" for k, v in (auth or {}).items() if v and k in ("session_id", "csrf_token"))
    if cookie_hdr:
        headers["Cookie"] = cookie_hdr
    try:
        req = urllib.request.Request(f"{api_base}/api/xcmax/admin/digest-identity", headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        code = str(data.get("code") or "").strip().upper()
        if len(code) == 6:
            return code
    except Exception as exc:
        logger.warning("surface audit: digest-identity fetch failed: %s", exc)
    return ""


async def _inject_admin_digest(context: Any, code: str) -> None:
    c = str(code or "").strip().upper()
    if not c:
        return
    script = (
        "(function(){try{localStorage.setItem('xcmax_digest_identity_code',"
        + json.dumps(json.dumps({"code": c, "ts": int(__import__('time').time() * 1000)}))
        + ");}catch(e){}})();"
    )
    await context.add_init_script(script)


async def _prepare_admin_digest(context: Any, auth: Dict[str, str]) -> None:
    code = _fetch_admin_digest_code_sync(auth)
    if code:
        try:
            api_base = (
                os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
                or os.environ.get("MODSTORE_INTERNAL_API_BASE")
                or "http://127.0.0.1:9990"
            ).strip().rstrip("/")
            payload = json.dumps({"code": code}).encode("utf-8")
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            csrf = str(auth.get("csrf_token") or "").strip()
            if csrf:
                headers["X-CSRF-Token"] = csrf
            req = urllib.request.Request(
                f"{api_base}/api/auth/verify-admin-digest-code",
                data=payload,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30):
                pass
        except Exception as exc:
            logger.warning("surface audit: verify-admin-digest-code failed: %s", exc)
    await _inject_admin_digest(context, code)

'''

if __name__ == "__main__":
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("already patched", TARGET)
        sys.exit(0)
    if "def build_surface_targets" not in text:
        raise SystemExit("build_surface_targets not found")
    if HELPERS.strip() not in text:
        anchor = "async def _inject_market_auth"
        if anchor not in text:
            anchor = "def _login_surface_audit_sync"
        text = text.replace(anchor, HELPERS + "\n\n" + anchor, 1)
    if ADMIN_PAGES.strip() not in text:
        needle = "    return out\n"
        if needle not in text:
            raise SystemExit("return out anchor not found")
        text = text.replace(needle, ADMIN_PAGES + "\n" + needle, 1)
    TARGET.write_text(text, encoding="utf-8")
    print("patched admin digest + P-W admin pages", TARGET)
