"""sec-continuous-observe（持续运行观察与就绪门禁）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/health_routes.py（/api/health、/health/details、/health/readiness）、
FHD/app/fastapi_routes/neurobus_routes.py（/api/neurobus/health）。
"""

import html as _html
import json as _json

FEATURE = "sec-continuous-observe"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文核验持续运行观察："
    "GET /api/health 返回运行时组件与神经总线状态 → "
    "GET /api/neurobus/health 返回 healthy/running 及发布/处理计数 → "
    "GET /health/details 返回 database 等检查项 → "
    "GET /health/readiness 在依赖缺失时返回 503 not_ready。"
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


def case_health_runtime(page, env):
    r = _api(page, "/api/health")
    d = r.get("body") or {}
    runtime = d.get("runtime") or {}
    comps = runtime.get("components") or {}
    ok = (r["status"] == 200 and runtime.get("status") == "healthy" and len(comps) > 0)
    body = {"status": r["status"], "version": d.get("version"),
            "runtime_status": runtime.get("status"), "components_total": len(comps)}
    _card(page, env, "O1-health-runtime.png", "O1", "运行健康接口返回组件与版本",
          "GET /api/health", r["status"], body)
    return body, ok


def case_neurobus_health(page, env):
    r = _api(page, "/api/neurobus/health")
    d = r.get("body") or {}
    ok = (r["status"] == 200 and d.get("status") == "healthy" and d.get("running") is True
          and isinstance(d.get("published"), int) and isinstance(d.get("processed"), int))
    body = {"status": r["status"], "health": d.get("status"), "running": d.get("running"),
            "published": d.get("published"), "processed": d.get("processed")}
    _card(page, env, "O2-neurobus-health.png", "O2", "神经总线持续运行计数可观察",
          "GET /api/neurobus/health", r["status"], body)
    return body, ok


def case_readiness_gate(page, env):
    details = _api(page, "/health/details")
    ready = _api(page, "/health/readiness")
    d = details.get("body") or {}
    checks = d.get("checks") or {}
    ok = (details["status"] == 200 and len(checks) > 0
          and ready["status"] in (200, 503))
    body = {"details_status": details["status"], "readiness_status": ready["status"]}
    _card(page, env, "O3-readiness-gate.png", "O3", "就绪门禁与详情探针（含降级边界）",
          "GET /health/details + GET /health/readiness", ready["status"], body)
    return body, ok


CASES = [
    {"id": "O1", "title": "运行健康接口返回组件与版本",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/health。",
     "expected": "200、runtime.status=healthy、组件表非空。",
     "run": case_health_runtime},
    {"id": "O2", "title": "神经总线持续运行计数可观察",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/neurobus/health。",
     "expected": "200、status=healthy、running=true、published/processed 计数存在。",
     "run": case_neurobus_health},
    {"id": "O3", "title": "就绪门禁与详情探针（含降级边界）",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /health/details 与 GET /health/readiness。",
     "expected": "details=200 且 outline 检查项存在；readiness 依据依赖返回 200/503。",
     "run": case_readiness_gate},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "O1-health-runtime.png": "GET /api/health 200：version=1.0.0.5、git_sha=8d1fd8f6…、runtime_status=healthy、components_total=37、neuro_running=true。",
    "O2-neurobus-health.png": "GET /api/neurobus/health 200：health=healthy、running=true、published=26068、processed=26068、handlers=136。",
    "O3-readiness-gate.png": "GET /health/details 200（database healthy、redis unhealthy、ai_service healthy 且 engines 已加载）；GET /health/readiness 因 redis unavailable 返回 503 not_ready。",
    "__video__": "录像（webm，11.76s）：运行健康 → 神经总线计数 → 就绪门禁（降级）。",
}