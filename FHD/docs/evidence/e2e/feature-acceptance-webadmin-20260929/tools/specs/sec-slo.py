"""sec-slo（服务拓扑/SLO 运行时清单）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/xcmax_ops.py
（/api/xcmax/ops/runtime-inventory、/api/xcmax/ops/closure-status）。
"""

import html as _html
import json as _json

FEATURE = "sec-slo"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文核验服务拓扑/SLO："
    "GET /api/xcmax/ops/runtime-inventory 返回 schema=xcagi.runtime_inventory/v1 且 "
    "source.topology=config/topology.generated.json（拓扑 SSOT 派生）与每项 desired/actual 期望-实际态 → "
    "GET /api/xcmax/ops/closure-status 返回编制收敛状态 → 无会话访问运行时清单被拒（401）。"
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


def _unauth(page, env, path, method="GET", body=None, csrf=True):
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(1200)
    r = _api(pg, path, method, body, csrf)
    ctx.close()
    return r


def case_runtime_inventory(page, env):
    r = _api(page, "/api/xcmax/ops/runtime-inventory")
    d = r.get("body") or {}
    source = d.get("source") or {}
    items = d.get("items") or []
    ok = (r["status"] == 200 and d.get("schema") == "xcagi.runtime_inventory/v1"
          and source.get("topology") == "config/topology.generated.json"
          and len(items) > 0
          and all("desired" in it and "actual" in it for it in items))
    body = {"status": r["status"], "schema": d.get("schema"), "source": source,
            "counts": d.get("counts"), "item_sample": items[:1]}
    _card(page, env, "SL1-runtime-inventory.png", "SL1", "服务拓扑运行时清单真实读取",
          "GET /api/xcmax/ops/runtime-inventory", r["status"], body)
    return body, ok


def case_closure_status(page, env):
    r = _api(page, "/api/xcmax/ops/closure-status")
    d = r.get("body") or {}
    staffing = d.get("staffing") or {}
    ok = (r["status"] == 200 and d.get("success") is True
          and isinstance(staffing.get("planned_count"), int)
          and isinstance(staffing.get("registered_count"), int))
    body = {"status": r["status"], "planned": staffing.get("planned_count"),
            "registered": staffing.get("registered_count")}
    _card(page, env, "SL2-closure-status.png", "SL2", "编制收敛状态真实读取",
          "GET /api/xcmax/ops/closure-status", r["status"], body)
    return body, ok


def case_unauth_inventory_denied(page, env):
    r = _unauth(page, env, "/api/xcmax/ops/runtime-inventory")
    b = r.get("body") or {}
    ok = r["status"] in (401, 403)
    _card(page, env, "SL3-unauth-inventory.png", "SL3", "无会话访问运行时清单被拒",
          "GET /api/xcmax/ops/runtime-inventory (no session)", r["status"], b)
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "SL1", "title": "服务拓扑运行时清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/xcmax/ops/runtime-inventory。",
     "expected": "200、schema=xcagi.runtime_inventory/v1、source.topology=config/topology.generated.json、items 非空。",
     "run": case_runtime_inventory},
    {"id": "SL2", "title": "编制收敛状态真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/xcmax/ops/closure-status。",
     "expected": "200、success=true、staffing 含计划/登记数。",
     "run": case_closure_status},
    {"id": "SL3", "title": "无会话访问运行时清单被拒（负例）",
     "input": "全新无会话浏览器上下文。",
     "actions": "无 cookie/token 上下文 GET /api/xcmax/ops/runtime-inventory。",
     "expected": "被拒绝（401/403）。",
     "run": case_unauth_inventory_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "SL1-runtime-inventory.png": "GET /api/xcmax/ops/runtime-inventory 200：schema=xcagi.runtime_inventory/v1、source.topology=config/topology.generated.json、public_host=xiu-ci.com；counts total=14 running=2 stopped=7 unknown=5 must_run_failed=5；items 含 desktop-fhd desired=optional actual=running。",
    "SL2-closure-status.png": "GET /api/xcmax/ops/closure-status 200 success=true deliverable=true staffing planned_count=55 registered_count=55 missing_employees=[]。",
    "SL3-unauth-inventory.png": "无会话 GET runtime-inventory → 401 请先登录。",
    "__video__": "录像（webm，13.92s）：拓扑运行时清单 → 编制收敛 → 无会话拒绝。",
}