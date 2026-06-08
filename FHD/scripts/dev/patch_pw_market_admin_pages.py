#!/usr/bin/env python3
"""P-W 管理端：MODstore 工作台 /market/admin/* 十页 + digest 解锁。"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py",
)

MARKER = "_PW_MARKET_ADMIN_PAGES"

ADMIN_PAGES_CONST = '''
_PW_MARKET_ADMIN_PAGES: Tuple[Tuple[str, str], ...] = (
    ("管理端·数据库管理", "/market/admin/database"),
    ("管理端·值班员工", "/market/admin/duty-employees"),
    ("管理端·运维审计", "/market/admin/ops-audit"),
    ("管理端·员工自主决策", "/market/admin/employee-autonomy"),
    ("管理端·变更请求", "/market/admin/change-requests"),
    ("管理端·员工入职", "/market/admin/yuangon-onboard"),
    ("管理端·编排任务", "/market/admin/orchestrate-jobs"),
    ("管理端·客服审核", "/market/admin/customer-service"),
    ("管理端·管家技能", "/market/admin/butler-skills"),
    ("管理端·AI 账号池", "/market/admin/ai-accounts"),
)
'''

BUILD_LOOP = '''
    for name, path in _PW_MARKET_ADMIN_PAGES:
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                name,
                path,
                "desktop",
                prepare="admin_digest",
            )
        )

'''

HELPERS = '''

def _fetch_admin_digest_code_sync(auth: Dict[str, str]) -> str:
    """从 MODstore API 拉取管理端 6 位校验码（对齐 FHD digest-identity 自签发）。"""
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
    try:
        req = urllib.request.Request(f"{api_base}/api/xcmax/admin/digest-identity", headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        data = body.get("data") if isinstance(body.get("data"), dict) else body
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
    payload = json.dumps({"code": c, "ts": int(__import__("time").time() * 1000)})
    script = (
        "(function(){try{localStorage.setItem('xcmax_digest_identity_code',"
        + json.dumps(payload)
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

APPLY_PREPARE_BRANCH = '''    if prepare == "admin_digest":
        try:
            unlock_btn = page.get_by_role("button", name=re.compile("解锁管理端"))
            if await unlock_btn.is_visible(timeout=2500):
                await unlock_btn.click(timeout=5000)
                await page.wait_for_timeout(1000)
        except Exception:
            pass
        try:
            await page.wait_for_selector(".wb-sidebar-admin-nav, #app .app-shell", timeout=12_000)
        except Exception:
            pass
        return
'''

CAPTURE_CTX_PATCH = '''                if market_auth and _path_needs_market_auth(target.path):
                    await _inject_market_auth(context, market_auth)
                if target.prepare == "admin_digest" and market_auth:
                    await _prepare_admin_digest(context, market_auth)
'''


def _replace_old_admin_block(text: str) -> str:
    """移除旧 FHD admin-console 五页（若存在）。"""
    old_snippets = (
        '("/xcmax-admin")',
        '("/automation-policy")',
        'prepare="admin_digest"',
        'f"admin:',
    )
    if '("/xcmax-admin")' not in text:
        return text
    import re

    text = re.sub(
        r"\n    for name, admin_path in \(\n"
        r'        \("管理端·服务器总览".*?\n'
        r"    \):\n"
        r"        out\.append\(\n"
        r"            SurfaceTarget\(\n"
        r'                "P-W".*?\n'
        r"            \)\n"
        r"        \)\n",
        "\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    return text


if __name__ == "__main__":
    text = TARGET.read_text(encoding="utf-8")
    changed = False

    if MARKER not in text:
        anchor = "_PW_MARKET_ENTRY_PAGES: Tuple[Tuple[str, str], ...] = ("
        if anchor not in text:
            raise SystemExit("_PW_MARKET_ENTRY_PAGES anchor not found")
        end = text.find("\n\n", text.find(anchor))
        if end < 0:
            raise SystemExit("could not locate end of _PW_MARKET_ENTRY_PAGES")
        text = text[:end] + ADMIN_PAGES_CONST + text[end:]
        changed = True

    text = _replace_old_admin_block(text)

    if "_fetch_admin_digest_code_sync" not in text:
        anchor = "async def _inject_market_auth"
        if anchor not in text:
            raise SystemExit("_inject_market_auth anchor not found")
        text = text.replace(anchor, HELPERS.strip() + "\n\n\n" + anchor, 1)
        changed = True

    if "_PW_MARKET_ADMIN_PAGES:" in text and "for name, path in _PW_MARKET_ADMIN_PAGES:" not in text:
        needle = "    for name, path in _PAPP_PUBLIC_PAGES:"
        if needle not in text:
            needle = "\n    return out\n"
            if needle not in text:
                raise SystemExit("build_surface_targets return anchor not found")
            text = text.replace(needle, BUILD_LOOP + needle, 1)
        else:
            text = text.replace(needle, BUILD_LOOP + needle, 1)
        changed = True

    if 'prepare == "admin_digest"' not in text:
        anchor = "async def _apply_page_prepare(page: Any, prepare: str, timeout_ms: int) -> None:"
        if anchor not in text:
            raise SystemExit("_apply_page_prepare not found")
        insert_at = text.find("    if prepare.startswith(\"ai_store_tab:\"):")
        if insert_at < 0:
            raise SystemExit("ai_store_tab branch not found")
        text = text[:insert_at] + APPLY_PREPARE_BRANCH + text[insert_at:]
        changed = True

    old_ctx = "                if market_auth and _path_needs_market_auth(target.path):\n                    await _inject_market_auth(context, market_auth)\n                page = await context.new_page()"
    if old_ctx in text and "_prepare_admin_digest" not in text:
        text = text.replace(
            old_ctx,
            CAPTURE_CTX_PATCH.strip()
            + "\n                page = await context.new_page()",
            1,
        )
        changed = True

    if changed:
        TARGET.write_text(text, encoding="utf-8")
        print("patched market admin pages + digest unlock", TARGET)
    else:
        print("already patched", TARGET)
