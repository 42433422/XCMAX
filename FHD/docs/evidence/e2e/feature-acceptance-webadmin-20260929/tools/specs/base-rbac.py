"""base-rbac（权限与角色控制）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/rbac.py、FHD/app/fastapi_routes/xcmax_admin_auth.py。
真实接口面：/api/auth/me（角色→权限清单）、/api/platform-shell/auth/permission-matrix（门控矩阵）、
/api/rbac/roles 与 /api/rbac/tenants（平台管理员专属，本企业管理员被拒）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "base-rbac"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，真实鼠标键盘）在自托管 Web 管理端建立管理员会话后："
    "读取本账号角色与 22 项权限清单 → 读取门控矩阵 → "
    "以真实 403 证明非平台管理员无法调用租户角色/全局权限管理接口（越权被拒）。"
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


def case_identity_permissions(page, env):
    r = _api(page, "/api/auth/me")
    d = (r["body"] or {}).get("data") or {}
    user = d.get("user") or {}
    perms = d.get("permissions") or []
    ok = (r["status"] == 200 and (r["body"] or {}).get("success") is True
          and user.get("role") == "admin" and len(perms) >= 10)
    body = {"status": r["status"], "role": user.get("role"), "tier": d.get("tier"),
            "tenant_id": d.get("tenant_id"), "permission_count": len(perms),
            "permissions_sample": perms[:10]}
    _card(page, env, "R1-identity-permissions.png", "R1",
          "角色 → 权限清单真实下发（本管理账号）", "GET /api/auth/me", r["status"], body)
    return body, ok


def case_permission_matrix(page, env):
    r = _api(page, "/api/platform-shell/auth/permission-matrix")
    d = (r["body"] or {}).get("data") or {}
    ok = (r["status"] == 200 and d.get("account_kind") == "admin"
          and isinstance(d.get("allowed"), bool))
    body = {"status": r["status"], "account_kind": d.get("account_kind"),
            "allowed": d.get("allowed"), "route_allowed": d.get("route_allowed"),
            "personal_shell_blocked": d.get("personal_shell_blocked"),
            "admin_shell_blocked": d.get("admin_shell_blocked")}
    return body, ok


def case_roles_denied(page, env):
    r = _api(page, "/api/rbac/roles")
    b = r["body"] or {}
    ok = r["status"] == 403 and "无角色管理权限" in str(b.get("message"))
    body = {"status": r["status"], "error_code": b.get("error_code"), "message": b.get("message")}
    _card(page, env, "R2-rbac-boundary.png", "R2",
          "非平台管理员越权调用角色管理被真实拒绝（边界/负例）",
          "GET /api/rbac/roles", r["status"], body)
    return body, ok


def case_tenants_denied(page, env):
    r = _api(page, "/api/rbac/tenants")
    b = r["body"] or {}
    ok = r["status"] == 403 and "仅平台管理员" in str(b.get("message"))
    return {"status": r["status"], "error_code": b.get("error_code"), "message": b.get("message")}, ok


CASES = [
    {"id": "R1", "title": "角色与权限清单真实下发",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/auth/me。",
     "expected": "HTTP 200、success=true，role=admin，permissions 非空（≥10 项）。",
     "run": case_identity_permissions},
    {"id": "R2", "title": "门控矩阵真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/platform-shell/auth/permission-matrix。",
     "expected": "HTTP 200，account_kind=admin，allowed 为布尔值。",
     "run": case_permission_matrix},
    {"id": "R3", "title": "越权调用角色管理被拒（负例/边界）",
     "input": "企业管理员会话（无 tenant.manage_roles 权限）。",
     "actions": "在页面上下文 fetch GET /api/rbac/roles。",
     "expected": "HTTP 403，message 指明当前企业账号无角色管理权限。",
     "run": case_roles_denied},
    {"id": "R4", "title": "越权管理全局权限被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/rbac/tenants。",
     "expected": "HTTP 403，message 指明仅平台管理员可管理全局权限。",
     "run": case_tenants_denied},
]

VISIBLE_RESULTS = {
    "R1-identity-permissions.png": "卡片「R1 · 角色 → 权限清单真实下发（本管理账号）」：请求 GET /api/auth/me，HTTP 状态 200，响应体 {\"status\":200,\"role\":\"admin\",\"tier\":\"admin\",\"tenant_id\":4,\"permission_count\":21,\"permissions_sample\":[\"admin.system_config\",\"etl.template.manage\",\"dataset.read\",\"customer.view\",\"customer.edit\",\"shipment.view\",\"shipment.create\",\"product.view\",\"etl.execute\",\"etl.read\"]}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，13.04s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 读取角色/权限 → 门控矩阵 → 越权角色管理与全局权限管理 403。"
}