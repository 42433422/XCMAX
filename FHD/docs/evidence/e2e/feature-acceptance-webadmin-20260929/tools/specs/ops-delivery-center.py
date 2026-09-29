"""ops-delivery-center（客户交付台账与同步门禁）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/private_mod_delivery_routes.py
（/api/mod-store/private-delivery/sync，市场账号身份门禁 + CSRF 双提交门禁）。
管理端 UI：/admin/delivery-center（客户交付中心，CUSTOMER DELIVERY CONTROL）。
"""

import html as _html
import json as _json

FEATURE = "ops-delivery-center"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → "
    "「客户交付中心」页真实渲染（CUSTOMER DELIVERY CONTROL 客户交付台账：企业用户/永久购买账户/"
    "永久待安装/待首次登录/永久交付完成/内部本机排除/定制交付工单/生产进行中，及全部阶段漏斗）"
    "并真实点击「刷新」触发同步 → POST /api/mod-store/private-delivery/sync "
    "在未绑定市场账号时被拒（401）→ 同一接口缺少 CSRF 双提交令牌时被安全中间件拒绝（403）。"
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


def case_delivery_center_sync(page, env):
    text = _render(page, env, "/admin/delivery-center",
                   name="DC1-delivery-center.png", wait_for="客户交付中心")
    clicked = False
    try:
        page.click("text=刷新", timeout=5000)
        clicked = True
    except Exception:
        pass
    if clicked:
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or text
        page.screenshot(path=str(env["shot"] / "DC1-delivery-center.png"))
    ok = ("CUSTOMER DELIVERY CONTROL" in text and "永久交付完成" in text
          and "定制交付工单" in text and clicked)
    return {"final_url": page.url, "title": page.title(), "refresh_clicked": clicked,
            "has_control_header": "CUSTOMER DELIVERY CONTROL" in text,
            "has_permanent_delivered": "永久交付完成" in text,
            "has_custom_ticket": "定制交付工单" in text,
            "text_head": text.replace("\n", " ")[:240]}, ok


def case_sync_market_gate(page, env):
    r = _api(page, "/api/mod-store/private-delivery/sync", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 401 and b.get("success") is False and "请登录已绑定市场的账号" in str(b.get("message"))
    _card(page, env, "DC2-sync-market-gate.png", "DC2",
          "交付同步未绑定市场账号被拒",
          "POST /api/mod-store/private-delivery/sync", r["status"], b)
    return {"status": r["status"], "message": b.get("message"),
            "error_code": b.get("error_code")}, ok


def case_sync_no_csrf_denied(page, env):
    r = _api(page, "/api/mod-store/private-delivery/sync", "POST", {}, csrf=False)
    b = r.get("body") or {}
    ok = r["status"] == 403 and "CSRF token missing" in str(b.get("message"))
    _card(page, env, "DC3-sync-no-csrf.png", "DC3",
          "交付同步缺少 CSRF 令牌被拒",
          "POST /api/mod-store/private-delivery/sync (no X-CSRF-Token)", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "DC1", "title": "「客户交付中心」页真实渲染并触发同步",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/delivery-center，等待渲染并真实点击「刷新」，滚动读取交付台账。",
     "expected": "渲染出 CUSTOMER DELIVERY CONTROL 客户交付台账（永久交付完成/定制交付工单等指标）。",
     "run": case_delivery_center_sync},
    {"id": "DC2", "title": "交付同步未绑定市场账号被拒（负例）",
     "input": "已建立的管理员会话，但未绑定修茈市场账号。",
     "actions": "页面上下文 POST /api/mod-store/private-delivery/sync。",
     "expected": "HTTP 401，success=false，提示请登录已绑定市场的账号。",
     "run": case_sync_market_gate},
    {"id": "DC3", "title": "交付同步缺少 CSRF 令牌被拒（边界）",
     "input": "已建立的管理员会话，但 POST 不带 X-CSRF-Token。",
     "actions": "页面上下文 POST /api/mod-store/private-delivery/sync（不附加 CSRF 头）。",
     "expected": "HTTP 403，success=false，message=CSRF token missing。",
     "run": case_sync_no_csrf_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "DC1-delivery-center.png": "「客户交付中心」页真实渲染并点击「刷新」：CUSTOMER DELIVERY CONTROL 客户交付中心台账可见 企业用户/永久购买账户/体验账户/永久待安装/待首次登录/永久交付完成/内部本机排除/定制交付工单（均 0）/生产进行中 0，含「同步交付状态」按钮与「全部阶段」筛选。",
    "DC2-sync-market-gate.png": "本轮响应：POST /api/mod-store/private-delivery/sync → 401，success=false，message=请登录已绑定市场的账号，path=/api/mod-store/private-delivery/sync。",
    "DC3-sync-no-csrf.png": "本轮响应：POST /api/mod-store/private-delivery/sync（无 X-CSRF-Token）→ 403，success=false，message=CSRF token missing。",
    "__video__": "本轮真实浏览器会话录像（webm，18.60s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 客户交付中心渲染并刷新 → 同步 401 → 缺 CSRF 403。",
}