"""ops-customer-value（客户价值门禁）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/xcmax_ops.py（/api/xcmax/ops/founder-autonomy，
customer 维度六项门禁与 attention）、FHD/app/fastapi_routes/ops_autonomy_admin_routes.py
（/api/xcmax/admin/autonomy/overview）。
管理端 UI：/admin/founder-autonomy（创始人自治驾驶舱）。
"""

import html as _html
import json as _json

FEATURE = "ops-customer-value"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → "
    "「创始人自治驾驶舱」页真实渲染「客户状态」卡片（0% · 能力早期 · 还差 100% · "
    "权威价值账本 · 查看 0/6 项证据门槛）→ GET /api/xcmax/ops/founder-autonomy "
    "返回客户价值 6 项门禁（value_ledger/paid/goals/delivered/capacity/outcome）与 "
    "57 项行动事项 attention → 审批/审计总览接口以管理会话应答 → "
    "无会话访问客户价值接口被拒（401）。"
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


def _unauth(page, env, path, method="GET", body=None, csrf=True, name=None):
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(1200)
    r = _api(pg, path, method, body, csrf)
    if name:
        pg.screenshot(path=str(env["shot"] / name))
    ctx.close()
    return r


def case_customer_card(page, env):
    text = _render(page, env, "/admin/founder-autonomy",
                   name="CV1-founder-autonomy-customer.png", wait_for="创始人自治驾驶舱")
    ok = ("客户状态" in text and "客户为可验证产出付费" in text
          and "权威价值账本" in text and "0/6 项证据门槛" in text)
    return {"final_url": page.url, "title": page.title(),
            "has_customer_dim": "客户状态" in text,
            "has_customer_target": "客户为可验证产出付费" in text,
            "has_value_ledger_gap": "权威价值账本" in text,
            "has_gate_count": "0/6 项证据门槛" in text,
            "text_head": text.replace("\n", " ")[:240]}, ok


def case_customer_gates(page, env):
    r = _api(page, "/api/xcmax/ops/founder-autonomy")
    d = r.get("body") or {}
    cust = ((d.get("dimensions") or {}).get("customer")) or {}
    gates = cust.get("gates") or {}
    keys = list(gates.keys())
    attention = d.get("attention") or {}
    expected = ["value_ledger", "paid", "goals", "delivered", "capacity", "outcome"]
    ok = (r["status"] == 200 and d.get("success") is True and keys == expected
          and isinstance(attention.get("total"), int))
    body = {"status": r["status"], "success": d.get("success"), "gate_keys": keys,
            "total_gate_count": len(keys), "progress": cust.get("progress"),
            "attention_total": attention.get("total")}
    _card(page, env, "CV2-customer-gates-api.png", "CV2",
          "客户价值 6 项门禁与行动事项", "/api/xcmax/ops/founder-autonomy",
          r["status"], body)
    return body, ok


def case_unauth_customer_denied(page, env):
    r = _unauth(page, env, "/api/xcmax/ops/founder-autonomy",
                name="CV3-unauth-denied.png")
    b = r.get("body") or {}
    ok = r["status"] in (401, 403) and isinstance(b, dict) and b.get("success") is False
    return {"status": r["status"], "body": b}, ok


def case_autonomy_overview(page, env):
    r = _api(page, "/api/xcmax/admin/autonomy/overview")
    d = r.get("body") or {}
    pending = d.get("pending") or {}
    audit = d.get("audit") or {}
    body = {"status": r["status"], "ok": d.get("ok"),
            "pending_count": pending.get("count"),
            "pending_items": len(pending.get("items") or []),
            "audit_items": len(audit.get("items") or [])}
    _card(page, env, "CV4-autonomy-overview.png", "CV4",
          "自治审批总览与只追加审计", "/api/xcmax/admin/autonomy/overview",
          r["status"], body)
    ok = (r["status"] == 200 and d.get("ok") is True
          and body["pending_count"] == body["pending_items"]
          and isinstance(audit.get("items"), list))
    return body, ok


CASES = [
    {"id": "CV1", "title": "「创始人自治驾驶舱」页真实渲染客户状态卡片",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/founder-autonomy，等待 SPA 渲染后读取标题与正文。",
     "expected": "渲染出「客户状态」并含「客户为可验证产出付费」「权威价值账本」「0/6 项证据门槛」。",
     "run": case_customer_card},
    {"id": "CV2", "title": "客户价值 6 项门禁与行动事项真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/xcmax/ops/founder-autonomy。",
     "expected": "200 且 success=true；dimensions[customer] 门禁 key 与 impl 顺序一致（6 项）；attention.total 为整数。",
     "run": case_customer_gates},
    {"id": "CV3", "title": "无会话访问客户价值接口被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 的上下文中 fetch GET /api/xcmax/ops/founder-autonomy。",
     "expected": "被拒绝（401/403），success=false，不返回客户价值数据。",
     "run": case_unauth_customer_denied},
    {"id": "CV4", "title": "自治审批总览与只追加审计真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/xcmax/admin/autonomy/overview。",
     "expected": "200 且 ok=true；pending.count 与 items 长度一致；audit.items 为列表。",
     "run": case_autonomy_overview},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码，可点「登 录」。",
    "CV1-founder-autonomy-customer.png": "「创始人自治驾驶舱」页已滚动到「七项真实进度」区：「客户状态 0% · 能力早期」，副标「客户为可验证产出付费」，缺口「接入可排除测试、内部与退款记录的权威价值账本」，「查看 0/6 项证据门槛」；同屏可见 创始人状态 40%、系统/代码/故障/进化状态 0%（进化 0/7）。",
    "CV2-customer-gates-api.png": "本工具在真实浏览器中渲染的本轮响应：GET /api/xcmax/ops/founder-autonomy → 200；customer 门禁 6 项 value_ledger/paid/goals/delivered/capacity/outcome，progress 0、total_gate_count 6、attention_total 57。",
    "CV3-unauth-denied.png": "无会话的新浏览器上下文停留在管理员登录页，未出现任何客户价值数据。",
    "CV4-autonomy-overview.png": "本轮响应：GET /api/xcmax/admin/autonomy/overview → 200，ok=true，health ok，pending.count=0、items_len=0，audit_items=1，审计样本 decision=config_loaded、risk_level=LOW。",
    "__video__": "本轮真实浏览器会话录像（webm，25.12s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 创始人自治驾驶舱客户状态卡片 → 客户价值门禁接口 → 无会话被拒 → 自治总览。",
}