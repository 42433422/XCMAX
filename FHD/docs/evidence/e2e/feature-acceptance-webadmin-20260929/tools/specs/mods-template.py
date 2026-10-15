"""mods-template（行业 Mod 模板）Web 管理端真机验收用例。

被测对象：以 web 模式运行的自托管管理端后端（http://127.0.0.1:42423）。
实现面：FHD/app/mod_sdk/industry_seed.py —— 行业 Mod 种子与模板（open_industry_seed_mod_ids、
bundled_industry_seeds_dir、install_industry_seed_with_fallback 等）；配套 /api/mod-store
的市场目录、本机目录、搜索与行业种子安装接口。

真实性边界：所有断言都在真实浏览器里用页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "mods-template"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 发现/扩展市场页真实渲染 → "
    "市场模板目录真实读取 → 本机已安装行业模板（*-industry）清单真实读取 → 行业模板搜索结果真实读取 → "
    "未经 CSRF 校验的行业种子安装写操作被真实拒绝（403）。"
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


def case_market_templates(page, env):
    text = _shot(page, env, "/admin/discover", "M1-discover.png")
    r = _api(page, "/api/mod-store/market-catalog")
    d = (r.get("body") or {}).get("data") or {}
    items = d.get("items") or []
    ok = (r["status"] == 200 and isinstance(items, list) and len(items) > 0
          and all(x.get("id") and x.get("version") for x in items))
    return {"status": r["status"], "total": d.get("total"), "count": len(items),
            "sample": [(x.get("id"), x.get("version")) for x in items[:4]],
            "ui_head": text.replace("\n", " ")[:130]}, ok


def case_installed_industry(page, env):
    text = _shot(page, env, "/admin/server-functions", "M2-server-functions.png")
    r = _api(page, "/api/mod-store/catalog")
    d = (r.get("body") or {}).get("data") or {}
    installed = d.get("installed") or []
    industry = [x for x in installed if "industry" in str(x.get("id") or "")]
    ok = r["status"] == 200 and len(industry) > 0
    return {"status": r["status"], "installed_count": len(installed),
            "industry_ids": [x.get("id") for x in industry][:6],
            "ui_head": text.replace("\n", " ")[:130]}, ok


def case_search_template(page, env):
    text = _shot(page, env, "/admin/tools", "M3-tools.png")
    r = _api(page, "/api/mod-store/search?q=industry")
    d = (r.get("body") or {}).get("data")
    ok = r["status"] == 200 and isinstance(d, list) and len(d) > 0
    return {"status": r["status"], "count": len(d or []),
            "sample": [(x.get("id"), x.get("version")) for x in (d or [])[:4]],
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_seed_install_without_csrf(page, env):
    text = _shot(page, env, "/admin/settings", "M4-settings.png")
    r = _api(page, "/api/mod-store/install-industry-seed", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 403 and "CSRF" in str(b.get("message") or "")
    return {"status": r["status"], "message": b.get("message"),
            "ui_head": text.replace("\n", " ")[:120]}, ok


CASES = [
    {"id": "M1", "title": "市场行业模板目录真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/discover，随后 fetch GET /api/mod-store/market-catalog。",
     "expected": "HTTP 200，items 非空且每项含 id 与 version。",
     "run": case_market_templates},
    {"id": "M2", "title": "本机已安装行业模板（*-industry）清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/server-functions，随后 fetch GET /api/mod-store/catalog。",
     "expected": "HTTP 200，data.installed 中存在 id 含 industry 的行业模板。",
     "run": case_installed_industry},
    {"id": "M3", "title": "行业模板搜索结果真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/tools，随后 fetch GET /api/mod-store/search?q=industry。",
     "expected": "HTTP 200，返回非空结果列表。",
     "run": case_search_template},
    {"id": "M4", "title": "未经 CSRF 校验的行业种子安装被拒绝（负例）",
     "input": "已建立的管理员会话（无 X-CSRF-Token 头）。",
     "actions": "浏览器打开 /admin/settings，随后 POST /api/mod-store/install-industry-seed（不带 CSRF 头）。",
     "expected": "HTTP 403，message 提示 CSRF token missing。",
     "run": case_seed_install_without_csrf},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码，可点蓝色「登 录」。",
    "M1-discover.png": "「发现」页真实渲染：工作台（MODstore 网页版 · 完整 Mod 能力）、MOD 市场（浏览与安装行业 Mod）、工具箱。",
    "M2-server-functions.png": "「服务器功能模块」页真实渲染：服务器功能注册表 90 个模块（xcmax-admin、ai-ecosystem、model-payment 等）。",
    "M3-tools.png": "「运维工具」页真实渲染：工具表渲染出 AI Planner 可调用工具网格（excel_analysis、template_preview、create_role 等）。",
    "M4-settings.png": "「系统设置」页真实渲染：个人主页 管理员 / admin@local，模型服务卡片。",
    "__video__": "本轮真实浏览器会话录像（webm，44.64s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 发现 → 服务器功能模块 → 运维工具 → 系统设置，并 fetch 复核 /api/mod-store/market-catalog、catalog、search 与行业种子安装（403）。",
}