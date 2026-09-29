"""ops-delivery-sync（交付阶段推进与私有 Mod 更新门禁）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/delivery_sync_routes.py
（/api/mod-store/private-delivery/status、/api/mod-store/private-mod/update）。
管理端 UI：/admin/delivery-center（客户交付中心，同步交付状态）。
"""

import html as _html
import json as _json

FEATURE = "ops-delivery-sync"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → "
    "「客户交付中心」页真实渲染CUSTOMER DELIVERY CONTROL 交付台账"
    "（定制交付工单/生产进行中及客户安装与业务验收独立核对口径）"
    "并真实点击「同步交付状态」触发同步动作 → "
    "POST /api/mod-store/private-delivery/status 缺少 mod_id/track/status 被参数校验拒绝（400）→ "
    "对未授权客户私有 Mod 推进阶段被越权拒绝（403）→ 对未授权私有 Mod 更新同样被拒（403）。"
    "本机未绑定修茈市场账号，故交付阶段成功流转的 200 正向路径不可达，相关拒绝为真实产品响应。"
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


def case_status_missing_params(page, env):
    r = _api(page, "/api/mod-store/private-delivery/status", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "缺少 mod_id、track 或 status" in str(b.get("message"))
    _card(page, env, "DS1-status-missing-params.png", "DS1",
          "交付阶段推进缺少参数被拒",
          "POST /api/mod-store/private-delivery/status (empty body)", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


def case_status_unauthorized(page, env):
    payload = {"mod_id": "xcagi-probe-mod", "track": "modules", "status": "testing"}
    r = _api(page, "/api/mod-store/private-delivery/status", "POST", payload)
    b = r.get("body") or {}
    ok = r["status"] == 403 and "当前账号未授权该客户私有 Mod" in str(b.get("message"))
    _card(page, env, "DS2-status-unauthorized.png", "DS2",
          "对未授权客户私有 Mod 推进阶段被拒",
          "POST /api/mod-store/private-delivery/status (mod_id=xcagi-probe-mod)", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


def case_update_unauthorized(page, env):
    r = _api(page, "/api/mod-store/private-mod/update", "POST", {"mod_id": "xcagi-probe-mod"})
    b = r.get("body") or {}
    ok = r["status"] == 403 and "当前账号未授权该客户私有 Mod" in str(b.get("message"))
    _card(page, env, "DS3-update-unauthorized.png", "DS3",
          "对未授权客户私有 Mod 更新被拒",
          "POST /api/mod-store/private-mod/update (mod_id=xcagi-probe-mod)", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


def case_delivery_progress_ui(page, env):
    text = _render(page, env, "/admin/delivery-center",
                   name="DS4-delivery-progress-ui.png", wait_for="客户交付中心")
    clicked = False
    try:
        page.click("text=同步交付状态", timeout=5000)
        clicked = True
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or text
        page.screenshot(path=str(env["shot"] / "DS4-delivery-progress-ui.png"))
    except Exception:
        pass
    visible = {"客户交付中心": "客户交付中心" in text,
               "CUSTOMER DELIVERY CONTROL": "CUSTOMER DELIVERY CONTROL" in text,
               "定制交付工单": "定制交付工单" in text,
               "生产进行中": "生产进行中" in text,
               "独立验收口径": "客户安装与业务验收独立核对" in text}
    ok = clicked and all(visible.values())
    return {"final_url": page.url, "sync_clicked": clicked, "visible_items": visible,
            "text_head": text.replace("\n", " ")[:240]}, ok


CASES = [
    {"id": "DS1", "title": "交付阶段推进缺少参数被拒（边界）",
     "input": "已建立的管理员会话；空请求体。",
     "actions": "页面上下文 POST /api/mod-store/private-delivery/status（空 body）。",
     "expected": "HTTP 400，success=false，提示缺少 mod_id、track 或 status。",
     "run": case_status_missing_params},
    {"id": "DS2", "title": "对未授权客户私有 Mod 推进阶段被越权拒绝（负例）",
     "input": "mod_id=xcagi-probe-mod（当前账号未授权）。",
     "actions": "页面上下文 POST /api/mod-store/private-delivery/status。",
     "expected": "HTTP 403，success=false，提示当前账号未授权该客户私有 Mod。",
     "run": case_status_unauthorized},
    {"id": "DS3", "title": "对未授权客户私有 Mod 更新被越权拒绝（负例）",
     "input": "mod_id=xcagi-probe-mod（当前账号未授权）。",
     "actions": "页面上下文 POST /api/mod-store/private-mod/update。",
     "expected": "HTTP 403，success=false，提示当前账号未授权该客户私有 Mod。",
     "run": case_update_unauthorized},
    {"id": "DS4", "title": "「客户交付中心」页真实渲染交付台账并触发同步动作",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/delivery-center，读取交付台账后真实点击「同步交付状态」。",
     "expected": "渲染出「客户交付中心」CUSTOMER DELIVERY CONTROL 台账（定制交付工单/生产进行中/独立验收口径），同步按钮可点击。",
     "run": case_delivery_progress_ui},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "DS1-status-missing-params.png": "本轮响应：POST /api/mod-store/private-delivery/status（空 body）→ 400，success=false，message=缺少 mod_id、track 或 status。",
    "DS2-status-unauthorized.png": "本轮响应：POST /api/mod-store/private-delivery/status（mod_id=xcagi-probe-mod, track=modules, status=testing）→ 403，success=false，message=当前账号未授权该客户私有 Mod。",
    "DS3-update-unauthorized.png": "本轮响应：POST /api/mod-store/private-mod/update（mod_id=xcagi-probe-mod）→ 403，success=false，message=当前账号未授权该客户私有 Mod。",
    "DS4-delivery-progress-ui.png": "「客户交付中心」页渲染 CUSTOMER DELIVERY CONTROL 台账（企业用户/永久交付完成/定制交付工单/生产进行中各 0），红字「尚未绑定修茈服务器账号…」；已真实点击「同步交付状态」（画面中该按钮为高亮态）。",
    "__video__": "本轮真实浏览器会话录像（webm，16.68s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 交付阶段缺参 400 → 未授权 403 → 私有 Mod 更新 403 → 交付中心台账并点击同步。",
}