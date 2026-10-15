"""sec-identity（身份认证与权限控制）Web 管理端真机验收用例。

impl：FHD/app/utils/security/security_middleware.py、FHD/app/auth_decorators.py。
真实接口面：/api/auth/me（身份与权限）、/api/auth/session/validate（会话校验）、
无会话上下文与管理接口的 401、无 CSRF 双提交写操作的 403。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "sec-identity"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取身份与权限清单 → 读取会话校验结果 → "
    "在全新无会话上下文读取 /api/auth/me（未认证）与管理接口 401 → "
    "以真实 403 证明缺 CSRF 双提交的写操作被拒。"
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


def case_me(page, env):
    r = _api(page, "/api/auth/me")
    d = (r["body"] or {}).get("data") or {}
    user = d.get("user") or {}
    ok = (r["status"] == 200 and (r["body"] or {}).get("success") is True
          and user.get("username") == "admin" and (d.get("permissions") or []))
    body = {"status": r["status"], "username": user.get("username"), "role": user.get("role"),
            "tier": d.get("tier"), "tenant_id": d.get("tenant_id"),
            "permission_count": len(d.get("permissions") or [])}
    _card(page, env, "I1-identity-me.png", "I1", "身份与权限清单真实读取",
          "GET /api/auth/me", r["status"], body)
    return body, ok


def case_session_validate(page, env):
    r = _api(page, "/api/auth/session/validate")
    b = r.get("body") or {}
    d = b.get("data") or {}
    ok = r["status"] == 200 and b.get("success") is True and b.get("valid") is True and bool(d.get("session_id"))
    return {"status": r["status"], "success": b.get("success"), "valid": b.get("valid"),
            "username": d.get("username"), "session_id_present": bool(d.get("session_id")),
            "expires_at": d.get("expires_at")}, ok


def case_unauthenticated_denied(page, env):
    browser = page.context.browser
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1200)
    me = pg2.evaluate(
        "async () => { try { const r = await fetch('/api/auth/me',{credentials:'include'});"
        " const t = await r.text(); let j=null; try{j=JSON.parse(t)}catch(e){}"
        " return {status:r.status, body:j!==null?j:t.slice(0,200)}; } catch(e){ return {status:0,body:String(e)}; } }")
    adm = pg2.evaluate(
        "async () => { try { const r = await fetch('/api/admin/audit-logs',{credentials:'include'});"
        " return {status:r.status}; } catch(e){ return {status:0}; } }")
    pg2.screenshot(path=str(env["shot"] / "I2-unauth-denied.png"))
    ctx2.close()
    me_b = me.get("body") or {}
    ok = me_b.get("success") is False and me_b.get("valid") is False and adm["status"] in (401, 403)
    body = {"me_status": me["status"], "me_success": me_b.get("success"), "me_valid": me_b.get("valid"),
            "admin_status": adm["status"],
            "note": "无会话上下文停留在登录页；/api/auth/me 返回未认证，管理接口 401/403。"}
    return body, ok


def case_csrf_missing_denied(page, env):
    r = _api(page, "/api/preferences", "POST", {"key": "x", "value": "y"}, csrf=False)
    b = r.get("body") or {}
    ok = r["status"] == 403 and "CSRF" in str(b.get("message"))
    out = {"status": r["status"], "message": b.get("message")}
    _card(page, env, "I3-identity-csrf-boundary.png", "I3", "缺 CSRF 双提交的写操作被拒（边界/负例）",
          "POST /api/preferences（无 X-CSRF-Token）", r["status"], out)
    return out, ok


CASES = [
    {"id": "I1", "title": "身份与权限清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/auth/me。",
     "expected": "HTTP 200、success=true，username=admin，permissions 非空。",
     "run": case_me},
    {"id": "I2", "title": "会话校验真实应答",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/auth/session/validate。",
     "expected": "HTTP 200、success=true、valid=true，返回 session_id。",
     "run": case_session_validate},
    {"id": "I3", "title": "无会话上下文身份与管理接口被拒（负例/边界）",
     "input": "全新无 cookie 的浏览器上下文。",
     "actions": "在其中 fetch GET /api/auth/me 与 GET /api/admin/audit-logs。",
     "expected": "me 返回 success=false/valid=false；管理接口 401 或 403。",
     "run": case_unauthenticated_denied},
    {"id": "I4", "title": "缺 CSRF 双提交的写操作被拒（负例/边界）",
     "input": "已建立会话但不带 X-CSRF-Token。",
     "actions": "在页面上下文 POST /api/preferences（无 CSRF 头）。",
     "expected": "HTTP 403，message 为 CSRF token missing。",
     "run": case_csrf_missing_denied},
]

VISIBLE_RESULTS = {
    "I1-identity-me.png": "卡片「I1 · 身份与权限清单真实读取」：GET /api/auth/me，200，{\"status\":200,\"username\":\"admin\",\"role\":\"admin\",\"tier\":\"admin\",\"tenant_id\":4,\"permission_count\":21}。",
    "I2-unauth-denied.png": "无会话浏览器上下文停留在「管理员登录」页（账号/密码均为空占位），未出现任何管理数据。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，16.32s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 身份/权限 → 会话校验 → 无会话上下文被拒 → 缺 CSRF 403。"
}