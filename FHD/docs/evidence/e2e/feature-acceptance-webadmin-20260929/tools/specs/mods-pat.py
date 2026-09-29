"""mods-pat（PAT / JWT 与权限控制）Web 管理端真机验收用例。

被测对象：以 web 模式运行的自托管管理端后端（http://127.0.0.1:42423）。
实现面：FHD/app/infrastructure/mods/mod_auth.py —— Mod 接入凭证与权限上下文
（ModContext.from_request、ModContextMiddleware、/api/mod/{mod_id} 的路径级 mod 上下文、
require_verified_mod 等）；以及会话 JWT 与市场凭证的权限边界。

真实性边界：所有断言都在真实浏览器里用页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "mods-pat"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 系统设置页真实渲染 → "
    "管理会话 JWT/会话有效性校验 → /api/mod/{mod_id} 命名空间按接入上下文路由 → "
    "未绑定修茈账号的市场管理接口被拒（401）→ 无 CSRF 凭证的写操作被拒（403）。"
)


def _api(page, path, method="GET", body=None, headers=None):
    return page.evaluate(
        "async ([p, m, b, h]) => { try {"
        " const init = {credentials:'include', method: m};"
        " if (b !== null) { init.headers = Object.assign({'Content-Type':'application/json'}, h||{}); init.body = JSON.stringify(b); }"
        " else if (h) { init.headers = h; }"
        " const r = await fetch(p, init); const t = await r.text();"
        " let j=null; try { j = JSON.parse(t); } catch(e) {}"
        " return {status: r.status, body: j !== null ? j : t.slice(0,300)};"
        " } catch(e) { return {status:0, body:String(e)}; } }",
        [path, method, body, headers],
    )


def _shot(page, env, url, name, wait=3500):
    page.goto(env["base"] + url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(wait)
    page.screenshot(path=str(env["shot"] / name))
    return (page.inner_text("body") or "")


def case_session_validate(page, env):
    text = _shot(page, env, "/admin/settings", "A1-settings.png")
    r = _api(page, "/api/auth/session/validate")
    b = r.get("body") or {}
    d = b.get("data") or {}
    ok = (r["status"] == 200 and b.get("valid") is True
          and b.get("account_kind") == "admin" and d.get("username") == "admin")
    return {"status": r["status"], "valid": b.get("valid"), "account_kind": b.get("account_kind"),
            "username": d.get("username"), "tier": b.get("tier"),
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_mod_namespace(page, env):
    text = _shot(page, env, "/admin/server-functions", "A2-server-functions.png")
    r = _api(page, "/api/mod/xcagi-planner-bridge/tools/registry")
    b = r.get("body") or {}
    d = b.get("data") or {}
    ok = (r["status"] == 200 and b.get("success") is True
          and isinstance(d.get("tool_count"), int) and d.get("tool_count") > 0)
    return {"status": r["status"], "tool_count": d.get("tool_count"),
            "sample": (d.get("tool_names") or [])[:4],
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_market_admin_unauthorized(page, env):
    text = _shot(page, env, "/admin/", "A3-overview.png")
    r = _api(page, "/api/xcmax/admin/market/assignable-mods")
    b = r.get("body") or {}
    ok = r["status"] == 401 and "尚未绑定" in str(b.get("message") or "")
    return {"status": r["status"], "message": b.get("message"),
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_write_without_csrf(page, env):
    text = _shot(page, env, "/admin/tools", "A4-tools.png")
    r = _api(page, "/api/mod-store/update", "POST", {"mod_id": "sz-qsm-pro"})
    b = r.get("body") or {}
    ok = r["status"] == 403 and "CSRF" in str(b.get("message") or "")
    return {"status": r["status"], "message": b.get("message"),
            "ui_head": text.replace("\n", " ")[:120]}, ok


CASES = [
    {"id": "A1", "title": "管理会话 JWT/会话有效性校验",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/settings，随后 fetch GET /api/auth/session/validate。",
     "expected": "HTTP 200、valid=true，account_kind=admin 且用户名为 admin。",
     "run": case_session_validate},
    {"id": "A2", "title": "/api/mod/{mod_id} 命名空间按接入上下文路由",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/server-functions，随后 fetch GET /api/mod/xcagi-planner-bridge/tools/registry。",
     "expected": "HTTP 200、success=true，返回 tool_count>0（mod 命名空间被按 mod_id 解析）。",
     "run": case_mod_namespace},
    {"id": "A3", "title": "未绑定修茈账号的市场管理接口被拒绝（负例）",
     "input": "已建立的管理员会话，但未绑定修茈市场账号。",
     "actions": "浏览器打开管理端总览页，随后 fetch GET /api/xcmax/admin/market/assignable-mods。",
     "expected": "HTTP 401，提示尚未绑定修茈服务器账号。",
     "run": case_market_admin_unauthorized},
    {"id": "A4", "title": "无 CSRF 凭证的写操作被拒绝（负例）",
     "input": "已建立的管理员会话，写请求不带 X-CSRF-Token 头。",
     "actions": "浏览器打开 /admin/tools，随后 POST /api/mod-store/update（不带 CSRF 头）。",
     "expected": "HTTP 403，message 提示 CSRF token missing。",
     "run": case_write_without_csrf},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码，可点蓝色「登 录」。",
    "A1-settings.png": "「系统设置」页真实渲染：个人主页 管理员 / admin / admin@local，模型服务卡片。",
    "A2-server-functions.png": "「服务器功能模块」页真实渲染：服务器功能注册表 90 个模块（xcmax-admin、ai-ecosystem、model-payment 等）。",
    "A3-overview.png": "「服务器后台总览」页真实渲染：本地节点 127.0.0.1:42423、远程服务器「离线」、模块注册表 0 个模块。",
    "A4-tools.png": "「运维工具」页真实渲染：工具表区域显示「加载中…」，本轮尚未刷新出工具列表。",
    "__video__": "本轮真实浏览器会话录像（webm，40.76s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 系统设置 → 服务器功能模块 → 总览 → 运维工具，并 fetch 复核 session/validate、/api/mod/{mod_id} 命名空间、市场管理 401 与无 CSRF 写操作 403。",
}