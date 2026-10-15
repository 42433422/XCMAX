"""mods-store（Mod 市场与一键装包）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/mod_store_route_handlers_part01.py、mod_store_ai_delivery_routes.py。
真实接口面：/api/mod-store/catalog（本机已装/可见目录）、/api/mod-store/market-catalog（市场目录）、
/api/mod-store/mod/{mod_id}/details（Mod 详情）、/api/mod-store/search。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "mods-store"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取本机 Mod 目录（已装清单）→ 读取市场目录与 Mod 详情 → "
    "以真实 400 证明缺 mod_id 的卸载被拒 → "
    "以真实 502 记录远端私有更新源不可用时的 fail-closed（边界/负例）。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p,m,b]) => {
            try {
                const init = {credentials:'include', method:m};
                if (b !== null && b !== undefined) {
                    init.headers = {'Content-Type':'application/json'};
                    init.body = JSON.stringify(b);
                }
                if (m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
                    if (cm) init.headers = Object.assign(init.headers||{}, {'X-CSRF-Token': decodeURIComponent(cm[1])});
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch(e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0,300)};
            } catch(e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body],
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


def case_catalog(page, env):
    r = _api(page, "/api/mod-store/catalog")
    d = (r.get("body") or {}).get("data") or {}
    installed = d.get("installed") or []
    ok = r["status"] == 200 and isinstance(installed, list) and len(installed) > 0
    body = {"status": r["status"], "installed_count": len(installed),
            "sample": [{"id": x.get("id"), "version": x.get("version"), "is_installed": x.get("is_installed")}
                       for x in installed[:5]]}
    _card(page, env, "S1-store-catalog.png", "S1", "本机 Mod 目录（已装/可见）真实读取",
          "GET /api/mod-store/catalog", r["status"], body)
    return body, ok


def case_market_catalog(page, env):
    r = _api(page, "/api/mod-store/market-catalog")
    d = (r.get("body") or {}).get("data") or {}
    items = d.get("items") or []
    ok = r["status"] == 200 and len(items) > 0
    body = {"status": r["status"], "item_count": len(items),
            "sample": [{"id": x.get("id"), "version": x.get("version"),
                        "download_url": x.get("download_url")} for x in items[:4]]}
    _card(page, env, "S2-store-market.png", "S2", "市场目录真实读取（可安装包与下载地址）",
          "GET /api/mod-store/market-catalog", r["status"], body)
    return body, ok


def case_mod_details(page, env):
    r = _api(page, "/api/mod-store/mod/accessories-packaging-industry/details")
    d = (r.get("body") or {}).get("data") or {}
    ok = r["status"] == 200 and d.get("id") == "accessories-packaging-industry" and bool(d.get("name"))
    return {"status": r["status"], "id": d.get("id"), "name": d.get("name"),
            "version": d.get("version"), "source": d.get("source")}, ok


def case_uninstall_missing_mod_denied(page, env):
    r = _api(page, "/api/mod-store/uninstall", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "mod_id" in str(b.get("message"))
    body = {"status": r["status"], "error_code": b.get("error_code"), "message": b.get("message")}
    _card(page, env, "S3-store-boundary.png", "S3", "缺 mod_id 的卸载被拒（边界/负例）",
          "POST /api/mod-store/uninstall {}", r["status"], body)
    return body, ok


def case_private_delivery_failclosed(page, env):
    r = _api(page, "/api/mod-store/private-delivery")
    b = r.get("body") or {}
    ok = r["status"] == 502 and "Catalog" in str(b.get("message"))
    body = {"status": r["status"], "error_code": b.get("error_code"), "message": str(b.get("message"))[:160],
            "note": "远端私有更新源凭证不可用时如实 502，不伪装为空目录。"}
    _card(page, env, "S4-store-remote-failclosed.png", "S4", "远端私有源不可用时 fail-closed（边界/负例）",
          "GET /api/mod-store/private-delivery", r["status"], body)
    return body, ok


CASES = [
    {"id": "S1", "title": "本机 Mod 目录真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mod-store/catalog。",
     "expected": "HTTP 200，data.installed 非空。",
     "run": case_catalog},
    {"id": "S2", "title": "市场目录真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/mod-store/market-catalog。",
     "expected": "HTTP 200，items 非空且含下载地址。",
     "run": case_market_catalog},
    {"id": "S3", "title": "Mod 详情真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/mod-store/mod/accessories-packaging-industry/details。",
     "expected": "HTTP 200，返回该 mod 的 id/name/version。",
     "run": case_mod_details},
    {"id": "S4", "title": "缺 mod_id 的卸载被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/mod-store/uninstall（空 body）。",
     "expected": "HTTP 400，message 为缺少 mod_id。",
     "run": case_uninstall_missing_mod_denied},
    {"id": "S5", "title": "远端私有源不可用时 fail-closed（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/mod-store/private-delivery。",
     "expected": "HTTP 502，message 指明远端 Catalog 返回 401 —— 不伪装成功。",
     "run": case_private_delivery_failclosed},
]

VISIBLE_RESULTS = {
    "S1-store-catalog.png": "卡片「S1 · 本机 Mod 目录（已装/可见）真实读取」：GET /api/mod-store/catalog，200，{\"status\":200,\"installed_count\":6,\"sample\":[{\"id\":\"accessories-packaging-industry\",\"version\":\"1.0.0\",\"is_installed\":true},{\"id\":\"attendance-industry\",\"version\":\"1.0.1\",\"is_installed\":true},{\"id\":\"coating-industry\",\"version\":\"1.0.0\",\"is_installed\":true},{\"id\":\"lan-gate-ai-employee\",\"version\":\"1.0.0\",\"is_installed\":true},{\"id\":\"sz-qsm-pro\",\"version\":\"1.0.0\",\"is_installed\":true}]}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，28.16s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 本机 Mod 目录 → 市场目录 → Mod 详情 → 缺 mod_id 400 → 远端私有源 502。"
}