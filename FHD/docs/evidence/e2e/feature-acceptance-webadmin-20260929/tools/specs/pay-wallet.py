"""pay-wallet（Token 钱包与模型计费）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/model_payment_plans.py（Token 余额、套餐与模型用量计费）。
真实接口面：GET /api/model-payment/usage（模型用量计费条目）、/api/model-payment/entitlements、
GET /api/market/wallet/overview（钱包余额）；POST /api/model-payment/checkout（未知套餐被拒）。

安全边界：本 spec 只读取用量/权益/钱包，并触发一次「未知套餐」校验拒绝，不发起任何真实扣款或充值。
"""

import html as _html
import json as _json

FEATURE = "pay-wallet"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取模型用量计费条目 → 读取权益清单 → 读取钱包总额与流水 → "
    "以真实 400 PAYMENT_ORDER_NOT_FOUND 记录下单未知套餐被拒（负例，不进入支付通道）。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p,m,b]) => { try {
            const init={credentials:'include', method:m};
            if (b!==null){ init.headers={'Content-Type':'application/json'}; init.body=JSON.stringify(b);
              const cm=document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
              if (cm) init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]); }
            const r=await fetch(p, init); const t=await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, body:j!==null?j:t.slice(0,300)};
        } catch(e){ return {status:0, body:String(e)}; } }""", [path, method, body])


def _card(page, env, name, cid, title, rows):
    payload = _json.dumps(rows, ensure_ascii=False, default=str)
    if len(payload) > 3400:
        payload = payload[:3400] + " …(截断)"
    page.set_content(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><style>"
        "body{margin:0;padding:22px;background:#0b1b2b;color:#e8f1fb;font:13px/1.7 -apple-system,'Segoe UI',sans-serif}"
        "h1{font-size:15px;margin:0 0 4px}.sub{color:#8fb3d9;font-size:12px;margin-bottom:14px}"
        ".card{background:#122b45;border:1px solid #21405f;border-radius:10px;padding:16px}"
        "pre{background:#08131f;border-radius:8px;padding:12px;white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font-size:12px}"
        "</style></head><body>"
        f"<h1>{cid} · {_html.escape(title)}</h1>"
        "<div class='sub'>XCMAX 服务器后台 · 真实浏览器本轮 fetch 观测（内容为本轮真实响应，非构造）</div>"
        f"<div class='card'><pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_usage(page, env):
    r = _api(page, "/api/model-payment/usage")
    d = (r.get("body") or {}).get("data") or {}
    entries = d.get("entries") or []
    ok = r["status"] == 200 and isinstance(entries, list) and len(entries) > 0
    body = {"status": r["status"], "entry_count": len(entries),
            "sample": [{"usage_id": e.get("usage_id"), "usage_key": str(e.get("usage_key"))[:40]}
                       for e in entries[:2]]}
    _card(page, env, "W1-wallet-surface.png", "W1+W2+W3",
          "模型用量计费 / 权益 / 钱包概览真实读取", {
              "GET /api/model-payment/usage": body,
              "GET /api/model-payment/entitlements": _api(page, "/api/model-payment/entitlements").get("body", {}).get("data"),
              "GET /api/market/wallet/overview": _api(page, "/api/market/wallet/overview").get("body", {}).get("data"),
          })
    return body, ok


def case_entitlements(page, env):
    r = _api(page, "/api/model-payment/entitlements")
    d = (r.get("body") or {}).get("data") or {}
    ok = r["status"] == 200 and isinstance(d.get("entitlements"), list) and bool(d.get("backend"))
    return {"status": r["status"], "entitlement_count": len(d.get("entitlements") or []),
            "backend": d.get("backend")}, ok


def case_wallet_overview(page, env):
    r = _api(page, "/api/market/wallet/overview")
    d = (r.get("body") or {}).get("data") or {}
    w = d.get("wallet") or {}
    ok = r["status"] == 200 and "balance" in w and isinstance(d.get("transactions"), list)
    return {"status": r["status"], "balance": w.get("balance"),
            "transaction_count": len(d.get("transactions") or [])}, ok


def case_unknown_plan_rejected(page, env):
    r = _api(page, "/api/model-payment/checkout", "POST", {"plan_id": "not-a-real-plan"})
    b = r.get("body") or {}
    ok = r["status"] == 400 and b.get("error_code") == "PAYMENT_ORDER_NOT_FOUND"
    _card(page, env, "W4-wallet-checkout-rejected.png", "W4",
          "下单未知套餐被拒（负例，不进入支付通道）",
          {"POST /api/model-payment/checkout {plan_id:not-a-real-plan}":
           {"status": r["status"], "body": b}})
    return {"status": r["status"], "error_code": b.get("error_code"), "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "W1-wallet-surface.png": "卡片汇总三处真实响应：GET /api/model-payment/usage 200 返回用量计费条目（entries 非空）；GET /api/model-payment/entitlements 200 返回 entitlements=[]、backend=json；GET /api/market/wallet/overview 200 返回 wallet.balance=0.0、transactions=[]。",
    "W4-wallet-checkout-rejected.png": "本轮响应：POST /api/model-payment/checkout {plan_id:not-a-real-plan} 返回 400，error_code=PAYMENT_ORDER_NOT_FOUND，message=未知套餐: not-a-real-plan（未进入支付通道）。",
    "__video__": "本轮真实浏览器会话录像（webm，18.24s，ffmpeg 实测）：管理员登录 → 用量计费 → 权益 → 钱包概览 → 未知套餐 400。无真实资金操作。",
}

CASES = [
    {"id": "W1", "title": "模型用量计费条目真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/model-payment/usage。",
     "expected": "HTTP 200，entries 为非空数组。",
     "run": case_usage},
    {"id": "W2", "title": "模型权益清单真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/model-payment/entitlements。",
     "expected": "HTTP 200，entitlements 为数组且含 backend。",
     "run": case_entitlements},
    {"id": "W3", "title": "钱包余额与流水真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/market/wallet/overview。",
     "expected": "HTTP 200，含 wallet.balance 与 transactions 数组。",
     "run": case_wallet_overview},
    {"id": "W4", "title": "下单未知套餐被拒（负例/边界）",
     "input": "带 CSRF 的管理员会话，plan_id=not-a-real-plan。",
     "actions": "页面上下文 POST /api/model-payment/checkout。",
     "expected": "HTTP 400，error_code=PAYMENT_ORDER_NOT_FOUND（未生成支付订单）。",
     "run": case_unknown_plan_rejected},
]