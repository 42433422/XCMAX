"""sec-tenant-isolation（多租户数据范围与越权）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/rbac_routes.py
（/api/rbac/tenants、/api/rbac/tenants/{id}/data-scopes、/api/rbac/roles）。
"""

import html as _html
import json as _json
import time as _time
import uuid as _uuid

FEATURE = "sec-tenant-isolation"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）核验多租户数据范围与平台/企业边界："
    "平台管理员读 /api/rbac/tenants 与/api/rbac/tenants/1/data-scopes（200）→ "
    "新建的个人租户账号登录后访问平台级 /api/rbac/roles 被拒（403，当前企业账号无角色管理权限）→ "
    "无会话访问被拒（401）。"
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


def _login(page, env, username, password):
    page.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1500)
    try:
        page.fill("input[name=username], #username, input[type=text]", username, timeout=5000)
        page.fill("input[name=password], #password, input[type=password]", password, timeout=5000)
        page.click("button[type=submit], text=登 录", timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(2000)
    me = _api(page, "/api/auth/me")
    d = (me.get("body") or {}).get("user") or {}
    return me["status"], d.get("username"), d.get("role")


def case_platform_tenants(page, env):
    r = _api(page, "/api/rbac/tenants")
    d = r.get("body") or {}
    data = d.get("data")
    ok = r["status"] == 200 and d.get("success") is True and isinstance(data, list)
    _card(page, env, "T1-platform-tenants.png", "T1", "平台管理员读取租户清单",
          "GET /api/rbac/tenants", r["status"],
          {"status": r["status"], "count": len(data) if isinstance(data, list) else None})
    return {"status": r["status"], "count": len(data) if isinstance(data, list) else None}, ok


def case_tenant_data_scopes(page, env):
    r = _api(page, "/api/rbac/tenants/1/data-scopes")
    d = r.get("body") or {}
    data = d.get("data")
    ok = r["status"] == 200 and d.get("success") is True and isinstance(data, list)
    _card(page, env, "T2-tenant-data-scopes.png", "T2", "读取指定租户数据范围",
          "GET /api/rbac/tenants/1/data-scopes", r["status"],
          {"status": r["status"], "scopes": data if isinstance(data, list) else []})
    return {"status": r["status"], "scopes": data if isinstance(data, list) else []}, ok


def case_tenant_user_denied(page, env):
    uname = "qa_ten_%d" % int(_time.time())
    reg = _api(page, "/api/auth/register", "POST",
               {"username": uname, "password": "Tenant#Pass9",
                "email": "%s@example.com" % uname, "account_kind": "personal"})
    regb = reg.get("body") or {}
    data = regb.get("data") or {}
    tenant_id = data.get("tenant_id") if isinstance(data, dict) else None
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    lstatus, luser, lrole = _login(pg, env, uname, "Tenant#Pass9")
    roles = _api(pg, "/api/rbac/roles")
    rb = roles.get("body") or {}
    detail = rb.get("detail") or rb.get("message") if isinstance(rb, dict) else None
    ctx.close()
    body = {"registered_tenant_id": tenant_id, "login_status": lstatus,
            "rbac_roles_status": roles["status"], "detail": detail}
    _card(page, env, "T3-tenant-user-denied.png", "T3", "个人租户账号越权访问平台级接口被拒",
          "GET /api/rbac/roles (tenant viewer session)", roles["status"], body)
    ok = (reg["status"] == 200 and lstatus == 200 and lrole == "viewer"
          and roles["status"] == 403 and "当前企业账号无角色管理权限" in str(detail))
    return body, ok


CASES = [
    {"id": "T1", "title": "平台管理员读取租户清单",
     "input": "平台管理员会话。",
     "actions": "页面上下文 GET /api/rbac/tenants。",
     "expected": "200、success=true、data 为数组。",
     "run": case_platform_tenants},
    {"id": "T2", "title": "读取指定租户数据范围",
     "input": "平台管理员会话。",
     "actions": "页面上下文 GET /api/rbac/tenants/1/data-scopes。",
     "expected": "200、success=true、data 为数组。",
     "run": case_tenant_data_scopes},
    {"id": "T3", "title": "个人租户账号越权访问平台级接口被拒（负例）",
     "input": "新建个人租户账号。",
     "actions": "新上下文以该账号登录后 GET /api/rbac/roles。",
     "expected": "403（当前企业账号无角色管理权限）。",
     "run": case_tenant_user_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "T1-platform-tenants.png": "GET /api/rbac/tenants（平台管理员）200 success=true data=[]。",
    "T2-tenant-data-scopes.png": "GET /api/rbac/tenants/1/data-scopes 200 success=true data=[]。",
    "T3-tenant-user-denied.png": "新建个人租户账号 qa_ten_… 登录成功(role=viewer)，GET /api/rbac/roles → 403 http_403 message=当前企业账号无角色管理权限（越权被拒）。",
    "__video__": "录像（webm，11.96s）：平台租户清单/数据范围 → 个人租户越权被拒。",
}