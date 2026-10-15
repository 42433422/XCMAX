"""mods-toolchain（Mod 制作工具链）Web 管理端真机验收用例。

被测对象：以 web 模式运行的自托管管理端后端（http://127.0.0.1:42423）。
实现面：FHD/app/fastapi_routes/mod_runtime_frontend.py —— 经过签名与安装验证的 Mod
的前端运行时资源（/api/mods/runtime/{mod_id} 与 assets），以及 /api/mods 下的 Mod
注册/发现/加载工具链接口。

真实性边界：所有断言都在真实浏览器里用页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "mods-toolchain"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 服务器功能模块页真实渲染 → "
    "Mod 前端路由注册表（/api/mods/routes）按工具链发现结果应答 → 未完成签名/安装验证的 Mod "
    "运行时接口被真实拒绝（409）→ 单个 Mod 元数据与加载状态真实读取。"
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


def case_routes(page, env):
    text = _shot(page, env, "/admin/server-functions", "T1-server-functions.png")
    r = _api(page, "/api/mods/routes")
    d = (r.get("body") or {}).get("data")
    ok = (r["status"] == 200 and isinstance(d, list) and len(d) > 0
          and all(x.get("mod_id") and x.get("routes_path") for x in d))
    return {"status": r["status"], "count": len(d or []), "sample": (d or [])[:3],
            "ui_head": text.replace("\n", " ")[:150]}, ok


def case_runtime_guard(page, env):
    text = _shot(page, env, "/admin/tools", "T2-tools.png")
    r = _api(page, "/api/mods/runtime/sz-qsm-pro")
    msg = str((r.get("body") or {}).get("message") or "")
    ok = r["status"] == 409 and "签名" in msg and "安装验证" in msg
    return {"status": r["status"], "message": msg,
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_mod_detail(page, env):
    text = _shot(page, env, "/admin/", "T3-overview.png")
    r = _api(page, "/api/mods/xcagi-planner-bridge")
    d = (r.get("body") or {}).get("data") or {}
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and d.get("id") == "xcagi-planner-bridge" and bool(d.get("version")))
    return {"status": r["status"], "mod_id": d.get("id"), "version": d.get("version"),
            "author": d.get("author"), "ui_head": text.replace("\n", " ")[:120]}, ok


def case_loading_status(page, env):
    text = _shot(page, env, "/admin/settings", "T4-settings.png")
    r = _api(page, "/api/mods/loading-status")
    d = (r.get("body") or {}).get("data") or {}
    ids = d.get("discovered_mod_ids") or []
    ok = r["status"] == 200 and isinstance(ids, list) and "sz-qsm-pro" in ids
    return {"status": r["status"], "discovered_count": len(ids), "sample": ids[:4],
            "mods_root": d.get("mods_root"), "ui_head": text.replace("\n", " ")[:120]}, ok


CASES = [
    {"id": "T1", "title": "Mod 前端路由注册表按工具链发现结果应答",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/server-functions，随后在页面上下文 fetch GET /api/mods/routes。",
     "expected": "HTTP 200 且返回非空列表，每项含 mod_id 与 routes_path。",
     "run": case_routes},
    {"id": "T2", "title": "未完成签名/安装验证的 Mod 运行时接口被拒绝",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/tools，随后 fetch GET /api/mods/runtime/sz-qsm-pro。",
     "expected": "HTTP 409，提示扩展包尚未完成签名与安装验证。",
     "run": case_runtime_guard},
    {"id": "T3", "title": "单个 Mod 元数据（工具链产物）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开管理端总览页，随后 fetch GET /api/mods/xcagi-planner-bridge。",
     "expected": "HTTP 200、success=true，返回该 Mod 的 id 与 version。",
     "run": case_mod_detail},
    {"id": "T4", "title": "Mod 加载状态（脚手架发现清单）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/settings，随后 fetch GET /api/mods/loading-status。",
     "expected": "HTTP 200，discovered_mod_ids 非空且包含本机已发现的 sz-qsm-pro。",
     "run": case_loading_status},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码，可点蓝色「登 录」。",
    "T1-server-functions.png": "「服务器功能模块」页真实渲染：服务器功能注册表 90 个模块，含 xcmax-admin（/xcmax-admin）、chat、ai-ecosystem、model-payment 等系统内置模块与路由。",
    "T2-tools.png": "「运维工具」页真实渲染：工具表区域显示「加载中…」，本轮尚未刷新出工具列表。",
    "T3-overview.png": "「服务器后台总览」页真实渲染：本地节点 127.0.0.1:42423、远程服务器显示「离线」、软件版本「检测中」、模块注册表显示 0 个模块（异步未回填）。",
    "T4-settings.png": "「系统设置」页真实渲染：个人主页 管理员 / admin / admin@local，模型服务卡片显示尚未绑定修茈市场账号。",
    "__video__": "本轮真实浏览器会话录像（webm，44.08s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 服务器功能模块 → 运维工具 → 总览 → 系统设置，并逐项 fetch 复核 /api/mods/*。",
}