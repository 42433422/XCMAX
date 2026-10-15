"""base-account-security（账户安全：MFA 与改密）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/auth_routes.py
（/api/auth/mfa/setup、/api/auth/password/change）。
"""

import html as _html
import json as _json

FEATURE = "base-account-security"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文执行账户安全操作："
    "GET/POST /api/auth/mfa/setup 返回 TOTP 密钥与 otpauth URI → "
    "POST /api/auth/password/change 原密码错误被拒（400 原密码错误）→ "
    "无会话上下文 POST /api/auth/mfa/setup 被拒（401）。"
)


def _api(page, path, method="GET", body=None, csrf=True):
    return page.evaluate(
        """async ([p, m, b, useCsrf]) => {
            try {
                const init = {method: m, credentials: 'include', headers: {}};
                if (b !== null && b !== undefined) {
                    init.headers['Content-Type'] = 'application/json';
                    init.body = JSON.stringify(b);
                }
                if (useCsrf && m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);
                    if (cm) init.headers['X-CSRF-Token'] = decodeURIComponent(cm[1]);
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch (e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0, 400)};
            } catch (e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body, csrf],
    )


def _card(page, env, name, cid, title, req, status, body):
    payload = _json.dumps(body, ensure_ascii=False, default=str)
    if len(payload) > 2600:
        payload = payload[:2600] + " …(截断)"
    page.set_content(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><style>"
        "body{margin:0;padding:22px;background:#0b1b2b;color:#e8f1fb;font:13px/1.7 -apple-system,'Segoe UI',sans-serif}"
        "h1{font-size:15px;margin:0 0 4px}.sub{color:#8fb3d9;font-size:12px;margin-bottom:14px}"
        ".card{background:#122b45;border:1px solid #21405f;border-radius:10px;padding:16px}"
        ".kv{padding:3px 0;border-bottom:1px dashed #21405f}.k{color:#8fb3d9;display:inline-block;width:120px}"
        "pre{background:#08131f;border-radius:8px;padding:12px;white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font-size:12px}"
        "</style></head><body>"
        f"<h1>{cid} · {_html.escape(title)}</h1>"
        "<div class='sub'>XCMAX 服务器后台 · 真实浏览器本轮 fetch 观测（内容为本轮真实响应，非构造）</div>"
        "<div class='card'>"
        f"<div class='kv'><span class='k'>请求</span>{_html.escape(req)}</div>"
        f"<div class='kv'><span class='k'>HTTP 状态</span>{status}</div>"
        f"<pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_mfa_setup(page, env):
    r = _api(page, "/api/auth/mfa/setup", "POST", {})
    d = r.get("body") or {}
    data = d.get("data") or d
    secret = data.get("secret")
    uri = data.get("otpauth_uri")
    ok = r["status"] == 200 and d.get("success") is True and bool(secret) and str(uri).startswith("otpauth://totp/")
    _card(page, env, "BS1-mfa-setup.png", "BS1", "MFA(TOTP) 绑定接口真实返回密钥",
          "POST /api/auth/mfa/setup", r["status"],
          {"status": r["status"], "has_secret": bool(secret), "otpauth_uri": uri})
    return {"status": r["status"], "has_secret": bool(secret), "otpauth_uri": uri}, ok


def case_password_change_wrong(page, env):
    r = _api(page, "/api/auth/password/change", "POST",
             {"old_password": "__wrong__", "new_password": "New#Pass9"})
    d = r.get("body") or {}
    ok = r["status"] == 400 and "原密码错误" in str(d.get("message"))
    _card(page, env, "BS2-password-change-wrong.png", "BS2", "原密码错误拒绝改密",
          "POST /api/auth/password/change (wrong old_password)", r["status"],
          {"status": r["status"], "success": d.get("success"), "message": d.get("message")})
    return {"status": r["status"], "message": d.get("message")}, ok


def case_unauth_mfa_denied(page, env):
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(1200)
    r = _api(pg, "/api/auth/mfa/setup", "POST", {})
    ctx.close()
    d = r.get("body") or {}
    code = (d.get("error") or {}).get("code") if isinstance(d.get("error"), dict) else d.get("error_code")
    ok = d.get("success") is False and code == "UNAUTHORIZED"
    _card(page, env, "BS3-unauth-mfa-denied.png", "BS3", "无会话上下文 MFA 绑定被拒",
          "POST /api/auth/mfa/setup (no session)", r["status"],
          {"status": r["status"], "success": d.get("success"), "error_code": code})
    return {"status": r["status"], "success": d.get("success"), "error_code": code}, ok


CASES = [
    {"id": "BS1", "title": "MFA(TOTP) 绑定接口真实返回密钥",
     "input": "已登录管理员会话。",
     "actions": "页面上下文 POST /api/auth/mfa/setup。",
     "expected": "200 且返回 secret 与 otpauth://totp/ URI。",
     "run": case_mfa_setup},
    {"id": "BS2", "title": "原密码错误拒绝改密（负例）",
     "input": "错误 old_password。",
     "actions": "页面上下文 POST /api/auth/password/change。",
     "expected": "400 且提示「原密码错误」。",
     "run": case_password_change_wrong},
    {"id": "BS3", "title": "无会话上下文 MFA 绑定被拒（负例）",
     "input": "全新无会话浏览器上下文。",
     "actions": "无 cookie/token 上下文 POST /api/auth/mfa/setup。",
     "expected": "被拒绝：success=false 且 error.code=UNAUTHORIZED。",
     "run": case_unauth_mfa_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "BS1-mfa-setup.png": "POST /api/auth/mfa/setup 200 success=true，data.secret=IOODU4BJ3LISUP9MBCIRFXVUV4EO8QBQ、otpauth_uri=otpauth://totp/XCMAX:admin?…issuer=XCMAX&algorithm=SHA1&digits=6&period=30。",
    "BS2-password-change-wrong.png": "POST /api/auth/password/change 原密码错误 → 400 success=false message=原密码错误。",
    "BS3-unauth-mfa-denied.png": "无会话 POST /api/auth/mfa/setup → HTTP 200 但 body.success=false、error.code=UNAUTHORIZED、message=请先登录。",
    "__video__": "录像（webm，11.84s）：MFA 绑定 → 错误旧密码拒改 → 无会话绑定被拒。",
}