"""base-help（内置教程与教学资源）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/tutorial_routes.py
（/api/tutorial/v2/assets/business-import.xlsx、/api/tutorial/v2/courses）。
"""

import html as _html
import json as _json

FEATURE = "base-help"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文访问内置教程能力："
    "GET /api/tutorial/v2/assets/business-import.xlsx 真实下发教学练习工作簿（xlsx 二进制）→ "
    "GET /api/tutorial/v2/courses 在未绑定企业时返回 409 source_tenant_required（真实业务前置契约）→ "
    "无会话访问教程接口被拒（401）。"
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


def _binary(page, path):
    return page.evaluate(
        """async (p) => {
            try {
                const r = await fetch(p, {credentials: 'include'});
                const buf = await r.arrayBuffer();
                return {status: r.status, bytes: buf.byteLength,
                        content_type: r.headers.get('content-type') || ''};
            } catch (e) { return {status: 0, bytes: 0, content_type: String(e)}; }
        }""",
        path,
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


def case_tutorial_workbook(page, env):
    r = _binary(page, "/api/tutorial/v2/assets/business-import.xlsx")
    ok = (r["status"] == 200
          and "spreadsheetml.sheet" in r["content_type"] and r["bytes"] > 2000)
    _card(page, env, "BH1-tutorial-workbook.png", "BH1", "教程练习工作簿真实下发",
          "GET /api/tutorial/v2/assets/business-import.xlsx", r["status"],
          {"status": r["status"], "content_type": r["content_type"], "bytes": r["bytes"]})
    return {"status": r["status"], "content_type": r["content_type"], "bytes": r["bytes"]}, ok


def case_courses_tenant_gate(page, env):
    r = _api(page, "/api/tutorial/v2/courses")
    d = r.get("body") or {}
    code = (d.get("error") or {}).get("code") if isinstance(d.get("error"), dict) else d.get("error_code")
    hint = d.get("hint") or (d.get("error") or {}).get("hint")
    ok = r["status"] == 409 and code == "source_tenant_required"
    _card(page, env, "BH2-courses-tenant-gate.png", "BH2", "未绑定企业时教程课程返回业务前置拒绝",
          "GET /api/tutorial/v2/courses", r["status"],
          {"status": r["status"], "error_code": code, "hint": hint})
    return {"status": r["status"], "error_code": code, "hint": hint}, ok


def case_unauth_courses(page, env):
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(1200)
    r = _api(pg, "/api/tutorial/v2/courses")
    ctx.close()
    b = r.get("body") or {}
    ok = r["status"] in (401, 403)
    _card(page, env, "BH3-unauth-courses.png", "BH3", "无会话访问教程接口被拒",
          "GET /api/tutorial/v2/courses (no session)", r["status"], b)
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "BH1", "title": "教程练习工作簿真实下发",
     "input": "已登录会话。",
     "actions": "页面上下文 GET /api/tutorial/v2/assets/business-import.xlsx 并读取字节。",
     "expected": "200、xlsx content-type、字节数 > 2000。",
     "run": case_tutorial_workbook},
    {"id": "BH2", "title": "未绑定企业时教程课程返回业务前置拒绝",
     "input": "已登录但未加入企业的管理员账号。",
     "actions": "页面上下文 GET /api/tutorial/v2/courses。",
     "expected": "409 且错误码 source_tenant_required。",
     "run": case_courses_tenant_gate},
    {"id": "BH3", "title": "无会话访问教程接口被拒（负例）",
     "input": "全新无会话浏览器上下文。",
     "actions": "无 cookie/token 上下文 GET /api/tutorial/v2/courses。",
     "expected": "被拒绝（401/403）。",
     "run": case_unauth_courses},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "BH1-tutorial-workbook.png": "GET /api/tutorial/v2/assets/business-import.xlsx 200、content_type=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet、bytes=5103（真实下发教学练习工作簿）。",
    "BH2-courses-tenant-gate.png": "GET /api/tutorial/v2/courses → 409、error.code=source_tenant_required、hint=当前账号尚未加入企业，无法创建教学空间。",
    "BH3-unauth-courses.png": "无会话 GET courses → 401 http_401 UNAUTHORIZED 请先登录。",
    "__video__": "录像（webm，11.40s）：教学资源下发 → 课程租户前置拒绝 → 无会话拒绝。",
}