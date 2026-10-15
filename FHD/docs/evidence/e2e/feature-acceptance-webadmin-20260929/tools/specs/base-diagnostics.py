"""base-diagnostics（诊断能力与客户端日志）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/diagnostics_routes.py（/api/diagnostics/capabilities）、
FHD/app/fastapi_routes/debug_routes.py（/api/debug/client-log）。
"""

import html as _html
import json as _json

FEATURE = "base-diagnostics"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文完成诊断："
    "GET /api/diagnostics/capabilities 返回各子引擎（rasa 等）状态快照 → "
    "POST /api/debug/client-log 上报客户端日志成功 → "
    "对只写接口用 GET 访问被拒（405）。"
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


def case_diagnostics_capabilities(page, env):
    r = _api(page, "/api/diagnostics/capabilities")
    d = r.get("body") or {}
    keys = sorted(d.keys())
    rasa = d.get("rasa") or {}
    ok = r["status"] == 200 and "timestamp" in keys and "rasa" in keys and "status" in rasa
    _card(page, env, "BD1-diagnostics-capabilities.png", "BD1", "诊断能力快照真实返回",
          "GET /api/diagnostics/capabilities", r["status"],
          {"status": r["status"], "keys": keys, "rasa_status": rasa.get("status")})
    return {"status": r["status"], "keys": keys, "rasa_status": rasa.get("status")}, ok


def case_client_log_upload(page, env):
    r = _api(page, "/api/debug/client-log", "POST",
             {"level": "error", "message": "e2e diagnostics probe", "source": "e2e"})
    d = r.get("body") or {}
    ok = r["status"] == 200 and d.get("success") is True
    _card(page, env, "BD2-client-log-upload.png", "BD2", "客户端日志上报成功",
          "POST /api/debug/client-log", r["status"],
          {"status": r["status"], "success": d.get("success")})
    return {"status": r["status"], "success": d.get("success")}, ok


def case_client_log_get_rejected(page, env):
    r = _api(page, "/api/debug/client-log")
    d = r.get("body") or {}
    ok = r["status"] == 404 and d.get("success") is False
    _card(page, env, "BD3-client-log-get-rejected.png", "BD3", "只写接口用 GET 访问被拒",
          "GET /api/debug/client-log (POST-only route)", r["status"], d)
    return {"status": r["status"], "body": d}, ok


CASES = [
    {"id": "BD1", "title": "诊断能力快照真实返回",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/diagnostics/capabilities。",
     "expected": "200 且含时间戳与子引擎（rasa）状态。",
     "run": case_diagnostics_capabilities},
    {"id": "BD2", "title": "客户端日志上报成功",
     "input": "一条 error 级客户端日志。",
     "actions": "页面上下文 POST /api/debug/client-log。",
     "expected": "200 且 success=true。",
     "run": case_client_log_upload},
    {"id": "BD3", "title": "只写接口用 GET 访问被拒（负例）",
     "input": "无。",
     "actions": "页面上下文 GET /api/debug/client-log（仅有 POST 路由）。",
     "expected": "404（该后端对未匹配方法返回统一 404 资源不存在）。",
     "run": case_client_log_get_rejected},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "BD1-diagnostics-capabilities.png": "GET /api/diagnostics/capabilities 200，keys=[timestamp,rasa,pyvector,engines,ai_service]；rasa.status=degraded available=false（model_not_found）。",
    "BD2-client-log-upload.png": "POST /api/debug/client-log 200 success=true（客户端日志已接收）。",
    "BD3-client-log-get-rejected.png": "GET /api/debug/client-log（仅有 POST 路由）→ 404 success=false 资源不存在。",
    "__video__": "录像（webm，11.56s）：诊断快照 → 日志上报 → GET 拒绝。",
}