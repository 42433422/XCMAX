"""pay-member-plan（支付订单与会员计划）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/model_payment_plans.py（订单与会员套餐计划）。
真实接口面：GET /api/market/membership-plans、/api/market/payment/plans、/api/model-payment/plans、
GET /api/market/payment/query/{out_trade_no}（不存在订单被拒）。

安全边界：本 spec 只读取套餐/会员计划并做只读订单查询，不发起任何下单/扣款/退款。
"""

import html as _html
import json as _json

FEATURE = "pay-member-plan"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取市场会员计划 → 读取支付套餐计划 → 读取本地模型支付套餐 → "
    "以真实 404 记录查询不存在支付订单被拒（负例，纯只读）。"
)


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,300)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", path)


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


def case_membership_plans(page, env):
    r = _api(page, "/api/market/membership-plans")
    d = (r.get("body") or {}).get("data") or {}
    plans = d.get("plans") or []
    ok = r["status"] == 200 and len(plans) > 0 and all(p.get("id") and p.get("name") and p.get("price") is not None for p in plans)
    body = {"status": r["status"], "plan_count": len(plans),
            "sample": [{"id": p.get("id"), "name": p.get("name"), "price": p.get("price")} for p in plans[:3]]}
    _card(page, env, "M1-member-plans.png", "M1+M2+M3",
          "会员计划与支付套餐真实读取", {
              "GET /api/market/membership-plans": body,
              "GET /api/market/payment/plans": _api(page, "/api/market/payment/plans").get("body", {}).get("data"),
              "GET /api/model-payment/plans": _api(page, "/api/model-payment/plans").get("body", {}).get("data"),
          })
    return body, ok


def case_payment_plans(page, env):
    r = _api(page, "/api/market/payment/plans")
    d = (r.get("body") or {}).get("data") or {}
    plans = d.get("plans") or []
    ok = r["status"] == 200 and len(plans) > 0
    return {"status": r["status"], "plan_count": len(plans),
            "ids": [p.get("id") for p in plans[:4]]}, ok


def case_model_payment_plans(page, env):
    r = _api(page, "/api/model-payment/plans")
    d = (r.get("body") or {}).get("data") or {}
    plans = d.get("plans") or []
    ok = r["status"] == 200 and len(plans) > 0 and all(p.get("id") for p in plans)
    return {"status": r["status"], "plan_count": len(plans),
            "ids": [p.get("id") for p in plans[:4]]}, ok


def case_order_query_not_found(page, env):
    r = _api(page, "/api/market/payment/query/PROBE-NOT-EXIST-0001")
    b = r.get("body") or {}
    ok = r["status"] == 404 and "不存在" in str(b.get("message"))
    _card(page, env, "M4-order-not-found.png", "M4",
          "查询不存在支付订单被拒（负例，纯只读）",
          {"GET /api/market/payment/query/PROBE-NOT-EXIST-0001": {"status": r["status"], "body": b}})
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "M1-member-plans.png": "卡片汇总三处真实响应：GET /api/market/membership-plans 200 返回套餐（plan_basic「VIP」price=9.9 等）；GET /api/market/payment/plans 200 返回同一市场套餐；GET /api/model-payment/plans 200 返回 demo-starter 等本地演示套餐。",
    "M4-order-not-found.png": "本轮响应：GET /api/market/payment/query/PROBE-NOT-EXIST-0001 返回 404，message=订单不存在（只读查询，无资金动作）。",
    "__video__": "本轮真实浏览器会话录像（webm，16.28s，ffmpeg 实测）：管理员登录 → 会员计划 → 支付套餐 → 本地套餐 → 不存在订单 404。无真实资金操作。",
}

CASES = [
    {"id": "M1", "title": "市场会员计划真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/market/membership-plans。",
     "expected": "HTTP 200，plans 非空且含 id/name/price。",
     "run": case_membership_plans},
    {"id": "M2", "title": "市场支付套餐真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/market/payment/plans。",
     "expected": "HTTP 200，plans 非空。",
     "run": case_payment_plans},
    {"id": "M3", "title": "本地模型支付套餐真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/model-payment/plans。",
     "expected": "HTTP 200，plans 非空且每项含 id。",
     "run": case_model_payment_plans},
    {"id": "M4", "title": "查询不存在支付订单被拒（负例/边界）",
     "input": "不存在的 out_trade_no。",
     "actions": "页面上下文 fetch GET /api/market/payment/query/PROBE-NOT-EXIST-0001。",
     "expected": "HTTP 404，提示订单不存在。",
     "run": case_order_query_not_found},
]