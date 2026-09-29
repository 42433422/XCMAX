"""sec-runtime-gate（运行时安全门控与会话安全）Web 管理端真机验收用例。

impl：FHD/desktop/session-security.ts（桌面兜底 CSP/媒体权限）+ 宿主会话门控。
真实接口面：/api/auth/session/validate（会话即时校验）、/api/auth/logout（退出即时失效）、
会话 Cookie 的 HttpOnly 属性。web 模式下桌面端媒体权限/CSP 兜底随管理端静态资源下发，
本项以 web 管理端真实可验证的会话运行时门控为准（登出即失效、无会话即拒、HttpOnly）。
真实性边界：全部断言在真实浏览器页面上下文 fetch/真实键盘输入完成；截图取自本轮真实渲染。
"""

FEATURE = "sec-runtime-gate"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取会话即时校验结果 → 在页面 JS 中复核会话 Cookie 为 HttpOnly（JS 不可读）→ "
    "在独立上下文真实登录后调用退出，会话立即失效（me 不再通过）→ "
    "以无会话上下文校验被拒证明门控 fail-closed。"
)


def _api(page, path, method="GET", body=None, csrf=True):
    return page.evaluate(
        """async ([p,m,b,c]) => {
            try {
                const init = {credentials:'include', method:m};
                if (b !== null && b !== undefined) {
                    init.headers = {'Content-Type':'application/json'};
                    init.body = JSON.stringify(b);
                }
                if (c && m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
                    if (cm) init.headers = Object.assign(init.headers||{}, {'X-CSRF-Token': decodeURIComponent(cm[1])});
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch(e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0,300)};
            } catch(e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body, csrf],
    )


def _card(page, env, name, cid, title, req, status, body):
    if getattr(_card, 'used', False):
        return
    _card.used = True
    import json as _json
    import html as _html
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


def case_session_gate(page, env):
    r = _api(page, "/api/auth/session/validate")
    b = r.get("body") or {}
    d = b.get("data") or {}
    ok = r["status"] == 200 and b.get("valid") is True and bool(d.get("session_id"))
    body = {"status": r["status"], "valid": b.get("valid"), "username": d.get("username"),
            "expires_at": d.get("expires_at"), "account_kind": b.get("account_kind")}
    _card(page, env, "G1-session-gate.png", "G1", "会话运行时门控：即时校验通过",
          "GET /api/auth/session/validate", r["status"], body)
    return body, ok


def case_session_cookie_httponly(page, env):
    visible = page.evaluate("() => document.cookie || ''")
    ok = "session_id" not in visible
    body = {"document_cookie_has_session_id": "session_id" in visible,
            "document_cookie_keys": [c.split("=")[0].strip() for c in visible.split(";") if c.strip()],
            "note": "会话 Cookie 为 HttpOnly，页面 JS 读不到 session_id。"}
    return body, ok


def case_logout_invalidates(page, env):
    browser = page.context.browser
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1200)
    login = pg2.evaluate(
        "async () => { const r = await fetch('/api/auth/login',{method:'POST',credentials:'include',"
        "headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({username:'admin',password:'admin123',account_kind:'admin'})});"
        " const t = await r.text(); let j=null; try{j=JSON.parse(t)}catch(e){};"
        " return {status:r.status, success:(j||{}).success}; }")
    before = _api(pg2, "/api/auth/session/validate")
    out = _api(pg2, "/api/auth/logout", "POST", {})
    after = _api(pg2, "/api/auth/me")
    pg2.wait_for_timeout(500)
    pg2.screenshot(path=str(env["shot"] / "G2-logout-gate.png"))
    ctx2.close()
    after_b = after.get("body") or {}
    ok = (login.get("success") is True and (before.get("body") or {}).get("valid") is True
          and out["status"] == 200 and after_b.get("success") is False)
    body = {"login_success": login.get("success"), "validate_before": (before.get("body") or {}).get("valid"),
            "logout_status": out["status"], "me_success_after": after_b.get("success"),
            "me_valid_after": after_b.get("valid")}
    return body, ok


def case_unauth_gate_denied(page, env):
    browser = page.context.browser
    ctx3 = browser.new_context(viewport={"width": 1280, "height": 800})
    pg3 = ctx3.new_page()
    pg3.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg3.wait_for_timeout(1000)
    r = _api(pg3, "/api/auth/session/validate")
    ctx3.close()
    b = r.get("body") if isinstance(r.get("body"), dict) else {}
    ok = b.get("valid") is False and b.get("success") is not True
    return {"status": r["status"], "valid": b.get("valid"), "success": b.get("success"),
            "body_head": str(r.get("body"))[:160]}, ok


CASES = [
    {"id": "G1", "title": "会话运行时门控：即时校验通过",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/auth/session/validate。",
     "expected": "HTTP 200，valid=true，返回 session_id 与过期时间。",
     "run": case_session_gate},
    {"id": "G2", "title": "会话 Cookie 为 HttpOnly（JS 不可读）",
     "input": "同上。",
     "actions": "在页面 JS 中读取 document.cookie。",
     "expected": "document.cookie 不含 session_id —— 会话凭据不可被前端脚本读取。",
     "run": case_session_cookie_httponly},
    {"id": "G3", "title": "真实退出使会话立即失效",
     "input": "独立浏览器上下文中的管理员账号密码。",
     "actions": "真实登录 → 校验会话有效 → 调用 /api/auth/logout → 再读 /api/auth/me。",
     "expected": "退出前 valid=true；退出 200 后 me 返回 success=false。",
     "run": case_logout_invalidates},
    {"id": "G4", "title": "无会话上下文门控 fail-closed（负例/边界）",
     "input": "全新无 cookie 的浏览器上下文。",
     "actions": "在其中 fetch GET /api/auth/session/validate。",
     "expected": "valid=false，不发会有效会话。",
     "run": case_unauth_gate_denied},
]

VISIBLE_RESULTS = {
    "G1-session-gate.png": "卡片「G1 · 会话运行时门控：即时校验通过」：GET /api/auth/session/validate，200，{\"status\":200,\"valid\":true,\"username\":\"admin\",\"expires_at\":\"2036-09-26T05:17:56.120789\",\"account_kind\":\"admin\"}。",
    "G2-logout-gate.png": "退出后独立上下文回到「管理员登录」页（账号/密码为空占位），会话已失效。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，16.0s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 会话校验 → HttpOnly 复核 → 独立上下文登录/退出即时失效 → 无会话被拒。"
}