"""ind-modstore-gateway（Mod 市场网关 · 服务端）Web 管理端真机验收用例。

被测对象：以 web 模式运行的自托管管理端后端（http://127.0.0.1:42423）所暴露的
「市场网关集成面」。实现面：成都修茈科技有限公司/MODstore_deploy（独立 MODstore 服务端网关）
及其在宿主侧的代理/回调对接：/api/xcmax/market-proxy/*、/api/market/status、
/api/xcmax/webhooks/modstore/payment、/api/mod-store/market-catalog。

真实性边界（重要）：本轮环境中独立 MODstore 服务端（默认 127.0.0.1:8765 / MODSTORE_PLATFORM_URL）
并未运行（本机仅 42423 在监听）。因此本 spec 只真实验证宿主侧「网关集成面」的可测契约：
市场目录消费、上游不可达时的显式诊断、未绑定市场账号时的代理鉴权、支付回调信封校验。
独立网关服务端自身的业务端点本轮无法真机验证，已在报告中如实标注。
"""

FEATURE = "ind-modstore-gateway"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 发现页真实渲染 → "
    "宿主消费市场网关目录（/api/mod-store/market-catalog）→ 上游网关不可达时 /api/market/status "
    "给出显式诊断（502，指名 XCAGI_MARKET_BASE_URL）→ 未绑定市场账号时网关代理被拒（401）→ "
    "支付回调空信封被拒（400 invalid_envelope）。注意：独立 MODstore 服务端本轮未运行，"
    "以上仅覆盖宿主侧网关集成面。"
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


def case_gateway_catalog(page, env):
    text = _shot(page, env, "/admin/discover", "G1-discover.png")
    r = _api(page, "/api/mod-store/market-catalog")
    d = (r.get("body") or {}).get("data") or {}
    items = d.get("items") or []
    ok = (r["status"] == 200 and isinstance(items, list) and len(items) > 0
          and all(x.get("id") and x.get("download_url") for x in items))
    return {"status": r["status"], "total": d.get("total"), "count": len(items),
            "sample": [(x.get("id"), x.get("download_url")) for x in items[:2]],
            "ui_head": text.replace("\n", " ")[:130]}, ok


def case_upstream_unreachable(page, env):
    text = _shot(page, env, "/admin/", "G2-overview.png")
    r = _api(page, "/api/market/status")
    b = r.get("body") or {}
    d = b.get("data") or {}
    err = b.get("error") or {}
    ok = (r["status"] == 502 and err.get("code") == "MARKET_AUTH_UNAVAILABLE"
          and bool(d.get("market_base_url")) and "无法连接" in str(b.get("message") or ""))
    return {"status": r["status"], "error_code": err.get("code"),
            "market_base_url": d.get("market_base_url"),
            "message": str(b.get("message") or "")[:120],
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_proxy_requires_binding(page, env):
    text = _shot(page, env, "/admin/server-functions", "G3-server-functions.png")
    r = _api(page, "/api/xcmax/market-proxy/health")
    b = r.get("body") or {}
    ok = r["status"] == 401 and "尚未绑定" in str(b.get("message") or "")
    return {"status": r["status"], "message": b.get("message"),
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_payment_webhook_envelope(page, env):
    text = _shot(page, env, "/admin/settings", "G4-settings.png")
    csrf = _csrf(page)
    r = _api(page, "/api/xcmax/webhooks/modstore/payment", "POST", {}, {"X-CSRF-Token": csrf})
    b = r.get("body") or {}
    ok = r["status"] == 400 and b.get("reason") == "invalid_envelope"
    return {"status": r["status"], "reason": b.get("reason"), "csrf_present": bool(csrf),
            "ui_head": text.replace("\n", " ")[:120]}, ok


CASES = [
    {"id": "G1", "title": "宿主消费市场网关目录",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/discover，随后 fetch GET /api/mod-store/market-catalog。",
     "expected": "HTTP 200，items 非空且每项含 id 与 download_url。",
     "run": case_gateway_catalog},
    {"id": "G2", "title": "上游网关不可达时给出显式诊断（观察项）",
     "input": "已建立的管理员会话；上游 MODstore/市场服务端未运行。",
     "actions": "浏览器打开管理端总览页，随后 fetch GET /api/market/status。",
     "expected": "HTTP 502，error.code=MARKET_AUTH_UNAVAILABLE，data.market_base_url 非空且文案说明无法连接。",
     "run": case_upstream_unreachable},
    {"id": "G3", "title": "未绑定市场账号时网关代理被拒绝（负例）",
     "input": "已建立的管理员会话，但未绑定修茈市场账号。",
     "actions": "浏览器打开 /admin/server-functions，随后 fetch GET /api/xcmax/market-proxy/health。",
     "expected": "HTTP 401，提示尚未绑定修茈服务器账号。",
     "run": case_proxy_requires_binding},
    {"id": "G4", "title": "支付回调空信封被拒绝（负例）",
     "input": "已建立的管理员会话，带合法 CSRF 双提交，回调体为空对象。",
     "actions": "浏览器打开 /admin/settings，读取 csrf_token 后 POST /api/xcmax/webhooks/modstore/payment。",
     "expected": "HTTP 400，reason=invalid_envelope。",
     "run": case_payment_webhook_envelope},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码，可点蓝色「登 录」。",
    "G1-discover.png": "「发现」页真实渲染：工作台（MODstore 网页版 · 完整 Mod 能力）、MOD 市场（浏览与安装行业 Mod）、工具箱。",
    "G2-overview.png": "「服务器后台总览」页真实渲染：本地节点 127.0.0.1:42423、远程服务器「离线」、软件版本「检测中」、模块注册表 0 个模块。",
    "G3-server-functions.png": "「服务器功能模块」页真实渲染：服务器功能注册表 90 个模块（xcmax-admin、ai-ecosystem、model-payment 等）。",
    "G4-settings.png": "「系统设置」页真实渲染：个人主页 管理员 / admin@local，模型服务卡片显示尚未绑定修茈市场账号。",
    "__video__": "本轮真实浏览器会话录像（webm，41.44s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 发现 → 总览 → 服务器功能模块 → 系统设置，并 fetch 复核 /api/mod-store/market-catalog、/api/market/status(502)、market-proxy(401)、支付回调(400)。注意：独立 MODstore 服务端未运行。",
}