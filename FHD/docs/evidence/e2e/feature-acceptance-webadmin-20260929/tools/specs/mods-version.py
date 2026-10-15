"""mods-version（版本管理与蓝绿）Web 管理端真机验收用例。

被测对象：以 web 模式运行的自托管管理端后端（http://127.0.0.1:42423）。
实现面：FHD/app/infrastructure/mods/mod_manager.py —— Mod 扫描/加载/版本元数据管理；
配套 /api/mods、/api/mod-store/updates、/api/mod-store/dependencies 接口。

真实性边界：所有断言都在真实浏览器里用页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "mods-version"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 管理端总览与服务器功能模块页真实渲染 → "
    "全量 Mod 版本清单（/api/mods?all=1）真实读取 → 更新检查（/api/mod-store/updates）返回更新源状态 → "
    "单 Mod 版本与依赖可安装性真实读取 → 查询不存在的 Mod 版本被真实拒绝（404）。"
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


def case_all_versions(page, env):
    text = _shot(page, env, "/admin/", "V1-overview.png")
    r = _api(page, "/api/mods?all=1")
    d = (r.get("body") or {}).get("data")
    ok = (r["status"] == 200 and isinstance(d, list) and len(d) > 0
          and all(x.get("id") and x.get("version") for x in d))
    return {"status": r["status"], "count": len(d or []),
            "sample": [(x.get("id"), x.get("version")) for x in (d or [])[:4]],
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_updates_check(page, env):
    text = _shot(page, env, "/admin/server-functions", "V2-server-functions.png")
    r = _api(page, "/api/mod-store/updates")
    d = (r.get("body") or {}).get("data") or {}
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and isinstance(d.get("updates_available"), list)
          and isinstance(d.get("count"), int)
          and isinstance(d.get("source_errors"), dict))
    return {"status": r["status"], "count": d.get("count"),
            "complete": d.get("complete"), "source_errors": d.get("source_errors"),
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_mod_version_and_deps(page, env):
    text = _shot(page, env, "/admin/settings", "V3-settings.png")
    r1 = _api(page, "/api/mods/xcagi-planner-bridge")
    r2 = _api(page, "/api/mod-store/dependencies?mod_id=xcagi-planner-bridge")
    d1 = (r1.get("body") or {}).get("data") or {}
    d2 = (r2.get("body") or {}).get("data") or {}
    ok = (r1["status"] == 200 and bool(d1.get("version"))
          and r2["status"] == 200 and isinstance(d2.get("can_install"), bool))
    return {"detail_status": r1["status"], "version": d1.get("version"),
            "deps_status": r2["status"], "can_install": d2.get("can_install"),
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_unknown_mod(page, env):
    text = _shot(page, env, "/admin/tools", "V4-tools.png")
    r = _api(page, "/api/mods/nonexistent-xyz")
    b = r.get("body") or {}
    ok = r["status"] == 404 and str(b.get("error") or "") == "Mod not found"
    return {"status": r["status"], "body": b,
            "ui_head": text.replace("\n", " ")[:120]}, ok


CASES = [
    {"id": "V1", "title": "全量 Mod 版本清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开管理端总览页，随后 fetch GET /api/mods?all=1。",
     "expected": "HTTP 200，返回非空列表且每项含 id 与 version。",
     "run": case_all_versions},
    {"id": "V2", "title": "更新检查（版本对比源）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/server-functions，随后 fetch GET /api/mod-store/updates。",
     "expected": "HTTP 200、success=true，含 updates_available 列表、count 与 source_errors。",
     "run": case_updates_check},
    {"id": "V3", "title": "单 Mod 版本与依赖可安装性真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/settings，随后 fetch /api/mods/xcagi-planner-bridge 与 /api/mod-store/dependencies。",
     "expected": "两者均 200；前一接口返回 version；后一接口返回布尔 can_install。",
     "run": case_mod_version_and_deps},
    {"id": "V4", "title": "查询不存在的 Mod 版本被真实拒绝（负例）",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/tools，随后 fetch GET /api/mods/nonexistent-xyz。",
     "expected": "HTTP 404，error=Mod not found。",
     "run": case_unknown_mod},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码，可点蓝色「登 录」。",
    "V1-overview.png": "「服务器后台总览」页真实渲染：本地节点 127.0.0.1:42423、远程服务器「离线」、模块注册表 0 个模块（异步未回填）。",
    "V2-server-functions.png": "「服务器功能模块」页真实渲染，本轮注册表显示 0 个模块并提示「暂无模块数据，点击刷新或检查 /api/xcmax/admin/modules」。",
    "V3-settings.png": "「系统设置」页真实渲染：个人主页 管理员 / admin / admin@local，模型服务卡片显示尚未绑定修茈市场账号。",
    "V4-tools.png": "「运维工具」页真实渲染：工具表渲染出 AI Planner 可调用工具网格（excel_analysis、template_preview、create_role 等）。",
    "__video__": "本轮真实浏览器会话录像（webm，43.96s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 总览 → 服务器功能模块 → 系统设置 → 运维工具，并 fetch 复核 /api/mods?all=1、/api/mod-store/updates、/api/mod-store/dependencies 等。",
}