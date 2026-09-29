"""ops-issue-runtime（问题工单确认与交付回执）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/issue_runtime_routes.py
（/api/mod-store/issue-runtime、/api/mod-store/issue-runtime/{id}、/api/mod-store/receipts/retry）。
"""

import html as _html
import json as _json

FEATURE = "ops-issue-runtime"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → "
    "POST /api/mod-store/issue-runtime/1 在客户勾选确认但未填修复结果说明时被校验拒绝（400）→ "
    "GET /api/mod-store/issue-runtime 未登录市场账号被拒（401）→ "
    "未确认提交同样因缺市场账号被拒（401）→ "
    "POST /api/mod-store/receipts/retry 交付回执重试因缺市场账号被拒（401）。"
    "因本机未绑定修茈市场账号，问题工单的正向确认回执闭环未能真机验证。"
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


def case_confirm_note_required(page, env):
    r = _api(page, "/api/mod-store/issue-runtime/1", "POST", {"confirmed": True, "note": "x"})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "至少4个字" in str(b.get("message"))
    _card(page, env, "IR1-confirm-note-required.png", "IR1",
          "客户确认修复但未填结果说明被拒",
          "POST /api/mod-store/issue-runtime/1 (confirmed=true, note=x)", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


def case_list_market_required(page, env):
    r = _api(page, "/api/mod-store/issue-runtime")
    b = r.get("body") or {}
    ok = r["status"] == 401 and "请登录市场账号查看修复交付" in str(b.get("message"))
    _card(page, env, "IR2-list-market-required.png", "IR2",
          "读取待确认修复交付未登录市场账号被拒",
          "GET /api/mod-store/issue-runtime", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


def case_submit_market_required(page, env):
    r = _api(page, "/api/mod-store/issue-runtime/1", "POST", {"confirmed": False, "note": ""})
    b = r.get("body") or {}
    ok = r["status"] == 401 and "请登录市场账号查看修复交付" in str(b.get("message"))
    _card(page, env, "IR3-submit-market-required.png", "IR3",
          "提交修复结果未登录市场账号被拒",
          "POST /api/mod-store/issue-runtime/1 (confirmed=false, note='')", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


def case_receipts_retry_denied(page, env):
    r = _api(page, "/api/mod-store/receipts/retry", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 401 and "请登录市场账号后同步交付回执" in str(b.get("message"))
    _card(page, env, "IR4-receipts-retry-401.png", "IR4",
          "交付回执重试未登录市场账号被拒",
          "POST /api/mod-store/receipts/retry", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "IR1", "title": "客户确认修复但未填结果说明被拒（边界）",
     "input": "已建立的管理员会话；{confirmed:true, note:'x'}。",
     "actions": "页面上下文 POST /api/mod-store/issue-runtime/1。",
     "expected": "HTTP 400，success=false，提示说明原问题使用结果至少 4 个字。",
     "run": case_confirm_note_required},
    {"id": "IR2", "title": "读取待确认修复交付未登录市场账号被拒（负例）",
     "input": "已建立的管理员会话，未绑定市场账号。",
     "actions": "页面上下文 GET /api/mod-store/issue-runtime。",
     "expected": "HTTP 401，success=false，提示请登录市场账号查看修复交付。",
     "run": case_list_market_required},
    {"id": "IR3", "title": "提交修复结果未登录市场账号被拒（负例）",
     "input": "已建立的管理员会话；{confirmed:false, note:''}。",
     "actions": "页面上下文 POST /api/mod-store/issue-runtime/1。",
     "expected": "HTTP 401，success=false，不落盘回执。",
     "run": case_submit_market_required},
    {"id": "IR4", "title": "交付回执重试未登录市场账号被拒（负例）",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 POST /api/mod-store/receipts/retry。",
     "expected": "HTTP 401，success=false，提示请登录市场账号后同步交付回执。",
     "run": case_receipts_retry_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "IR1-confirm-note-required.png": "本轮响应：POST /api/mod-store/issue-runtime/1（confirmed=true, note=x）→ 400，success=false，message=请说明原问题现在的使用结果（至少4个字）。",
    "IR2-list-market-required.png": "本轮响应：GET /api/mod-store/issue-runtime → 401，success=false，message=请登录市场账号查看修复交付。",
    "IR3-submit-market-required.png": "本轮响应：POST /api/mod-store/issue-runtime/1（confirmed=false, note=''）→ 401，success=false，message=请登录市场账号查看修复交付。",
    "IR4-receipts-retry-401.png": "本轮响应：POST /api/mod-store/receipts/retry → 401，success=false，message=请登录市场账号后同步交付回执。",
    "__video__": "本轮真实浏览器会话录像（webm，11.52s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 确认缺说明 400 → 列表/提交/回执重试均 401。",
}