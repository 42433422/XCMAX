"""base-web-admin（自托管 Web 管理端基座）Web 管理端真机验收用例。

impl 参考：/api/auth/me（会话身份）、/api/xcmax/admin/modules（服务器模块注册表）、
/api/platform-shell/capabilities（平台能力清单）、/api/admin/audit-logs（鉴权面）。
管理端 UI：/admin/（单页后台，重定向 /admin/xcmax-admin 服务器后台总览）。
"""

import html as _html
import json as _json

FEATURE = "base-web-admin"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，CDP 真实鼠标键盘）在自托管 Web 管理端完成："
    "管理员登录建立会话 → /admin/ 单页后台真实渲染并显示产品版本 → "
    "服务器模块注册表与平台能力清单真实读取 → 无会话上下文访问管理接口被拒。"
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


def _render(page, env, route, name=None, wait_for=None, tries=12):
    page.goto(env["base"] + route, wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(tries):
        page.wait_for_timeout(2000)
        text = page.inner_text("body") or ""
        if wait_for is None or wait_for in text:
            break
    if name:
        page.screenshot(path=str(env["shot"] / name))
    return text


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


def _login(page, env, username="admin", password="admin123"):
    page.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1500)
    try:
        page.fill("input[name=username], #username, input[type=text]", username, timeout=5000)
        page.fill("input[name=password], #password, input[type=password]", password, timeout=5000)
        page.click("button[type=submit], text=登 录", timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(2500)


def case_login_session(page, env):
    _login(page, env)
    r = _api(page, "/api/auth/me")
    d = r.get("body") or {}
    user = d.get("user") or {}
    ok = r["status"] == 200 and d.get("success") is True and user.get("role") == "admin"
    _card(page, env, "BW1-session-me.png", "BW1", "管理员登录并建立管理会话（真实浏览器）",
          "GET /api/auth/me", r["status"],
          {"me_status": r["status"], "success": d.get("success"),
           "username": user.get("username"), "role": user.get("role"),
           "account_kind": user.get("account_kind"), "tenant_id": user.get("tenant_id"),
           "url": page.url})
    return {"me_status": r["status"], "success": d.get("success"),
            "username": user.get("username"), "role": user.get("role"),
            "url": page.url}, ok


def case_admin_overview(page, env):
    text = _render(page, env, "/admin/", name="BW2-admin-overview.png",
                   wait_for="服务器后台总览")
    ok = ("服务器后台总览" in text and "1.0.0.5" in text)
    return {"final_url": page.url, "title": page.title(),
            "has_overview_title": "服务器后台总览" in text,
            "has_version": "1.0.0.5" in text,
            "text_head": text.replace("\n", " ")[:240]}, ok


def case_module_registry(page, env):
    mr = _api(page, "/api/xcmax/admin/modules")
    cr = _api(page, "/api/platform-shell/capabilities")
    md = mr.get("body") or {}
    cd = cr.get("body") or {}
    modules = md.get("modules") or md.get("data") or []
    edition = cd.get("edition") or (cd.get("data") or {}).get("edition")
    ok = (mr["status"] == 200 and len(modules) > 0
          and cr["status"] == 200 and bool(edition))
    _card(page, env, "BW3-module-registry.png", "BW3", "服务器模块注册表与平台能力清单真实读取",
          "GET /api/xcmax/admin/modules + GET /api/platform-shell/capabilities", mr["status"],
          {"modules_status": mr["status"], "module_count": len(modules),
           "capabilities_status": cr["status"], "edition": edition})
    return {"modules_status": mr["status"], "module_count": len(modules),
            "capabilities_status": cr["status"], "edition": edition}, ok


def case_unauth_denied(page, env):
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(1200)
    r = _api(pg, "/api/admin/audit-logs")
    ctx.close()
    b = r.get("body") or {}
    ok = r["status"] in (401, 403)
    _card(page, env, "BW4-unauth-denied.png", "BW4", "未登录会话访问管理接口被拒绝",
          "GET /api/admin/audit-logs (no session)", r["status"], b)
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "BW1", "title": "管理员登录并建立管理会话（真实浏览器）",
     "input": "管理端账号与密码，在 /admin/login 真实输入。",
     "actions": "真实键盘输入并点击「登 录」；随后在页面上下文复核 GET /api/auth/me。",
     "expected": "登录成功且 me 返回 role=admin。",
     "run": case_login_session},
    {"id": "BW2", "title": "自托管管理端总览页真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/，等待 SPA 重定向与渲染，读取正文关键信息。",
     "expected": "渲染出「服务器后台总览」且显示本产品版本 1.0.0.5。",
     "run": case_admin_overview},
    {"id": "BW3", "title": "服务器模块注册表与平台能力清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/xcmax/admin/modules 与 GET /api/platform-shell/capabilities。",
     "expected": "两者均 200；模块清单非空；能力清单含 edition。",
     "run": case_module_registry},
    {"id": "BW4", "title": "未登录会话访问管理接口被拒绝",
     "input": "全新的无会话浏览器上下文。",
     "actions": "无 cookie/token 上下文 fetch GET /api/admin/audit-logs。",
     "expected": "被拒绝（401/403），不返回管理数据。",
     "run": case_unauth_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「管理员登录 · 管理员账号 · 仅限运营人员」，账号框已填 admin、密码框掩码，按钮「登 录」。",
    "BW1-session-me.png": "JSON：GET /api/auth/me 200 success=true，user.username=admin、role=admin、account_kind=admin、tenant_id=null。",
    "BW2-admin-overview.png": "「服务器后台总览」页真实渲染：本地节点 版本 1.0.0.5、数据库 ok、本地地址 127.0.0.1:42423；远端服务器离线；模块注册表 90 个模块；左侧运维导航。",
    "BW3-module-registry.png": "JSON：modules_status=200、module_count=90（xcmax-admin/chat/ai-ecosystem…）；capabilities_status=200、edition=full。",
    "BW4-unauth-denied.png": "无会话 GET /api/admin/audit-logs → status=401、error_code=http_401、UNAUTHORIZED 请先登录。",
    "__video__": "录像（webm，25.96s，VP8 1600x1000）：登录 → 总览页渲染 → 会话/模块接口应答 → 无会话拒绝。",
}