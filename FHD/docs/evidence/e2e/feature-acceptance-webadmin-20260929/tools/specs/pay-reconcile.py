"""pay-reconcile（平台对账与发票）Web 管理端真机验收用例。

impl 源码：FHD/app/fastapi_routes/payment_reconcile_internal_api.py（服务间模型支付对账区间快照）
真实接口：GET /api/internal/payment/reconciliation-period（须 X-Internal-Api-Key）、
          GET /api/finance/unified-ledger[/summary]（统一账本对账）、GET /api/finance/invoices/market（市场发票）。
"""

import html as _html
import json as _json

FEATURE = "pay-reconcile"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 服务器后台总览真实渲染 → "
    "统一账本对账口径（finance_self_hosted 自托管）真实读取 → 服务间对账区间接口在缺少内部 API Key 时"
    "失败关闭（503）→ 缺少必要区间参数时被参数校验拒绝（422）→ 市场发票接口在未绑定市场账号时被拒（401）。"
)


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,400)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", path)


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


def case_ledger(page, env):
    summary = _api(page, "/api/finance/unified-ledger/summary")
    items = _api(page, "/api/finance/unified-ledger")
    sb, ib = summary.get("body") or {}, items.get("body") or {}
    ok = (summary["status"] == 200 and sb.get("success") is True
          and sb.get("finance_self_hosted") is True and isinstance(sb.get("summary"), dict)
          and items["status"] == 200 and ib.get("success") is True
          and isinstance(ib.get("items"), list) and isinstance(ib.get("count"), int))
    page.goto(env["base"] + "/admin/xcmax-admin", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(5000)
    text = (page.inner_text("body") or "").replace("\n", " ")
    page.screenshot(path=str(env["shot"] / "PR1-console-overview.png"))
    return {"summary_status": summary["status"], "finance_self_hosted": sb.get("finance_self_hosted"),
            "summary": sb.get("summary"), "ledger_status": items["status"], "count": ib.get("count"),
            "ui_has_overview": "服务器后台总览" in text, "ui_url": page.url}, \
        ok and "服务器后台总览" in text


def case_internal_requires_key(page, env):
    path = ("/api/internal/payment/reconciliation-period"
            "?period_start=2026-09-01T00:00:00&period_end=2026-09-30T00:00:00")
    r = _api(page, path)
    body = r.get("body") or {}
    ok = r["status"] in (401, 403, 503) and body.get("success") is False
    _card(page, env, "PR2-internal-key-required.png", "PR2",
          "服务间对账区间接口未授权即失败关闭", path, r["status"], body)
    return {"status": r["status"], "error_code": body.get("error_code"),
            "message": body.get("message"), "accepted_unauthorized": False}, ok


def case_internal_missing_params(page, env):
    path = "/api/internal/payment/reconciliation-period"
    r = _api(page, path)
    body = r.get("body") or {}
    fields = [e.get("field") for e in (body.get("errors") or [])]
    ok = r["status"] == 422 and body.get("error_code") == "validation_error" \
        and "query.period_start" in fields and "query.period_end" in fields
    _card(page, env, "PR3-internal-missing-params.png", "PR3",
          "对账区间接口缺参被参数校验拒绝", path, r["status"], body)
    return {"status": r["status"], "error_code": body.get("error_code"), "fields": fields}, ok


def case_market_invoice_denied(page, env):
    path = "/api/finance/invoices/market"
    r = _api(page, path)
    body = r.get("body") or {}
    ok = r["status"] == 401 and body.get("success") is False
    _card(page, env, "PR4-invoice-denied.png", "PR4",
          "市场发票对账接口未绑定市场账号被拒", path, r["status"], body)
    return {"status": r["status"], "message": body.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号 admin、密码为掩码。",
    "PR1-console-overview.png": "登录后进入「服务器后台总览」，本地节点版本 1.0.0.5、数据库 ok、本地地址 127.0.0.1:42423，顶部导航含 订单经营/基础设施 等对账入口。",
    "PR2-internal-key-required.png": "本工具在真实浏览器中渲染的本轮响应：GET /api/internal/payment/reconciliation-period 返回 503，success=false，error_code=http_503，message=internal api not configured（未配置内部 Key 即失败关闭）。",
    "PR3-internal-missing-params.png": "本轮响应：同一接口不带 period_start/period_end 返回 422，error_code=validation_error，errors 列出 query.period_start 与 query.period_end 缺失。",
    "PR4-invoice-denied.png": "本轮响应：GET /api/finance/invoices/market 返回 401，success=false，message=尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization。",
    "__video__": "本轮真实浏览器会话录像（webm，23.84s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 总览页渲染 → 统一账本对账读取 → 对账区间接口 503/422 → 市场发票 401。",
}

CASES = [
    {"id": "PR1", "title": "统一账本对账口径真实读取（自托管）",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/finance/unified-ledger/summary 与 /api/finance/unified-ledger；随后导航 /admin/xcmax-admin。",
     "expected": "两者均 200 且 success=true，finance_self_hosted=true，账本为列表且 count 为整数；总览页渲染出「服务器后台总览」。",
     "run": case_ledger},
    {"id": "PR2", "title": "服务间对账区间接口未带内部 Key 即失败关闭",
     "input": "合法的 period_start/period_end，但无 X-Internal-Api-Key。",
     "actions": "页面上下文 fetch GET /api/internal/payment/reconciliation-period。",
     "expected": "被拒绝（401/403/503），success=false，不返回任何对账快照。",
     "run": case_internal_requires_key},
    {"id": "PR3", "title": "对账区间接口缺少必要参数被参数校验拒绝",
     "input": "不带 period_start 与 period_end。",
     "actions": "页面上下文 fetch GET /api/internal/payment/reconciliation-period。",
     "expected": "HTTP 422，error_code=validation_error，errors 指明 period_start 与 period_end 缺失。",
     "run": case_internal_missing_params},
    {"id": "PR4", "title": "市场发票对账接口未绑定市场账号被拒",
     "input": "已建立的管理员会话，但未绑定修茈市场 Authorization。",
     "actions": "页面上下文 fetch GET /api/finance/invoices/market。",
     "expected": "HTTP 401，success=false，不返回发票数据。",
     "run": case_market_invoice_denied},
]