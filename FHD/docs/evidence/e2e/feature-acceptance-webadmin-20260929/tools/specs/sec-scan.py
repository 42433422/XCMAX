"""sec-scan（安全扫描门禁员工运行时）Web 管理端真机验收用例。

impl 参考：FHD/app/mod_sdk/employee_pack_runtime.py（员工包统一 HTTP 面）
+ FHD/mods/_employees/security-secrets-guard、github-pr-gatekeeper、deploy-release-officer。
接口：GET /api/mod/{mid}/employees/{emp_id}/status、POST /api/mod/{mid}/employees/{emp_id}/run。
"""

import html as _html
import json as _json

FEATURE = "sec-scan"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文核验安全扫描门禁运行时："
    "安全密钥守卫员工 status=ready → 以脱敏 finding 触发其确定性只读审计动作返回 approved"
    "（read_only=true，无副作用）→ GitHub PR 守门员/发布官员工 status=ready → "
    "缺少 CSRF 的触发请求被 403 拒绝。"
)

_GUARD = "security-secrets-guard"
_PR = "github-pr-gatekeeper"
_RELEASE = "deploy-release-officer"


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


def _status_of(page, mid):
    r = _api(page, f"/api/mod/{mid}/employees/{mid}/status")
    d = r.get("body") or {}
    data = d.get("data") or {}
    return r["status"], data.get("status")


def case_gate_employees_ready(page, env):
    gs, guard = _status_of(page, _GUARD)
    ps, pr = _status_of(page, _PR)
    rs, release = _status_of(page, _RELEASE)
    body = {"guard": guard, "pr_gatekeeper": pr, "release_officer": release}
    ok = all(s == "ready" for s in (guard, pr, release)) and gs == ps == rs == 200
    _card(page, env, "S1-gate-employees.png", "S1", "安全/发布门禁员工就绪",
          "GET /api/mod/{mid}/employees/{mid}/status", gs, body)
    return body, ok


def case_secret_audit_run(page, env):
    payload = {"finding_summary": "redacted finding summary is clear"}
    r = _api(page, f"/api/mod/{_GUARD}/employees/{_GUARD}/run", "POST", payload)
    d = r.get("body") or {}
    data = d.get("data") or {}
    evidence = data.get("evidence") or []
    ok = (r["status"] == 200 and d.get("success") is True and data.get("ok") is True
          and data.get("read_only") is True and len(evidence) > 0)
    body = {"status": r["status"], "employee_status": data.get("status"),
            "read_only": data.get("read_only"), "evidence": evidence,
            "summary": data.get("summary"), "side_effects": data.get("side_effects")}
    _card(page, env, "S2-secret-audit-run.png", "S2", "安全密钥守卫执行脱敏审计（真实响应）",
          f"POST /api/mod/{_GUARD}/employees/{_GUARD}/run", r["status"], body)
    return body, ok


def case_scan_run_csrf_gate(page, env):
    payload = {"finding_summary": "redacted finding summary is clear"}
    r = _api(page, f"/api/mod/{_GUARD}/employees/{_GUARD}/run", "POST", payload, csrf=False)
    b = r.get("body") or {}
    ok = r["status"] == 403 and "CSRF token missing" in str(b.get("message"))
    _card(page, env, "S3-scan-run-csrf-gate.png", "S3", "缺少 CSRF 的扫描门禁触发被拒",
          f"POST /api/mod/{_GUARD}/employees/{_GUARD}/run (no x-csrf-token)", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "S1", "title": "安全/发布门禁员工就绪",
     "input": "无。",
     "actions": "页面上下文 GET 安全密钥守卫/GitHub PR 守门员/发布官员工 status。",
     "expected": "三者均 200 且 status=ready。",
     "run": case_gate_employees_ready},
    {"id": "S2", "title": "安全密钥守卫执行脱敏审计（真实响应）",
     "input": "脱敏 finding_summary（无敏感值）。",
     "actions": "页面上下文 POST 安全密钥守卫 run。",
     "expected": "200、success=true、data.ok=true、read_only=true。",
     "run": case_secret_audit_run},
    {"id": "S3", "title": "缺少 CSRF 的扫描门禁触发被拒（负例）",
     "input": "已登录会话，但不带 x-csrf-token 头。",
     "actions": "页面上下文 POST 安全密钥守卫 run。",
     "expected": "403 CSRF token missing。",
     "run": case_scan_run_csrf_gate},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "S1-gate-employees.png": "JSON：{security_secrets_guard:ready, github_pr_gatekeeper:ready, deploy_release_officer:ready}。",
    "S2-secret-audit-run.png": "POST 安全密钥守卫 run → 200 data.ok=true status=approved summary='redacted finding summary is clear' evidence=[fixture_only,redacted_counts_only,no_repository_scan,no_secret_output] read_only=true side_effects=[]。",
    "S3-scan-run-csrf-gate.png": "无 CSRF 的 POST run → 403 success=false message=CSRF token missing。",
    "__video__": "录像（webm，11.64s）：门禁员工就绪 → 脱敏审计执行 → CSRF 拒绝。",
}