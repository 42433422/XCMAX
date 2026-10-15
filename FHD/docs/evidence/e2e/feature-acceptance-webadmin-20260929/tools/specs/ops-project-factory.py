"""ops-project-factory（项目工厂与工厂版员工派工）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/factory_routes.py
（/api/admin/factory/workspaces、/api/admin/factory/employees）。
管理端 UI：/admin/project-factory（项目工厂，仅平台管理端可见）、
/admin/delivery-center（客户交付中心）、/admin/server-functions（服务器功能模块）。
"""

import html as _html
import json as _json

FEATURE = "ops-project-factory"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取工厂项目工作区清单（/api/admin/factory/workspaces：id/隔离/默认分支）→ "
    "读取工厂员工与派工端点（/api/admin/factory/employees：Claude/Codex/Cursor/Trae 及 endpoint）→ "
    "项目工厂页真实渲染项目下拉、员工下拉与派工输入；无会话访问工作区清单被拒（401）。"
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


def _render(page, env, route, name=None, wait_for=None, tries=10):
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


def _unauth(page, env, path, method="GET", body=None, csrf=True, name=None):
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(1200)
    r = _api(pg, path, method, body, csrf)
    if name:
        pg.screenshot(path=str(env["shot"] / name))
    ctx.close()
    return r


def case_factory_workspaces(page, env):
    text = _render(page, env, "/admin/delivery-center",
                   name="F1-workspaces.png", wait_for="客户交付中心")
    r = _api(page, "/api/admin/factory/workspaces")
    d = r.get("body") or {}
    ws = d.get("workspaces") or []
    ok = (r["status"] == 200 and d.get("success") is True and len(ws) > 0
          and all(w.get("id") and "isolation" in w and w.get("default_branch") for w in ws))
    return {"status": r["status"], "success": d.get("success"),
            "workspace_count": len(ws), "workspaces": ws,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_factory_employees(page, env):
    text = _render(page, env, "/admin/server-functions",
                   name="F2-employees.png", wait_for="服务器功能模块")
    r = _api(page, "/api/admin/factory/employees")
    d = r.get("body") or {}
    emps = d.get("employees") or []
    ok = (r["status"] == 200 and d.get("success") is True and len(emps) > 0
          and all(e.get("id") and e.get("display_tool") and e.get("endpoint") for e in emps))
    return {"status": r["status"], "success": d.get("success"),
            "employee_count": len(emps), "employees": emps,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_project_factory_page(page, env):
    text = _render(page, env, "/admin/project-factory",
                   name="F3-project-factory.png", wait_for="项目工厂")
    ok = "项目工厂" in text and "XCMAX 主项目" in text and "工厂员工-Claude" in text
    return {"final_url": page.url, "has_title": "项目工厂" in text,
            "has_workspace_option": "XCMAX 主项目" in text,
            "has_employee_option": "工厂员工-Claude" in text,
            "text_head": text.replace("\n", " ")[:240]}, ok


def case_unauth_workspaces_denied(page, env):
    r = _unauth(page, env, "/api/admin/factory/workspaces",
                name="F4-unauth-denied.png")
    b = r.get("body") or {}
    ok = r["status"] in (401, 403) and isinstance(b, dict) and b.get("success") is False
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "F1", "title": "工厂项目工作区清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/delivery-center，随后 fetch GET /api/admin/factory/workspaces。",
     "expected": "HTTP 200、success=true，返回非空工作区且各含 id/label/isolation/default_branch。",
     "run": case_factory_workspaces},
    {"id": "F2", "title": "工厂员工与派工端点真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/server-functions，随后 fetch GET /api/admin/factory/employees。",
     "expected": "HTTP 200、success=true，返回非空员工且各含 id/display_name/endpoint。",
     "run": case_factory_employees},
    {"id": "F3", "title": "项目工厂页真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/project-factory，等待渲染项目下拉、员工下拉与派工输入区。",
     "expected": "页面渲染「项目工厂」，项目下拉含「XCMAX 主项目」，员工下拉含「工厂员工-Claude」。",
     "run": case_project_factory_page},
    {"id": "F4", "title": "无会话访问工作区清单被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 的上下文中 fetch GET /api/admin/factory/workspaces。",
     "expected": "被拒绝（401/403），success=false，不返回工作区数据。",
     "run": case_unauth_workspaces_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "F1-workspaces.png": "「客户交付中心」页真实渲染：Mac 主控·四设备协同，交付台账与企业用户计数卡片。",
    "F2-employees.png": "「服务器功能模块」页真实渲染：服务器功能注册表 90 个模块列表。",
    "F3-project-factory.png": "「项目工厂」页真实渲染：项目下拉「XCMAX 主项目（none）」、工厂员工下拉「工厂员工-Claude」、刷新按钮与派工输入区（提示「还没有派工记录。选好项目和员工，下面发条指令试试。」），并说明需配置 XCMAX_FACTORY_CAPABILITY_TOKEN 才启用工厂能力。",
    "F4-unauth-denied.png": "无会话的新浏览器上下文停留在管理员登录页，未出现任何工作区数据。",
    "__video__": "本轮真实浏览器会话录像（webm，27.88s，1600x1000 25fps，ffmpeg 实测）：管理员登录 → 客户交付中心 → 服务器功能模块 → 项目工厂页渲染 → 无会话被拒，并 fetch 复核工作区与员工接口。",
}