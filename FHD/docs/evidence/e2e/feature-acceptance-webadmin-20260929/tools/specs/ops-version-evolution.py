"""ops-version-evolution（版本列车与自进化门禁）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/release_train_routes.py（/api/xcmax/release-train）、
FHD/app/fastapi_routes/xcmax_ops.py（/api/xcmax/ops/founder-autonomy，evolution 维度）、
FHD/app/fastapi_routes/ops_autonomy_admin_routes.py（/api/xcmax/admin/autonomy/deploy-events）。
管理端 UI：/admin/xcmax-admin（服务器后台总览，软件版本与更新包）。
"""

import html as _html
import json as _json

FEATURE = "ops-version-evolution"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → "
    "「服务器后台总览」页真实渲染「软件版本与更新包」（管理端版本 / update 站版本 / 企业端）→ "
    "GET /api/xcmax/release-train 返回版本列车（epoch 1.0.0.0、product_version/current=1.0.0.5）→ "
    "GET /api/xcmax/ops/founder-autonomy 返回「进化状态」7 项门禁"
    "（detect/knowledge/implement/metrics/council/package/publish）→ "
    "GET /api/xcmax/admin/autonomy/deploy-events 返回自驱部署事件与 status → "
    "无会话访问部署事件接口被拒（401）。"
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


def _card(page, env, name, cid, title, req, status, body):
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


def case_version_panel(page, env):
    text = _render(page, env, "/admin/xcmax-admin",
                   name="EV1-version-panel.png", wait_for="服务器后台总览")
    ok = ("服务器后台总览" in text and "软件版本与更新包" in text
          and "管理端版本" in text and "update 站版本" in text)
    return {"final_url": page.url, "title": page.title(),
            "has_overview": "服务器后台总览" in text,
            "has_version_panel": "软件版本与更新包" in text,
            "has_admin_version": "管理端版本" in text,
            "has_update_site_version": "update 站版本" in text,
            "text_head": text.replace("\n", " ")[:240]}, ok


def case_release_train(page, env):
    r = _api(page, "/api/xcmax/release-train")
    d = r.get("body") or {}
    data = d.get("data") or {}
    ok = (r["status"] == 200 and d.get("success") is True
          and data.get("epoch") == "1.0.0.0"
          and data.get("current") == data.get("product_version") == "1.0.0.5"
          and isinstance(data.get("day_index"), int))
    _card(page, env, "EV2-release-train.png", "EV2", "版本列车",
          "/api/xcmax/release-train", r["status"], data)
    return {"status": r["status"], "success": d.get("success"), "data": data}, ok


def case_evolution_gates(page, env):
    r = _api(page, "/api/xcmax/ops/founder-autonomy")
    d = r.get("body") or {}
    evo = ((d.get("dimensions") or {}).get("evolution")) or {}
    gates = evo.get("gates") or {}
    keys = list(gates.keys())
    expected = ["detect", "knowledge", "implement", "metrics", "council", "package", "publish"]
    ok = r["status"] == 200 and keys == expected
    body = {"status": r["status"], "label": evo.get("label"), "gate_keys": keys,
            "total_gate_count": len(keys)}
    _card(page, env, "EV3-evolution-gates.png", "EV3", "进化状态 7 项门禁",
          "/api/xcmax/ops/founder-autonomy", r["status"], body)
    return body, ok


def case_deploy_events(page, env):
    r = _api(page, "/api/xcmax/admin/autonomy/deploy-events")
    d = r.get("body") or {}
    items = d.get("items") or []
    ok = (r["status"] == 200 and d.get("ok") is True and len(items) > 0
          and all("deploy_id" in it and "status" in it and "source_workflow" in it for it in items))
    _card(page, env, "EV4-deploy-events.png", "EV4", "自驱部署事件与 status",
          "/api/xcmax/admin/autonomy/deploy-events", r["status"],
          {"ok": d.get("ok"), "count": len(items), "sample": items[:2]})
    return {"status": r["status"], "ok": d.get("ok"), "count": len(items),
            "sample": items[:2]}, ok


def case_unauth_deploy_events_denied(page, env):
    r = _unauth(page, env, "/api/xcmax/admin/autonomy/deploy-events",
                name="EV5-unauth-denied.png")
    b = r.get("body") or {}
    ok = r["status"] in (401, 403) and isinstance(b, dict) and b.get("success") is False
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "EV1", "title": "「服务器后台总览」页真实渲染软件版本与更新包",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/xcmax-admin，等待 SPA 渲染后读取标题与正文。",
     "expected": "渲染出「服务器后台总览」与「软件版本与更新包」（管理端版本 / update 站版本）。",
     "run": case_version_panel},
    {"id": "EV2", "title": "版本列车真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/xcmax/release-train。",
     "expected": "200 且 success=true；epoch=1.0.0.0，current=product_version=1.0.0.5，day_index 为整数。",
     "run": case_release_train},
    {"id": "EV3", "title": "进化状态 7 项门禁真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/xcmax/ops/founder-autonomy。",
     "expected": "200；dimensions[evolution] total_gate_count=7，门禁 key 与 impl 顺序一致。",
     "run": case_evolution_gates},
    {"id": "EV4", "title": "自驱部署事件与 status 真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/xcmax/admin/autonomy/deploy-events。",
     "expected": "200 且 ok=true；items 非空且含 deploy_id/status/source_workflow。",
     "run": case_deploy_events},
    {"id": "EV5", "title": "无会话访问部署事件接口被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 的上下文中 fetch GET /api/xcmax/admin/autonomy/deploy-events。",
     "expected": "被拒绝（401/403），不返回部署事件数据。",
     "run": case_unauth_deploy_events_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "EV1-version-panel.png": "「服务器后台总览」页渲染三栏：本地节点（本地地址 127.0.0.1:42423、异常）、远端服务器（离线）、软件版本与更新包（管理端版本/管理端 Git/update 站版本/update 站 Git/企业端 不可达/安装回执 0 台已安装），含「检测中...」「推送更新安装包」按钮。",
    "EV2-release-train.png": "本轮响应：GET /api/xcmax/release-train → 200，epoch=1.0.0.0，product_version=current=1.0.0.5，started_at 2026-07-12，day_index=1，reset_reason=stable-1.0.0.0-ssot。",
    "EV3-evolution-gates.png": "本轮响应：GET /api/xcmax/ops/founder-autonomy → 200，evolution 维度门禁 7 项 detect/knowledge/implement/metrics/council/package/publish，total_gate_count 7，progress 0。",
    "EV4-deploy-events.png": "本轮响应：GET /api/xcmax/admin/autonomy/deploy-events → 200，ok=true，count=20；样本 deploy_id=7e4092b6d7b6 status=failed、711be1d036e3 status=success，source_workflow=fhd-auto-update、head_branch=main。",
    "EV5-unauth-denied.png": "无会话的新浏览器上下文停留在管理员登录页，未出现任何部署事件数据。",
    "__video__": "本轮真实浏览器会话录像（webm，24.52s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 服务器后台总览版本面板 → 版本列车 → 进化门禁 → 部署事件 → 无会话被拒。",
}