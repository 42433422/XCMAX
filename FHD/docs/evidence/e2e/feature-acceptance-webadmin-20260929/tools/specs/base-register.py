"""base-register（账户注册与找回）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/auth_routes.py（/api/auth/register、/api/auth/forgot-account）。
"""

import html as _html
import json as _json
import time as _time

FEATURE = "base-register"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文执行账户注册与找回："
    "真实 POST /api/auth/register 成功创建账号并返回角色/租户 → "
    "空参数注册被拒（400 INVALID_INPUT）→ 找回账号缺少有效邮箱被拒（400）。"
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


def case_register_ok(page, env):
    uname = "qa_reg_%d" % int(_time.time())
    r = _api(page, "/api/auth/register", "POST",
             {"username": uname, "password": "Reg#Pass9",
              "email": "%s@example.com" % uname})
    d = r.get("body") or {}
    data = d.get("data") or d
    user = data.get("user") or data
    ok = r["status"] == 200 and d.get("success") is True and bool(user.get("username"))
    _card(page, env, "BR1-register-ok.png", "BR1", "真实注册创建账号",
          "POST /api/auth/register", r["status"],
          {"status": r["status"], "success": d.get("success"),
           "username": user.get("username"), "role": user.get("role"),
           "tenant_id": user.get("tenant_id")})
    return {"status": r["status"], "success": d.get("success"),
            "username": user.get("username"), "role": user.get("role"),
            "tenant_id": user.get("tenant_id")}, ok


def case_register_missing(page, env):
    r = _api(page, "/api/auth/register", "POST", {})
    d = r.get("body") or {}
    code = (d.get("error") or {}).get("code") if isinstance(d.get("error"), dict) else d.get("error_code")
    ok = r["status"] == 400 and code == "INVALID_INPUT"
    _card(page, env, "BR2-register-missing.png", "BR2", "空参数注册被拒",
          "POST /api/auth/register (empty body)", r["status"],
          {"status": r["status"], "error_code": code,
           "message": d.get("message") or (d.get("error") or {}).get("message")})
    return {"status": r["status"], "error_code": code}, ok


def case_forgot_account_negative(page, env):
    r = _api(page, "/api/auth/forgot-account", "POST", {"username": "qa_unknown"})
    d = r.get("body") or {}
    code = (d.get("error") or {}).get("code") if isinstance(d.get("error"), dict) else d.get("error_code")
    ok = r["status"] == 400 and code == "INVALID_INPUT"
    _card(page, env, "BR3-forgot-account-negative.png", "BR3", "账号找回缺少有效邮箱被拒",
          "POST /api/auth/forgot-account (username only)", r["status"],
          {"status": r["status"], "error_code": code,
           "message": d.get("message") or (d.get("error") or {}).get("message")})
    return {"status": r["status"], "error_code": code}, ok


CASES = [
    {"id": "BR1", "title": "真实注册创建账号",
     "input": "唯一用户名/密码/邮箱，在已登录页面上下文提交注册。",
     "actions": "页面上下文 POST /api/auth/register（带 CSRF 双提交）。",
     "expected": "200、success=true、返回新用户名与角色（viewer）。",
     "run": case_register_ok},
    {"id": "BR2", "title": "空参数注册被拒（边界/负例）",
     "input": "空对象。",
     "actions": "页面上下文 POST /api/auth/register 空 body。",
     "expected": "400 且错误码 INVALID_INPUT。",
     "run": case_register_missing},
    {"id": "BR3", "title": "账号找回缺少有效邮箱被拒（负例）",
     "input": "只给 username、无邮箱。",
     "actions": "页面上下文 POST /api/auth/forgot-account。",
     "expected": "400 且错误码 INVALID_INPUT（提示填写有效邮箱）。",
     "run": case_forgot_account_negative},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "BR1-register-ok.png": "POST /api/auth/register 200 success=true，user.username=qa_reg_…、role=viewer、tenant_id=2、account_kind=personal，并建立 session_id。",
    "BR2-register-missing.png": "空 body 注册 → 400、error.code=INVALID_INPUT、message=用户名和密码不能为空。",
    "BR3-forgot-account-negative.png": "POST /api/auth/forgot-account 仅给 username → 400、INVALID_INPUT、请填写有效邮箱。",
    "__video__": "录像（webm，11.64s）：页面上下文真实完成 注册成功 / 空参拒绝 / 找回缺邮箱拒绝。",
}