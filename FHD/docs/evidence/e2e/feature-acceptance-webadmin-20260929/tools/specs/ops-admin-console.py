"""ops-admin-console（企业管理总后台）Web 管理端真机验收用例。

被测对象：以 web 模式运行的自托管管理端（XCAGI_DESKTOP_MODE=0），
入口 /admin/login，管理接口在 /api/admin/*；本项即「企业、账号、模块与运营数据的统一管理后台」。
"""

FEATURE = "ops-admin-console"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，CDP 真实鼠标键盘）在自托管 Web 管理端完成：管理员登录建立会话 → "
    "管理后台总览页真实渲染并显示产品版本 → 审计日志接口以本账号身份应答 → "
    "未登录会话访问管理接口被拒 → 模块注册表与平台能力清单真实读取。"
)


def _api(page, path, init_js="{}"):
    return page.evaluate(
        "async ([p, init]) => { try { const r = await fetch(p, Object.assign({credentials:'include'}, init));"
        " const t = await r.text(); let j=null; try { j = JSON.parse(t); } catch(e) {}"
        " return {status: r.status, body: j !== null ? j : t.slice(0,200)}; }"
        " catch(e) { return {status: 0, body: String(e)}; } }",
        [path, __import__("json").loads(init_js)],
    )


def case_login(page, env):
    me = _api(page, "/api/auth/me")
    user = ((me.get("body") or {}).get("data") or {}).get("user") or {}
    ok = me["status"] == 200 and (me.get("body") or {}).get("success") is True and user.get("role") == "admin"
    return {"me_status": me["status"], "me_success": (me.get("body") or {}).get("success"),
            "username": user.get("username"), "role": user.get("role"),
            "url": page.url}, ok


def case_console_page(page, env):
    page.goto(env["base"] + "/admin/", wait_until="domcontentloaded", timeout=45000)
    text, waited = "", 0
    for _ in range(12):                      # 总览页异步填充版本号，轮询到出现为止
        page.wait_for_timeout(2500)
        waited += 2500
        text = page.inner_text("body") or ""
        if "1.0.0.5" in text and "服务器后台总览" in text:
            break
    title = page.title() or ""
    has_overview = "服务器后台总览" in text
    has_version = "1.0.0.5" in text
    page.screenshot(path=str(env["shot"] / "W2-console-overview.png"))
    return {"final_url": page.url, "title": title, "has_overview_title": has_overview,
            "has_product_version": has_version, "waited_ms": waited,
            "text_head": text.replace("\n", " ")[:300]}, has_overview and has_version


def case_audit_logs(page, env):
    r = _api(page, "/api/admin/audit-logs")
    body = r.get("body") or {}
    data = body.get("data") or {}
    ok = r["status"] == 200 and body.get("success") is True and data.get("requested_by") == "admin"
    return {"status": r["status"], "success": body.get("success"),
            "requested_by": data.get("requested_by"), "total": data.get("total"),
            "path_configured": data.get("path_configured")}, ok


def case_unauthenticated_denied(page, env):
    browser = page.context.browser
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1500)
    r = pg2.evaluate(
        "async () => { try { const r = await fetch('/api/admin/audit-logs', {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){}"
        " return {status: r.status, body: j !== null ? j : t.slice(0,200)}; }"
        " catch(e) { return {status:0, body:String(e)}; } }"
    )
    pg2.screenshot(path=str(env["shot"] / "W4-unauthenticated-denied.png"))
    ctx2.close()
    ok = r["status"] in (401, 403)
    return {"status": r["status"], "body": r.get("body")}, ok


def case_module_registry(page, env):
    routes = _api(page, "/api/mods/routes")
    caps = _api(page, "/api/platform-shell/capabilities")
    rdata = (routes.get("body") or {}).get("data")
    cdata = (caps.get("body") or {}).get("data") or {}
    ok = (routes["status"] == 200 and isinstance(rdata, list) and len(rdata) > 0
          and caps["status"] == 200 and isinstance(cdata, dict) and bool(cdata.get("edition")))
    return {"mods_routes_status": routes["status"], "mods_route_count": len(rdata or []),
            "mods_sample": (rdata or [])[:3],
            "capabilities_status": caps["status"], "edition": cdata.get("edition"),
            "protected_client_mod_ids": cdata.get("protected_client_mod_ids")}, ok


# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码，可点「登 录」。",
    "W2-console-overview.png": "登录后进入「服务器后台总览」：左上 XCMAX 服务器后台，左侧运维导航（服务器后台总览/客户交付中心/创始人状态/自动化方针/服务器功能模块/业务审批/员工自治/用户管理/运维数据源/运维工具/系统设置），本地节点版本 1.0.0.5、数据库 ok、本地地址 127.0.0.1:42423，模块注册表 90 个模块。",
    "W4-unauthenticated-denied.png": "无会话的新浏览器上下文停留在管理员登录页，未出现任何管理数据。",
    "__video__": "本轮真实浏览器会话录像（webm，36.48s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 总览页渲染 → 审计接口应答 → 无会话上下文被拒 → 模块注册表读取。",
}

CASES = [
    {"id": "W1", "title": "管理员登录并建立管理会话（真实浏览器）",
     "input": "管理端账号与密码，在 /admin/login 真实输入。",
     "actions": "真实键盘输入账号/密码并点击「登 录」；随后在页面上下文复核 GET /api/auth/me。",
     "expected": "登录成功且 me 返回 role=admin 的管理员账号。",
     "run": case_login},
    {"id": "W2", "title": "管理后台总览页真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/，等待 SPA 完成重定向与渲染，读取页面标题与正文关键信息。",
     "expected": "页面渲染出「服务器后台总览」且显示本产品版本 1.0.0.5。",
     "run": case_console_page},
    {"id": "W3", "title": "审计日志接口以管理会话身份应答",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/admin/audit-logs。",
     "expected": "HTTP 200、success=true，且 requested_by 为本管理账号。",
     "run": case_audit_logs},
    {"id": "W4", "title": "未登录会话访问管理接口被拒绝",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie/无 token 的上下文中 fetch GET /api/admin/audit-logs。",
     "expected": "被拒绝（401 或 403），不返回管理数据。",
     "run": case_unauthenticated_denied},
    {"id": "W5", "title": "企业模块注册表与平台能力清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mods/routes 与 GET /api/platform-shell/capabilities。",
     "expected": "两者均 200；模块路由清单非空；平台能力清单含版本标识。",
     "run": case_module_registry},
]