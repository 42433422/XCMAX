"""sec-audit（操作审计与只增自治账本）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/admin_audit_routes.py（/api/admin/audit-logs）、
FHD/app/fastapi_routes/ops_autonomy_admin_routes.py（/api/xcmax/admin/autonomy/audit-log）。
"""

import html as _html
import json as _json

FEATURE = "sec-audit"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文核验操作审计："
    "GET /api/admin/audit-logs 返回审计分页并声明 requested_by=admin → "
    "GET /api/xcmax/admin/autonomy/audit-log 返回只追加(append_only=true)的自治审计账本 → "
    "无会话上下文访问审计接口被拒（401）。"
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


def case_audit_logs(page, env):
    r = _api(page, "/api/admin/audit-logs")
    d = r.get("body") or {}
    data = d.get("data") or {}
    ok = (r["status"] == 200 and d.get("success") is True
          and d.get("requested_by") == "admin")
    _card(page, env, "A1-audit-logs.png", "A1", "审计日志接口以管理会话身份应答",
          "GET /api/admin/audit-logs", r["status"],
          {"status": r["status"], "success": d.get("success"),
           "requested_by": d.get("requested_by"), "total": data.get("total"),
           "path_configured": d.get("path_configured")})
    return {"status": r["status"], "success": d.get("success"),
            "requested_by": d.get("requested_by"), "total": data.get("total"),
            "path_configured": d.get("path_configured")}, ok


def case_autonomy_audit_ledger(page, env):
    r = _api(page, "/api/xcmax/admin/autonomy/audit-log")
    d = r.get("body") or {}
    items = d.get("items") or []
    ok = r["status"] == 200 and d.get("append_only") is True and isinstance(items, list)
    _card(page, env, "A2-autonomy-audit-ledger.png", "A2", "自治审计账本为只追加",
          "GET /api/xcmax/admin/autonomy/audit-log", r["status"],
          {"status": r["status"], "append_only": d.get("append_only"), "count": len(items)})
    return {"status": r["status"], "append_only": d.get("append_only"),
            "count": len(items)}, ok


def case_unauth_audit_denied(page, env):
    r = _unauth(page, env, "/api/admin/audit-logs")
    b = r.get("body") or {}
    ok = r["status"] in (401, 403)
    _card(page, env, "A3-unauth-audit-denied.png", "A3", "未登录会话访问审计接口被拒",
          "GET /api/admin/audit-logs (no session)", r["status"], b)
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "A1", "title": "审计日志接口以管理会话身份应答",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/admin/audit-logs。",
     "expected": "200、success=true、requested_by=admin。",
     "run": case_audit_logs},
    {"id": "A2", "title": "自治审计账本为只追加",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/xcmax/admin/autonomy/audit-log。",
     "expected": "200 且 append_only=true，items 为数组。",
     "run": case_autonomy_audit_ledger},
    {"id": "A3", "title": "未登录会话访问审计接口被拒",
     "input": "全新无会话浏览器上下文。",
     "actions": "无 cookie/token 上下文 GET /api/admin/audit-logs。",
     "expected": "被拒绝（401/403）。",
     "run": case_unauth_audit_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "A1-audit-logs.png": "GET /api/admin/audit-logs 200 success=true，data.items=[]、total=0、path_configured=false、requested_by=admin。",
    "A2-autonomy-audit-ledger.png": "GET /api/xcmax/admin/autonomy/audit-log 200 append_only=true，count=6，样本 employee_execute/auto_approve（含 risk_level/source/rollback_path/metadata）。",
    "A3-unauth-audit-denied.png": "无会话 GET /api/admin/audit-logs → 401 UNAUTHORIZED 请先登录。",
    "__video__": "录像（webm，11.40s）：审计分页 → 只追加自治账本 → 无会话拒绝。",
}