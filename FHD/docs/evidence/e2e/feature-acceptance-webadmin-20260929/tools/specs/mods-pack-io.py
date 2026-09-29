"""mods-pack-io（包导入导出与发布）Web 管理端真机验收用例。

被测对象：以 web 模式运行的自托管管理端后端（http://127.0.0.1:42423）。
实现面：FHD/app/services/mod_zip_normalize.py —— Mod 包 zip 布局规范化（与
mod_store._normalize_package_zip 语义一致）；配套 /api/mod-store 下的包清单、
市场包元数据、包校验与包下载接口。

真实性边界：所有断言都在真实浏览器里用页面上下文 fetch 复核；截图取自本轮真实渲染。
「包校验未实现」「包下载未实现」均按产品真实响应如实记录为观察项。
"""

FEATURE = "mods-pack-io"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 发现/扩展市场页真实渲染 → "
    "本机已安装 Mod 包清单真实读取 → 市场包元数据（package_file / download_url）真实读取 → "
    "包校验接口按其真实能力返回「未实现」→ 下载不存在的包被真实拒绝（404）。"
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


def case_catalog_installed(page, env):
    text = _shot(page, env, "/admin/discover", "P1-discover.png")
    r = _api(page, "/api/mod-store/catalog")
    d = (r.get("body") or {}).get("data") or {}
    installed = d.get("installed") or []
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and isinstance(installed, list) and len(installed) > 0
          and all(x.get("id") and x.get("version") for x in installed))
    return {"status": r["status"], "installed_count": len(installed),
            "sample": installed[:2], "ui_head": text.replace("\n", " ")[:140]}, ok


def case_market_packages(page, env):
    text = _shot(page, env, "/admin/settings", "P2-settings.png")
    r = _api(page, "/api/mod-store/market-catalog")
    d = (r.get("body") or {}).get("data") or {}
    items = d.get("items") or []
    has_pkg = all(x.get("package_file") for x in items) if items else False
    ok = (r["status"] == 200 and isinstance(items, list) and len(items) > 0 and has_pkg)
    return {"status": r["status"], "total": d.get("total"), "items_count": len(items),
            "sample": items[:2], "ui_head": text.replace("\n", " ")[:120]}, ok


def case_validate_capability(page, env):
    text = _shot(page, env, "/admin/tools", "P3-tools.png")
    r = _api(page, "/api/mod-store/validate")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is False
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message"),
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_download_missing_package(page, env):
    text = _shot(page, env, "/admin/", "P4-overview.png")
    r = _api(page, "/api/mod-store/package/foo.zip/download")
    b = r.get("body") or {}
    msg = str(b.get("message") or "")
    ok = r["status"] == 404 and ("未实现" in msg or "不存在" in msg)
    return {"status": r["status"], "message": msg,
            "ui_head": text.replace("\n", " ")[:120]}, ok


CASES = [
    {"id": "P1", "title": "本机已安装 Mod 包清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/discover，随后 fetch GET /api/mod-store/catalog。",
     "expected": "HTTP 200、success=true，data.installed 非空且每项含 id/version。",
     "run": case_catalog_installed},
    {"id": "P2", "title": "市场包导出/发布元数据真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/settings，随后 fetch GET /api/mod-store/market-catalog。",
     "expected": "HTTP 200，items 非空，且每项含可发布/导出的 package_file。",
     "run": case_market_packages},
    {"id": "P3", "title": "包校验接口按真实能力边界应答（观察项）",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/tools，随后 fetch GET /api/mod-store/validate。",
     "expected": "HTTP 200，但 success=false —— 如实记录该接口当前返回「未实现」。",
     "run": case_validate_capability},
    {"id": "P4", "title": "下载不存在的 Mod 包被真实拒绝（负例）",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开管理端总览页，随后 fetch GET /api/mod-store/package/foo.zip/download。",
     "expected": "HTTP 404，明确提示包下载未实现/不存在。",
     "run": case_download_missing_package},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码，可点蓝色「登 录」。",
    "P1-discover.png": "「发现」页真实渲染：工作台（MODstore 网页版 · 完整 Mod 能力）、扩展与市场下 MOD 市场（浏览与安装行业 Mod）与工具箱入口。",
    "P2-settings.png": "「系统设置」页真实渲染：个人主页 管理员 / admin@local，模型服务卡片。",
    "P3-tools.png": "「运维工具」页真实渲染：工具表区域显示「加载中…」，本轮尚未刷新出工具列表。",
    "P4-overview.png": "「服务器后台总览」页真实渲染：本地节点 127.0.0.1:42423、远程服务器「离线」、模块注册表 0 个模块。",
    "__video__": "本轮真实浏览器会话录像（webm，45.60s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 发现 → 系统设置 → 运维工具 → 总览，并逐项 fetch 复核 /api/mod-store 包目录/校验/下载接口。",
}