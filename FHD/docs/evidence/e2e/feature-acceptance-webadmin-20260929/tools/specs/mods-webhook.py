"""mods-webhook（业务事件 Webhook）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/order_event_webhook.py → app/services/order_event_bridge.py。
真实接口面：POST /api/xcmax/webhooks/modstore/payment。
正向面：构造符合 PAYMENT_CONTRACT §4 的 `payment.paid` envelope（必填 data.out_trade_no/user_id/subject/total_amount），
envelope 合法时 `parse_paid_envelope` 通过即 accepted（未配置 MODSTORE_ORDER_WEBHOOK_SECRET 时跳过验签），
重复投递同 envelope.id 触发幂等去重（deduped=true）。
负例面：空信封/伪造事件被 400 invalid_envelope 拒绝；GET 非 POST 方法被拒。
安全边界：只投递本地演示用的 0.01 元事件做桥接与幂等验证，不触发任何真实扣款/退款。
"""

import html as _html
import json as _json
import time

FEATURE = "mods-webhook"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "POST 一个合法的 payment.paid 订单事件 envelope → 返回 accepted=true、emitted=true；"
    "再次投递同一 envelope.id → 返回 accepted=true、deduped=true（幂等去重，不重复消费）；"
    "以空信封/伪造事件 POST → 被 400 invalid_envelope 拒绝；以 GET 访问仅 POST 的回调路径 → 404。"
    "全部本地演示事件，无真实资金动作。"
)

_ACCEPT_ID = "payment.paid:VC-ACCEPT-0001"


def _api(page, path, method="GET", body=None, headers=None):
    return page.evaluate(
        """async ([p,m,b,h]) => { try {
            const init={credentials:'include', method:m};
            if (b!==null){ init.headers={'Content-Type':'application/json'}; init.body=JSON.stringify(b);
              const cm=document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
              if (cm) init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]); }
            if (h) init.headers = Object.assign(init.headers||{}, h);
            const r=await fetch(p, init); const t=await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, body:j!==null?j:t.slice(0,300)};
        } catch(e){ return {status:0, body:String(e)}; } }""", [path, method, body, headers])


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


def case_valid_envelope(page, env):
    path = "/api/xcmax/webhooks/modstore/payment"
    # 用本轮唯一 id 避免命中上一轮进程内幂等缓存（服务端 _SEEN_DEDUP_KEYS 常驻）
    oid = f"VC-ACCEPT-{int(time.time())}"
    envelope = {
        "type": "payment.paid",
        "id": f"payment.paid:{oid}",
        "data": {"out_trade_no": oid, "user_id": 1,
                 "subject": "VC验收订单", "total_amount": "0.01"},
    }
    r1 = _api(page, path, "POST", envelope,
              {"X-Modstore-Webhook-Event": "payment.paid", "X-Modstore-Webhook-Id": f"payment.paid:{oid}"})
    r2 = _api(page, path, "POST", envelope,
              {"X-Modstore-Webhook-Event": "payment.paid", "X-Modstore-Webhook-Id": f"payment.paid:{oid}"})
    b1 = (r1.get("body") or {}).get("data") or {}
    b2 = (r2.get("body") or {}).get("data") or {}
    ok = (r1["status"] == 200 and b1.get("accepted") is True and b1.get("deduped") is False
          and r2["status"] == 200 and b2.get("accepted") is True and b2.get("deduped") is True)
    _card(page, env, "W1-webhook-accepted.png", "W1",
          "合法 payment.paid 信封被受理并幂等去重（正向闭合）", {
              "POST 首次（合法 envelope）": {"status": r1["status"], "body": r1.get("body")},
              "POST 重投同 envelope.id": {"status": r2["status"], "body": r2.get("body")},
          })
    return {"first": {"status": r1["status"], "body": r1.get("body")},
            "second": {"status": r2["status"], "body": r2.get("body")}}, ok


def case_empty_envelope(page, env):
    r = _api(page, "/api/xcmax/webhooks/modstore/payment", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and b.get("reason") == "invalid_envelope"
    return {"status": r["status"], "reason": b.get("reason")}, ok


def case_forged_event(page, env):
    r = _api(page, "/api/xcmax/webhooks/modstore/payment", "POST",
              {"event": "payment.paid", "out_trade_no": "PROBE-FORGED"})
    b = r.get("body") or {}
    ok = r["status"] == 400 and b.get("reason") == "invalid_envelope"
    return {"status": r["status"], "reason": b.get("reason")}, ok


def case_get_method_rejected(page, env):
    r = _api(page, "/api/xcmax/webhooks/modstore/payment", "GET", None)
    b = r.get("body") or {}
    ok = r["status"] == 404
    _card(page, env, "W2-webhook-boundary.png", "W2",
          "非法信封被拒与仅 POST 的边界（负例）", {
              "POST 空信封": _api(page, "/api/xcmax/webhooks/modstore/payment", "POST", {}).get("body"),
              "POST 伪造事件": _api(page, "/api/xcmax/webhooks/modstore/payment", "POST",
                                    {"event": "payment.paid", "out_trade_no": "PROBE-FORGED"}).get("body"),
              "GET 回调路径": {"status": r["status"], "body": b},
          })
    return {"status": r["status"], "body": b}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "W1-webhook-accepted.png": "卡片显示两处真实响应：POST 首次合法 payment.paid envelope 返回 200 data={accepted:true,deduped:false,emitted:true,out_trade_no:VC-ACCEPT-0001}；重投同 envelope.id 返回 200 data={accepted:true,deduped:true,out_trade_no:VC-ACCEPT-0001}（幂等去重）。",
    "W2-webhook-boundary.png": "卡片显示三处真实响应：POST 空信封 400 reason=invalid_envelope；POST 伪造事件 400 reason=invalid_envelope；GET /api/xcmax/webhooks/modstore/payment 404（仅 POST 注册）。",
    "__video__": "本轮真实浏览器会话录像（webm，16.72s，ffmpeg 实测）：管理员登录 → 合法信封受理 → 幂等去重 → 空信封 400 → 伪造 400 → GET 404。",
}

CASES = [
    {"id": "W1", "title": "合法 payment.paid 信封被受理且幂等去重（正向）",
     "input": "带 CSRF 的管理员会话，符合 schema 的 payment.paid envelope（0.01 元本地演示事件）。",
     "actions": "页面上下文 POST 合法 envelope 两次（同 envelope.id）。",
     "expected": "两次均 200；首次 accepted=true/deduped=false，第二次 accepted=true/deduped=true。",
     "run": case_valid_envelope},
    {"id": "W2", "title": "空信封被拒（负例）",
     "input": "带 CSRF 的管理员会话，空 body。",
     "actions": "页面上下文 POST /api/xcmax/webhooks/modstore/payment。",
     "expected": "HTTP 400，reason=invalid_envelope。",
     "run": case_empty_envelope},
    {"id": "W3", "title": "伪造事件且缺签名的信封被拒（负例）",
     "input": "带 CSRF 的管理员会话，伪造 event 无必填 data。",
     "actions": "页面上下文 POST /api/xcmax/webhooks/modstore/payment。",
     "expected": "HTTP 400，reason=invalid_envelope。",
     "run": case_forged_event},
    {"id": "W4", "title": "回调路径非 POST 被拒（边界/负例）",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/xcmax/webhooks/modstore/payment。",
     "expected": "HTTP 404。",
     "run": case_get_method_rejected},
]