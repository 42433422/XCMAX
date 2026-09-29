"""mods-store-sync（市场库同步与可见性）Web 管理端真机验收用例。

被测对象：以 web 模式运行的自托管管理端后端（http://127.0.0.1:42423）。
实现面：FHD/app/services/modstore_library_sync.py（从修茈 MODstore /v1/mod-sync 拉取源码
zip 并写入本机 mods/）与 FHD/app/services/catalog_visibility.py（目录可见性控制）。

真实性边界：所有断言都在真实浏览器里用页面上下文 fetch 复核；截图取自本轮真实渲染。
同步的两道门：写操作须带 CSRF 双提交；真正的拉取还须修茈 Developer PAT（含 mod:sync）。
"""

FEATURE = "mods-store-sync"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 发现页真实渲染 → "
    "本机 Mod 目录（可见性基线）真实读取 → 客户端 Mod 可见性开关状态真实读取 → "
    "平台能力清单中的受保护客户端 Mod 白名单真实读取 → 缺修茈 Developer PAT 的市场库同步被真实拒绝（400）。"
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


def _csrf(page):
    return page.evaluate(
        "() => { const m = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);"
        " return m ? decodeURIComponent(m[1]) : ''; }"
    )


def _shot(page, env, url, name, wait=3500):
    page.goto(env["base"] + url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(wait)
    page.screenshot(path=str(env["shot"] / name))
    return (page.inner_text("body") or "")


def case_catalog_visibility(page, env):
    text = _shot(page, env, "/admin/discover", "S1-discover.png")
    r = _api(page, "/api/mod-store/catalog")
    d = (r.get("body") or {}).get("data") or {}
    installed = d.get("installed") or []
    ok = r["status"] == 200 and isinstance(installed, list) and len(installed) > 0
    return {"status": r["status"], "installed_count": len(installed),
            "sample": [x.get("id") for x in installed[:5]],
            "ui_head": text.replace("\n", " ")[:130]}, ok


def case_client_mods_off(page, env):
    text = _shot(page, env, "/admin/", "S2-overview.png")
    r = _api(page, "/api/state/client-mods-off")
    d = (r.get("body") or {}).get("data") or {}
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and isinstance(d.get("client_mods_off"), bool))
    return {"status": r["status"], "client_mods_off": d.get("client_mods_off"),
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_protected_client_mods(page, env):
    text = _shot(page, env, "/admin/settings", "S3-settings.png")
    r = _api(page, "/api/platform-shell/capabilities")
    d = (r.get("body") or {}).get("data") or {}
    prot = d.get("protected_client_mod_ids") or []
    ok = r["status"] == 200 and isinstance(prot, list) and len(prot) > 0
    return {"status": r["status"], "edition": d.get("edition"),
            "protected_client_mod_ids": prot, "ui_head": text.replace("\n", " ")[:120]}, ok


def case_sync_without_pat(page, env):
    text = _shot(page, env, "/admin/tools", "S4-tools.png")
    csrf = _csrf(page)
    r = _api(page, "/api/mod-store/sync-modstore-library", "POST", {}, {"X-CSRF-Token": csrf})
    b = r.get("body") or {}
    msg = str(b.get("message") or "")
    ok = r["status"] == 400 and "PAT" in msg
    return {"status": r["status"], "message": msg, "csrf_present": bool(csrf),
            "ui_head": text.replace("\n", " ")[:120]}, ok


CASES = [
    {"id": "S1", "title": "本机 Mod 目录可见性基线真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/discover，随后 fetch GET /api/mod-store/catalog。",
     "expected": "HTTP 200，data.installed 非空。",
     "run": case_catalog_visibility},
    {"id": "S2", "title": "客户端 Mod 可见性开关状态真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开管理端总览页，随后 fetch GET /api/state/client-mods-off。",
     "expected": "HTTP 200、success=true，data.client_mods_off 为布尔值。",
     "run": case_client_mods_off},
    {"id": "S3", "title": "平台能力清单中的受保护客户端 Mod 白名单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/settings，随后 fetch GET /api/platform-shell/capabilities。",
     "expected": "HTTP 200，protected_client_mod_ids 非空列表。",
     "run": case_protected_client_mods},
    {"id": "S4", "title": "缺少修茈 Developer PAT 的市场库同步被拒绝（负例）",
     "input": "已建立的管理员会话，带合法 CSRF 双提交但无 PAT。",
     "actions": "浏览器打开 /admin/tools，读取 csrf_token Cookie 并 POST /api/mod-store/sync-modstore-library。",
     "expected": "HTTP 400，message 提示缺少 token（修茈 Developer PAT，需含 mod:sync）。",
     "run": case_sync_without_pat},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码，可点蓝色「登 录」。",
    "S1-discover.png": "「发现」页真实渲染：工作台（MODstore 网页版 · 完整 Mod 能力）、MOD 市场（浏览与安装行业 Mod）、工具箱。",
    "S2-overview.png": "「服务器后台总览」页真实渲染：本地节点 127.0.0.1:42423、远程服务器「离线」、模块注册表 0 个模块。",
    "S3-settings.png": "「系统设置」页真实渲染：个人主页 管理员 / admin@local，模型服务卡片显示尚未绑定修茈市场账号。",
    "S4-tools.png": "「运维工具」页真实渲染：工具表区域显示「加载中…」，本轮尚未刷新出工具列表。",
    "__video__": "本轮真实浏览器会话录像（webm，38.68s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 发现 → 总览 → 系统设置 → 运维工具，并 fetch 复核 /api/mod-store/catalog、/api/state/client-mods-off、/api/platform-shell/capabilities 与缺 PAT 同步（400）。",
}