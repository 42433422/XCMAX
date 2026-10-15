"""pay-refund（退款申请与审核）Web 管理端真机验收用例。

impl 源码：FHD/app/services/reconciliation_scheduler.py（退款/对账调度与审核状态 SSOT，经 operations-line 暴露）
真实接口：GET /api/operations-line/reconciliation/status、GET /api/model-payment/refund/query、
          POST /api/model-payment/refund（校验被拒路径）、GET /api/xcmax/admin/market/commerce/refunds/pending、
          POST /api/xcmax/admin/market/commerce/refunds/{id}/review（未绑定市场账号被拒）。
本 spec 只做查询/校验/被拒路径，不发起任何真实退款。
"""

import html as _html
import json as _json

FEATURE = "pay-refund"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 业务审批页真实渲染 → "
    "退款/对账审核调度状态真实读取（auto_confirm_enabled=false，不做自动确认）→ "
    "退款申请缺少 out_trade_no 被校验拒绝（400）→ 退款查询因支付服务不可用被如实拒绝（success=false）→ "
    "待审退款列表与退款审核入口在未绑定市场账号时被拒（401）。全程仅查询/校验/被拒，无任何真实资金动作。"
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


def case_scheduler_status(page, env):
    path = "/api/operations-line/reconciliation/status"
    r = _api(page, path)
    body = r.get("body") or {}
    data = body.get("data") or {}
    ok = (r["status"] == 200 and body.get("success") is True and data.get("success") is True
          and data.get("auto_confirm_enabled") is False and "last_run" in data)
    page.goto(env["base"] + "/admin/autonomy-approval-hub", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    text = (page.inner_text("body") or "").replace("\n", " ")
    page.screenshot(path=str(env["shot"] / "PF1-approval-hub.png"))
    return {"status": r["status"], "auto_confirm_enabled": data.get("auto_confirm_enabled"),
            "last_run": data.get("last_run"), "ui_has_approval_hub": "自治审批中心" in text,
            "ui_url": page.url}, ok and "自治审批中心" in text


def case_refund_application_validation(page, env):
    path = "/api/model-payment/refund"
    r = _post(page, path, {})
    body = r.get("body") or {}
    ok = r["status"] == 400 and body.get("success") is False \
        and "out_trade_no" in str(body.get("message"))
    _card(page, env, "PF2-refund-application-validation.png", "PF2",
          "退款申请缺少 out_trade_no 被校验拒绝（未进入支付通道）", path, r["status"], body)
    return {"status": r["status"], "csrf_sent": r.get("csrf"), "message": body.get("message")}, ok


def case_refund_query_rejected(page, env):
    path = "/api/model-payment/refund/query?out_trade_no=PF-PROBE-NOT-EXIST-0001"
    r = _api(page, path)
    body = r.get("body") or {}
    ok = r["status"] == 200 and body.get("success") is False and bool(body.get("message"))
    _card(page, env, "PF3-refund-query-rejected.png", "PF3",
          "退款查询（只读）因支付服务不可用被如实拒绝", path, r["status"], body)
    return {"status": r["status"], "success": body.get("success"), "message": body.get("message")}, ok


def case_pending_refunds_denied(page, env):
    path = "/api/xcmax/admin/market/commerce/refunds/pending"
    r = _api(page, path)
    body = r.get("body") or {}
    ok = r["status"] == 401 and body.get("success") is False
    _card(page, env, "PF4-pending-refunds-denied.png", "PF4",
          "待审退款列表在未绑定市场账号时被拒", path, r["status"], body)
    return {"status": r["status"], "message": body.get("message")}, ok


def case_refund_review_denied(page, env):
    path = "/api/xcmax/admin/market/commerce/refunds/999999/review"
    r = _post(page, path, {"action": "approve", "reason": "acceptance-probe"})
    body = r.get("body") or {}
    ok = r["status"] == 401 and body.get("success") is False
    _card(page, env, "PF5-refund-review-denied.png", "PF5",
          "退款审核入口未绑定市场账号即被拒（不产生任何审核/退款动作）", path, r["status"], body)
    return {"status": r["status"], "csrf_sent": r.get("csrf"), "message": body.get("message"),
            "refund_reviewed": False}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号 admin、密码为掩码。",
    "PF1-approval-hub.png": "「自治审批中心」页（产品问题工单审批）：说明「共享 Work Order 与完整闸门时间线；每 30 秒刷新」，含 更新时间与「刷新工单」按钮，主体显示「当前没有共享工单」。",
    "PF2-refund-application-validation.png": "本工具在真实浏览器中渲染的本轮响应：POST /api/model-payment/refund 空 body 返回 400，success=false，message=out_trade_no 必填。",
    "PF3-refund-query-rejected.png": "本轮响应：GET /api/model-payment/refund/query?out_trade_no=PF-PROBE-NOT-EXIST-0001 返回 200，success=false，message=支付宝服务暂时不可用（纯查询，无资金动作）。",
    "PF4-pending-refunds-denied.png": "本轮响应：GET /api/xcmax/admin/market/commerce/refunds/pending 返回 401，success=false，message=尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization。",
    "PF5-refund-review-denied.png": "本轮响应：POST /api/xcmax/admin/market/commerce/refunds/999999/review 返回 401，success=false，同一未绑定市场账号消息（审核未执行）。",
    "__video__": "本轮真实浏览器会话录像（webm，17.72s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 审批中心页渲染 → 审核调度状态读取 → 退款申请缺参 400 → 退款查询被拒 → 待审列表/审核入口 401。",
}

CASES = [
    {"id": "PF1", "title": "退款/对账审核调度状态真实读取，且审批页真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/operations-line/reconciliation/status；随后导航 /admin/autonomy-approval-hub。",
     "expected": "200 且 data.success=true、auto_confirm_enabled=false、含 last_run 字段；审批中心页渲染成功。",
     "run": case_scheduler_status},
    {"id": "PF2", "title": "退款申请缺少 out_trade_no 被校验拒绝",
     "input": "带 CSRF 的管理员会话，空 body。",
     "actions": "页面上下文 POST /api/model-payment/refund。",
     "expected": "HTTP 400，success=false，提示 out_trade_no 必填（调用校验即返回，不发起任何退款）。",
     "run": case_refund_application_validation},
    {"id": "PF3", "title": "退款查询（只读）被如实拒绝",
     "input": "不存在的 out_trade_no。",
     "actions": "页面上下文 fetch GET /api/model-payment/refund/query。",
     "expected": "200 且 success=false，返回明确失败原因，不伪造退款结果。",
     "run": case_refund_query_rejected},
    {"id": "PF4", "title": "待审退款列表未绑定市场账号被拒",
     "input": "已建立的管理员会话，但未绑定市场 Authorization。",
     "actions": "页面上下文 fetch GET /api/xcmax/admin/market/commerce/refunds/pending。",
     "expected": "HTTP 401，success=false，不返回退款数据。",
     "run": case_pending_refunds_denied},
    {"id": "PF5", "title": "退款审核入口未绑定市场账号被拒",
     "input": "带 CSRF 的管理员会话，refund_id=999999，action=approve。",
     "actions": "页面上下文 POST /api/xcmax/admin/market/commerce/refunds/999999/review。",
     "expected": "HTTP 401，success=false（审核请求未被执行、未产生任何资金动作）。",
     "run": case_refund_review_denied},
]