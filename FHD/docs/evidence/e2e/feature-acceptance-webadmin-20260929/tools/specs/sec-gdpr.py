"""sec-gdpr（GDPR 接口底座与门禁）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/gdpr_routes.py（/api/gdpr/status/{id}、/api/gdpr/export）。
运行时组件表：/api/health → runtime.components.gdpr_routes。
"""

import html as _html
import json as _json

FEATURE = "sec-gdpr"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文核验 GDPR 接口底座："
    "/api/health 运行时组件表显示 gdpr_routes=ok（3 个 /api/gdpr/* 端点已注册）→ "
    "GET /api/gdpr/status/{id} 返回 503 FEATURE_DISABLED（experimental.gdpr_api 默认关闭）→ "
    "无 CSRF 令牌的 POST /api/gdpr/export 被 403 拒绝。"
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


def case_gdpr_routes_registered(page, env):
    r = _api(page, "/api/health")
    d = r.get("body") or {}
    comps = (d.get("runtime") or {}).get("components") or {}
    gdpr = comps.get("gdpr_routes") or {}
    ok = r["status"] == 200 and gdpr.get("ok") is True
    _card(page, env, "G1-gdpr-routes-registered.png", "G1", "GDPR 路由已注册（运行时组件表）",
          "GET /api/health → runtime.components.gdpr_routes", r["status"],
          {"status": r["status"], "gdpr_routes": gdpr})
    return {"status": r["status"], "gdpr_routes": gdpr}, ok


def case_gdpr_status_feature_gate(page, env):
    r = _api(page, "/api/gdpr/status/e2e-probe")
    b = r.get("body") or {}
    msg = str(b.get("message") if isinstance(b, dict) else b)
    ok = r["status"] == 503 and "FEATURE_DISABLED" in msg and "experimental.gdpr_api" in msg
    _card(page, env, "G2-gdpr-status-feature-gate.png", "G2", "GDPR 接口受 Feature Flag 门禁（默认关闭）",
          "GET /api/gdpr/status/e2e-probe", r["status"], b)
    return {"status": r["status"], "message": msg}, ok


def case_gdpr_export_csrf_gate(page, env):
    r = _api(page, "/api/gdpr/export", "POST", {}, csrf=False)
    b = r.get("body") or {}
    ok = r["status"] == 403 and "CSRF token missing" in str(b.get("message"))
    _card(page, env, "G3-gdpr-export-csrf-gate.png", "G3", "缺少 CSRF 令牌的导出请求被拒",
          "POST /api/gdpr/export (no x-csrf-token)", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "G1", "title": "GDPR 路由已注册（运行时组件表）",
     "input": "无。",
     "actions": "页面上下文 GET /api/health，读取 runtime.components.gdpr_routes。",
     "expected": "gdpr_routes.ok=true。",
     "run": case_gdpr_routes_registered},
    {"id": "G2", "title": "GDPR 接口受 Feature Flag 门禁（默认关闭）",
     "input": "已登录管理员会话。",
     "actions": "页面上下文 GET /api/gdpr/status/{task_id}。",
     "expected": "503 且含 FEATURE_DISABLED（experimental.gdpr_api 默认关闭）。",
     "run": case_gdpr_status_feature_gate},
    {"id": "G3", "title": "缺少 CSRF 令牌的导出请求被拒（负例）",
     "input": "已登录会话，但不带 x-csrf-token 头。",
     "actions": "页面上下文 POST /api/gdpr/export。",
     "expected": "403 CSRF token missing。",
     "run": case_gdpr_export_csrf_gate},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "G1-gdpr-routes-registered.png": "GET /api/health：git_sha=8d1fd8f686884c7fc637ef2fa3e3e048a0074bec；runtime.components.gdpr_routes.ok=true（/api/gdpr/* 端点已注册）。",
    "G2-gdpr-status-feature-gate.png": "GET /api/gdpr/status/e2e-probe → 503 http_503，message 含 FEATURE_DISABLED / Feature Flag: experimental.gdpr_api。",
    "G3-gdpr-export-csrf-gate.png": "无 CSRF 的 POST /api/gdpr/export → 403 success=false message=CSRF token missing。",
    "__video__": "录像（webm，11.48s）：路由注册核验 → 特性开关门禁 → CSRF 双提交门禁。",
}