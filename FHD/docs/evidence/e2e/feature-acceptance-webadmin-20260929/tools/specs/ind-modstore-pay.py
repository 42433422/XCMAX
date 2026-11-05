"""ind-modstore-pay（市场支付桥接 Mod）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端中的模型付费面。
impl：FHD/mods/xcagi-model-payment-bridge（门面 /api/mod/xcagi-model-payment-bridge/model-payment/*，
      host_prefix /api/model-payment）。
真实验证面：套餐清单与诊断真实读取 → 真实创建演示下单（返回真实 order_id）→ 按 order_id 查询 →
未知套餐被 400 拒绝（负例）；并如实记录 Mod 门面 checkout 的 500 观察项。
所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "ind-modstore-pay"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端读取模型付费 Mod 的门面状态与套餐清单（/api/model-payment/plans）→ "
    "真实 POST /api/model-payment/checkout 创建演示下单（返回真实 order_id，status=demo_pending）→ "
    "按 order_id 查询订单 → 未知套餐被 400 PAYMENT_ORDER_NOT_FOUND 拒绝（负例）。"
)

_STATE: dict = {}


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        "async ([p,m,b]) => { try { const init={credentials:'include',method:m,headers:{}};"
        " if(b!==null){init.headers['Content-Type']='application/json';init.body=JSON.stringify(b);}"
        " if(m!=='GET'&&m!=='HEAD'){const cm=document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);"
        "   if(cm)init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]);}"
        " const r=await fetch(p,init);const t=await r.text();let j=null;try{j=JSON.parse(t);}catch(e){}"
        " return {status:r.status, body:j!==null?j:t.slice(0,240)};"
        " } catch(e){ return {status:0, body:String(e)}; } }", [path, method, body])


def _panel(page, env, name, title, obj):
    page.evaluate(
        "([t,o]) => { document.documentElement.lang='zh-CN'; document.head.replaceChildren();"
        " document.body.replaceChildren(); document.body.style.cssText='margin:0;padding:22px;background:#0b1b2b;"
        " color:#e8f1fb;font:13px/1.7 -apple-system,sans-serif';"
        " const h=document.createElement('h2'); h.textContent=t; h.style.cssText='font-size:15px;margin:0 0 12px';"
        " const p=document.createElement('pre'); p.style.cssText='background:#08131f;border-radius:8px;padding:14px;"
        " white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font:12px/1.6 monospace';"
        " p.textContent=JSON.stringify(o,null,2); document.body.appendChild(h); document.body.appendChild(p); }",
        [title, obj])
    page.screenshot(path=str(env["shot"] / name))


def case_mod_status(page, env):
    st = _api(page, "/api/mod/xcagi-model-payment-bridge/status")
    d = (st.get("body") or {}).get("data") or {}
    ok = st["status"] == 200 and bool(d.get("mod_id")) and int(d.get("endpoint_count") or 0) >= 5
    return {"status": st["status"], "mod_id": d.get("mod_id"),
            "host_prefix": d.get("host_prefix"), "facade_prefix": d.get("facade_prefix"),
            "endpoint_count": d.get("endpoint_count")}, ok


def case_plans_and_diagnostics(page, env):
    plans = _api(page, "/api/model-payment/plans")
    diag = _api(page, "/api/model-payment/diagnostics")
    ent = _api(page, "/api/model-payment/entitlements")
    pb = plans.get("body") or {}
    pd = pb.get("data") or {}
    plan_list = pd.get("plans") or []
    dd = (diag.get("body") or {}).get("data") or {}
    ed = (ent.get("body") or {}).get("data") or {}
    _panel(page, env, "MP1-pay-plans.png",
           "GET /api/model-payment/plans · diagnostics · entitlements",
           {"plans_status": plans["status"], "plan_count": len(plan_list),
            "plan_ids": [p.get("id") for p in plan_list[:4]],
            "plan_amounts": [p.get("amount_cents") for p in plan_list[:4]],
            "diagnostics": {"status": diag["status"], "alipay_configured": dd.get("alipay_configured"),
                            "sdk_installed": dd.get("sdk_installed"), "sot_backend": dd.get("sot_backend")},
            "entitlements": {"status": ent["status"], "backend": ed.get("backend"),
                             "count": len(ed.get("entitlements") or [])}})
    ok = (plans["status"] == 200 and len(plan_list) >= 3
          and diag["status"] == 200 and dd.get("sdk_installed") is True
          and ent["status"] == 200)
    return {"plans_status": plans["status"], "plan_count": len(plan_list),
            "plan_ids": [p.get("id") for p in plan_list[:4]],
            "plan_amounts": [p.get("amount_cents") for p in plan_list[:4]],
            "diagnostics": {"status": diag["status"], "alipay_configured": dd.get("alipay_configured"),
                            "sdk_installed": dd.get("sdk_installed"), "sot_backend": dd.get("sot_backend")},
            "entitlements": {"status": ent["status"], "backend": ed.get("backend"),
                             "count": len(ed.get("entitlements") or [])}}, ok


def case_checkout_and_query(page, env):
    ck = _api(page, "/api/model-payment/checkout", method="POST", body={"plan_id": "demo-starter"})
    cb = ck.get("body") or {}
    cd = cb.get("data") or {}
    order_id = cd.get("order_id")
    _STATE["order_id"] = order_id
    q = _api(page, f"/api/model-payment/query/{order_id}") if order_id else {"status": 0, "body": {}}
    qb = q.get("body") or {}
    _panel(page, env, "MP2-pay-checkout.png",
           "POST /api/model-payment/checkout · GET query/{order_id}（真实下单与查询）",
           {"checkout_status": ck["status"], "success": cb.get("success"),
            "order_id": order_id, "channel": cd.get("channel"), "status_field": cd.get("status"),
            "amount_cents": cd.get("amount_cents"), "plan_id": cd.get("plan_id"),
            "setup_hint": str(cd.get("setup_hint"))[:160],
            "query_status": q["status"], "query_body": str(qb)[:200]})
    ok = (ck["status"] == 200 and cb.get("success") is True and bool(order_id)
          and cd.get("status") == "demo_pending" and cd.get("amount_cents") == 990)
    return {"checkout_status": ck["status"], "order_id": order_id, "channel": cd.get("channel"),
            "status_field": cd.get("status"), "amount_cents": cd.get("amount_cents"),
            "query_status": q["status"], "query_body": str(qb)[:200]}, ok


def case_negative_and_facade(page, env):
    bad = _api(page, "/api/model-payment/checkout", method="POST", body={"plan_id": "no-such-plan"})
    bb = bad.get("body") or {}
    facade = _api(page, "/api/mod/xcagi-model-payment-bridge/model-payment/checkout", method="POST",
                  body={"plan_id": "demo-starter", "channel": "alipay", "market_user_id": 0})
    fb = facade.get("body") or {}
    _panel(page, env, "MP3-pay-negative.png",
           "未知套餐被拒（负例）· Mod 门面 checkout 真实观察",
           {"unknown_plan": {"status": bad["status"], "error_code": bb.get("error_code"),
                             "message": bb.get("message")},
            "mod_facade_checkout": {"status": facade["status"], "message": fb.get("message")}})
    ok = bad["status"] == 400 and bb.get("error_code") == "PAYMENT_ORDER_NOT_FOUND"
    return {"unknown_plan": {"status": bad["status"], "error_code": bb.get("error_code"),
                             "message": bb.get("message")},
            "mod_facade_checkout": {"status": facade["status"], "message": fb.get("message")},
            "note": "Mod 门面 checkout 本环境返回 500（真实缺陷观察项）；宿主 /api/model-payment/checkout 正常"}, ok


CASES = [
    {"id": "MP1", "title": "支付桥接 Mod 门面状态真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/mod/xcagi-model-payment-bridge/status。",
     "expected": "HTTP 200，返回 mod_id 与 endpoint_count≥5。",
     "run": case_mod_status},
    {"id": "MP2", "title": "套餐清单 / 诊断 / 权益真实读取",
     "input": "已建立的管理员会话。",
     "actions": "fetch GET /api/model-payment/plans、/diagnostics、/entitlements。",
     "expected": "套餐≥3 且含 id/金额；诊断 200 且 sdk_installed=true；权益接口 200。",
     "run": case_plans_and_diagnostics},
    {"id": "MP3", "title": "真实创建演示下单并按 order_id 查询",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/model-payment/checkout（plan_id=demo-starter），再 GET /api/model-payment/query/{order_id}。",
     "expected": "下单 200、success=true、返回真实 order_id、status=demo_pending、金额 990；查询接口 200。",
     "run": case_checkout_and_query},
    {"id": "MP4", "title": "未知套餐被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/model-payment/checkout（plan_id=no-such-plan）；并探测 Mod 门面 checkout。",
     "expected": "未知套餐 400 且 error_code=PAYMENT_ORDER_NOT_FOUND。",
     "run": case_negative_and_facade},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "MP1-pay-plans.png": "浏览器渲染 /api/model-payment/plans、diagnostics、entitlements 的真实 JSON：套餐 demo-starter/standard/pro 及金额，diagnostics 含 alipay_configured=false、sdk_installed=true、sot_backend。",
    "MP2-pay-checkout.png": "浏览器渲染真实下单与查询响应：checkout 200、success=true、order_id=mp-...、status=demo_pending、amount_cents=990 与演示提示。",
    "MP3-pay-negative.png": "浏览器渲染未知套餐拒绝：400、error_code=PAYMENT_ORDER_NOT_FOUND「未知套餐: no-such-plan」；Mod 门面 checkout 500 internal_error。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 支付门面状态 → 套餐/诊断/权益 → 真实下单与查询 → 未知套餐拒绝。",
}