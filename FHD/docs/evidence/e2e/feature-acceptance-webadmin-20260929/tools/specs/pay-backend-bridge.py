"""pay-backend-bridge（支付后端桥接 json / postgres / modstore）Web 管理端真机验收用例。

impl 源码：FHD/app/infrastructure/payment/payment_sot.py（按 MODEL_PAYMENT_BACKEND 选择支付 SOT 后端）
真实接口：GET /api/model-payment/diagnostics、GET /api/model-payment/plans、
          POST /api/model-payment/checkout（被拒路径）、POST /api/xcmax/webhooks/modstore/payment（被拒路径）、
          GET /api/market/status（modstore 分支连通性）。
"""

import html as _html
import json as _json

FEATURE = "pay-backend-bridge"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 服务器功能模块页真实渲染出模型支付模块 → "
    "模型支付只读诊断报告当前 SOT 后端 json 与订单存储路径 → 套餐接口回传后端路由标志（market/postgres 均为 false）→ "
    "未知套餐下单被拒（400）→ MODstore 支付 webhook 桥接拒绝非法事件（400）→ modstore 分支在不可达时显式 502。"
)


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,400)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", path)


def _post(page, path, body):
    return page.evaluate(
        "async ([p, b]) => {"
        " const m = document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);"
        " const csrf = m ? decodeURIComponent(m[1]) : '';"
        " try { const r = await fetch(p, {method:'POST', credentials:'include',"
        "  headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body: JSON.stringify(b)});"
        "  const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        "  return {status:r.status, csrf:!!csrf, body: j!==null?j:t.slice(0,400)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", [path, body])


def _card(page, env, name, cid, title, path, status, body):
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
        f"<div class='kv'><span class='k'>请求</span>{_html.escape(path)}</div>"
        f"<div class='kv'><span class='k'>HTTP 状态</span>{status}</div>"
        f"<pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_diagnostics(page, env):
    r = _api(page, "/api/model-payment/diagnostics")
    data = ((r.get("body") or {}).get("data")) or {}
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and data.get("sot_backend") == "json" and bool(data.get("store_path"))
          and data.get("notify_url_path_expected") == "/api/model-payment/notify/alipay")
    page.goto(env["base"] + "/admin/server-functions", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    text = (page.inner_text("body") or "").replace("\n", " ")
    page.screenshot(path=str(env["shot"] / "PB1-server-functions.png"))
    return {"status": r["status"], "sot_backend": data.get("sot_backend"),
            "store_path": data.get("store_path"), "alipay_configured": data.get("alipay_configured"),
            "ui_has_model_payment_module": "model-payment" in text, "ui_url": page.url}, \
        ok and "model-payment" in text


def case_plans_route_flags(page, env):
    r = _api(page, "/api/model-payment/plans")
    data = ((r.get("body") or {}).get("data")) or {}
    integ = data.get("integration") or {}
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and integ.get("backend") == "json" and integ.get("market_sot") is False
          and integ.get("postgres_sot") is False and len(data.get("plans") or []) > 0)
    _card(page, env, "PB2-plans-route-flags.png", "PB2",
          "套餐接口回传支付后端路由标志（json / postgres / market）",
          "/api/model-payment/plans", r["status"], {"integration": integ,
                                                    "plan_ids": [p.get("id") for p in (data.get("plans") or [])]})
    return {"status": r["status"], "integration": integ,
            "plan_count": len(data.get("plans") or [])}, ok


def case_checkout_unknown_plan(page, env):
    path = "/api/model-payment/checkout"
    r = _post(page, path, {"plan_id": "__no_such_plan__"})
    body = r.get("body") or {}
    ok = r["status"] == 400 and body.get("success") is False \
        and body.get("error_code") == "PAYMENT_ORDER_NOT_FOUND"
    _card(page, env, "PB3-checkout-unknown-plan.png", "PB3",
          "未知套餐下单被拒（未进入任何支付通道）", path, r["status"], body)
    return {"status": r["status"], "csrf_sent": r.get("csrf"), "error_code": body.get("error_code"),
            "message": body.get("message")}, ok


def case_webhook_rejects_bad_event(page, env):
    path = "/api/xcmax/webhooks/modstore/payment"
    r = _post(page, path, {"type": "not.a.paid.event", "data": {}})
    body = r.get("body") or {}
    ok = r["status"] == 400 and body.get("success") is False \
        and body.get("reason") == "invalid_envelope"
    _card(page, env, "PB4-webhook-invalid-envelope.png", "PB4",
          "MODstore 支付 webhook 桥接拒绝非法事件", path, r["status"], body)
    return {"status": r["status"], "reason": body.get("reason")}, ok


def case_modstore_branch_unreachable(page, env):
    path = "/api/market/status"
    r = _api(page, path)
    body = r.get("body") or {}
    err = body.get("error") or {}
    ok = r["status"] in (502, 503) and body.get("success") is False \
        and err.get("code") == "MARKET_AUTH_UNAVAILABLE"
    _card(page, env, "PB5-modstore-unreachable.png", "PB5",
          "modstore 支付分支不可达时显式失败（不静默降级）", path, r["status"], body)
    return {"status": r["status"], "error_code": err.get("code"),
            "market_base_url": (body.get("data") or {}).get("market_base_url")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号 admin、密码为掩码。",
    "PB1-server-functions.png": "「服务器功能模块」页：说明「对接修茈服务器的模块注册、每日摘要记录和员工大会能力。」，含 服务器模块/每日摘要记录/员工大会 分页；下方「服务器功能注册表 90 个模块」表内可见 model-payment（模型服务，系统内置，路由 /model-payment，启用）。",
    "PB2-plans-route-flags.png": "本工具在真实浏览器中渲染的本轮响应：GET /api/model-payment/plans 返回 200，success=true，integration={alipay_configured:false, market_sot:false, postgres_sot:false, backend:'json'}，含 demo-* 与 saas-* 套餐。",
    "PB3-checkout-unknown-plan.png": "本轮响应：POST /api/model-payment/checkout {plan_id:'__no_such_plan__'} 返回 400，success=false，error_code=PAYMENT_ORDER_NOT_FOUND，message=未知套餐: __no_such_plan__。",
    "PB4-webhook-invalid-envelope.png": "本轮响应：POST /api/xcmax/webhooks/modstore/payment 送 type=not.a.paid.event 返回 400，success=false，reason=invalid_envelope。",
    "PB5-modstore-unreachable.png": "本轮响应：GET /api/market/status 返回 502，success=false，error.code=MARKET_AUTH_UNAVAILABLE，data.market_base_url=http://127.0.0.1:8765。",
    "__video__": "本轮真实浏览器会话录像（webm，17.64s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 服务器功能模块页（含 model-payment 模块行）→ 诊断/套餐路由标志读取 → 未知套餐 400 → webhook 非法事件 400 → modstore 502。",
}

CASES = [
    {"id": "PB1", "title": "模型支付 SOT 后端可只读诊断，且功能模块页真实登记该模块",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/model-payment/diagnostics；随后导航 /admin/server-functions 读取模块注册表。",
     "expected": "诊断 200 且 sot_backend=json、store_path 非空、notify 路径与本产品一致；功能页出现 model-payment 模块。",
     "run": case_diagnostics},
    {"id": "PB2", "title": "套餐接口回传支付后端路由标志",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/model-payment/plans。",
     "expected": "200 且 integration.backend=json、market_sot=false、postgres_sot=false，套餐列表非空。",
     "run": case_plans_route_flags},
    {"id": "PB3", "title": "未知套餐下单被拒（不触发任何真实扣款）",
     "input": "带 CSRF 的管理员会话，plan_id=__no_such_plan__。",
     "actions": "页面上下文 POST /api/model-payment/checkout。",
     "expected": "HTTP 400，success=false，error_code=PAYMENT_ORDER_NOT_FOUND。",
     "run": case_checkout_unknown_plan},
    {"id": "PB4", "title": "MODstore 支付 webhook 桥接拒绝非法事件",
     "input": "带 CSRF 的管理员会话，body 为非法事件 type。",
     "actions": "页面上下文 POST /api/xcmax/webhooks/modstore/payment。",
     "expected": "HTTP 400，success=false，reason=invalid_envelope（桥接层不落任何订单）。",
     "run": case_webhook_rejects_bad_event},
    {"id": "PB5", "title": "modstore 支付分支不可达时显式失败",
     "input": "已建立的管理员会话，未启动修茈市场服务。",
     "actions": "页面上下文 fetch GET /api/market/status。",
     "expected": "502/503 且 error.code=MARKET_AUTH_UNAVAILABLE，明确暴露不可达而非静默降级。",
     "run": case_modstore_branch_unreachable},
]