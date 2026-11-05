"""pay-alipay（支付宝支付与回调）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/model_payment.py、infrastructure/payment/alipay.py、order_store.py。
真实接口面：GET /api/model-payment/diagnostics（支付通道配置侦察）、/api/model-payment/plans、
POST /api/model-payment/notify/alipay（异步回调签名校验）、GET /api/model-payment/query/{out_trade_no}。

安全边界：本 spec 只做配置侦察、套餐读取、回调校验与只读查询，不发起任何真实扣款/退款/下单。
"""

import html as _html
import json as _json

FEATURE = "pay-alipay"
ENTRY = "/admin/login"
# 部分验证：配置侦察/套餐/回调拒绝/只读查询为真实；alipay_configured=false（无商户密钥），真实扣款与回调成功受理未验证。
EXTRA_OBSERVATIONS = [
    "部分验证：GET /api/model-payment/diagnostics 真实返回 alipay_configured=false、sdk_installed=true（无商户密钥）；"
    "配置侦察、套餐目录、无签名回调被拒(400)、只读订单查询被拒均为真实。"
    "真实扣款/退款与合法签名回调的成功受理因无支付宝商户凭据，本轮未验证；全程未触发任何资金动作。",
]
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取支付宝通道配置侦察（alipay_configured=false、sdk_installed=true、密钥源 missing）→ 读取套餐目录 → "
    "以真实 400 记录无签名的异步回调被拒 → 以真实 success=false 记录不存在订单的只读查询被如实拒绝。"
    "全程无任何真实资金动作。"
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


def case_diagnostics(page, env):
    r = _api(page, "/api/model-payment/diagnostics")
    b = r.get("body") or {}
    d = b.get("data") or {}
    ok = (r["status"] == 200 and d.get("alipay_configured") is False
          and d.get("sdk_installed") is True
          and d.get("notify_url_path_expected") == "/api/model-payment/notify/alipay")
    body = {"status": r["status"], "alipay_configured": d.get("alipay_configured"),
            "sdk_installed": d.get("sdk_installed"), "private_key_source": d.get("private_key_source"),
            "public_key_source": d.get("public_key_source"),
            "notify_url_path_expected": d.get("notify_url_path_expected"),
            "sot_backend": d.get("sot_backend")}
    _card(page, env, "P1-alipay-diagnostics.png", "P1+P2",
          "支付宝通道配置侦察与套餐目录真实读取", {
              "GET /api/model-payment/diagnostics": body,
              "GET /api/model-payment/plans": _api(page, "/api/model-payment/plans").get("body", {}).get("data"),
          })
    return body, ok


def case_plans(page, env):
    r = _api(page, "/api/model-payment/plans")
    d = (r.get("body") or {}).get("data") or {}
    plans = d.get("plans") or []
    ok = r["status"] == 200 and len(plans) > 0 and all(p.get("id") and p.get("amount_cents") is not None for p in plans)
    return {"status": r["status"], "plan_count": len(plans),
            "sample": [{"id": p.get("id"), "amount_cents": p.get("amount_cents")} for p in plans[:3]]}, ok


def case_notify_rejected(page, env):
    r = _api(page, "/api/model-payment/notify/alipay", "POST", {})
    ok = r["status"] == 400 and "fail" in str(r.get("body")).lower()
    return {"status": r["status"], "body": r.get("body")}, ok


def case_query_rejected(page, env):
    r = _api(page, "/api/model-payment/query/PROBE-NOT-EXIST-0001")
    b = r.get("body") or {}
    notify = _api(page, "/api/model-payment/notify/alipay", "POST", {})
    ok = r["status"] == 200 and b.get("success") is False and bool(b.get("message"))
    _card(page, env, "P3-alipay-negative.png", "P3+P4",
          "无签名回调被拒与不存在订单只读查询被拒（负例，无资金动作）", {
              "POST /api/model-payment/notify/alipay {}": {"status": notify["status"], "body": notify.get("body")},
              "GET /api/model-payment/query/PROBE-NOT-EXIST-0001": {"status": r["status"], "body": b},
          })
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "P1-alipay-diagnostics.png": "卡片汇总两处真实响应：GET /api/model-payment/diagnostics 200 返回 alipay_configured=false、sdk_installed=true、private/public_key_source=missing、notify_url_path_expected=/api/model-payment/notify/alipay、sot_backend=json；GET /api/model-payment/plans 200 返回 demo-starter 等本地演示套餐。",
    "P3-alipay-negative.png": "卡片显示两处真实响应：POST /api/model-payment/notify/alipay 空 body 返回 400（响应体 fail，无有效签名的异步回调被拒）；GET /api/model-payment/query/PROBE-NOT-EXIST-0001 返回 200 success=false message=支付宝服务暂时不可用（纯只读查询，无资金动作）。",
    "__video__": "本轮真实浏览器会话录像（webm，14.88s，ffmpeg 实测）：管理员登录 → 支付宝配置侦察 → 套餐目录 → 回调 400 → 只读查询被拒。全程无真实资金操作。",
}

CASES = [
    {"id": "P1", "title": "支付宝通道配置侦察真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/model-payment/diagnostics。",
     "expected": "HTTP 200，alipay_configured=false，sdk_installed=true，回调路径与产品一致。",
     "run": case_diagnostics},
    {"id": "P2", "title": "套餐目录真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/model-payment/plans。",
     "expected": "HTTP 200，plans 非空且含 id 与金额。",
     "run": case_plans},
    {"id": "P3", "title": "无签名的支付宝异步回调被拒（负例）",
     "input": "带 CSRF 的管理员会话，空 body。",
     "actions": "页面上下文 POST /api/model-payment/notify/alipay。",
     "expected": "HTTP 400（回调未受理）。",
     "run": case_notify_rejected},
    {"id": "P4", "title": "不存在订单的只读查询被如实拒绝（负例）",
     "input": "不存在的 out_trade_no。",
     "actions": "页面上下文 fetch GET /api/model-payment/query/PROBE-NOT-EXIST-0001。",
     "expected": "HTTP 200 且 success=false，返回明确失败原因。",
     "run": case_query_rejected},
]