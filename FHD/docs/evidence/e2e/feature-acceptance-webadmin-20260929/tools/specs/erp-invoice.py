"""erp-invoice（发票与税务）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的发票税务面。
impl：FHD/app/services/tax_invoice_provider.py、FHD/app/fastapi_routes/finance_invoices_api.py。
真实验证面：税务通道读取 → 真实开具 CRM 发票并在列表读回 → 市场发票列表；
并含缺 market_user_id/opportunity_id 被 400 拒绝（负例）。所有请求在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-invoice"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端读取税务通道（自建 Stub）→ POST /api/finance/invoices/crm/issue 真实开具发票 → "
    "GET /api/finance/invoices/crm 读回发票号与状态（issued）→ GET /api/finance/invoices/market；"
    "并含缺 market_user_id/opportunity_id 的 400（负例）。"
)


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


def case_tax_channel(page, env):
    r = _api(page, "/api/finance/invoices/tax-channel")
    b = r.get("body") or {}
    _panel(page, env, "TI1-tax-channel.png",
           "GET /api/finance/invoices/tax-channel · 税务通道", r)
    ok = r["status"] == 200 and b.get("success") is True and b.get("self_hosted") is True
    return {"status": r["status"], "provider": b.get("provider"), "label": b.get("label"),
            "self_hosted": b.get("self_hosted")}, ok


def case_invoice_issue_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    created = _api(page, "/api/finance/invoices/crm/issue", method="POST",
                   body={"market_user_id": 1, "opportunity_id": 1, "amount": 88})
    cb = created.get("body") or {}
    pipeline = cb.get("pipeline") or {}
    inv = pipeline.get("invoice") or {}
    invoice_id = pipeline.get("crm_invoice_id")
    lst = _api(page, "/api/finance/invoices/crm")
    items = (lst.get("body") or {}).get("items") or []
    found = next((x for x in items if x.get("id") == invoice_id), {})
    _panel(page, env, "TI2-invoice-issue.png",
           "POST /api/finance/invoices/crm/issue · GET crm list · 发票真实开具与读回",
           {"issue_http": created["status"], "success": cb.get("success"), "invoice_id": invoice_id,
            "invoice_no": inv.get("invoice_no"), "list_http": lst["status"], "total": (lst.get("body") or {}).get("total"),
            "readback": {"id": found.get("id"), "invoice_no": found.get("invoice_no"),
                         "status": found.get("status"), "market_user_id": found.get("market_user_id")}})
    ok = (created["status"] == 200 and cb.get("success") is True and bool(invoice_id)
          and found.get("id") == invoice_id and found.get("status") == "issued"
          and bool(found.get("invoice_no")))
    return {"issue_http": created["status"], "invoice_id": invoice_id, "invoice_no": inv.get("invoice_no"),
            "readback_status": found.get("status"), "readback_no": found.get("invoice_no")}, ok


def case_market_invoices(page, env):
    r = _api(page, "/api/finance/invoices/market")
    b = r.get("body") or {}
    _panel(page, env, "TI3-market-invoices.png",
           "GET /api/finance/invoices/market", {"status": r["status"], "ok": b.get("ok"),
                                                "total": b.get("total"), "page": b.get("page")})
    ok = r["status"] == 200
    return {"status": r["status"], "ok": b.get("ok"), "total": b.get("total")}, ok


def case_negative(page, env):
    r = _api(page, "/api/finance/invoices/crm/issue", method="POST", body={})
    b = r.get("body") or {}
    _panel(page, env, "TI4-invoice-negative.png",
           "缺 market_user_id/opportunity_id 被拒（负例）", r)
    ok = r["status"] == 400
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "TI1", "title": "税务通道真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/finance/invoices/tax-channel。",
     "expected": "200、success=true、self_hosted=true，返回 provider 与 label。",
     "run": case_tax_channel},
    {"id": "TI2", "title": "CRM 发票真实开具并读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/finance/invoices/crm/issue（market_user_id/opportunity_id），随后 GET /api/finance/invoices/crm。",
     "expected": "开具 200、success=true、返回发票 id；列表读回同 id、发票号且状态 issued。",
     "run": case_invoice_issue_roundtrip},
    {"id": "TI3", "title": "市场发票列表读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/finance/invoices/market。",
     "expected": "200。",
     "run": case_market_invoices},
    {"id": "TI4", "title": "缺必要凭据被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/finance/invoices/crm/issue（空 body）。",
     "expected": "400「请提供 market_user_id 或 opportunity_id」。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "TI1-tax-channel.png": "浏览器渲染税务通道真实 JSON：provider=stub、self_hosted=true 与 label。",
    "TI2-invoice-issue.png": "浏览器渲染发票开具与读回真实 JSON：issue 200、invoice_id、发票号 INV-...，列表读回状态 issued。",
    "TI3-market-invoices.png": "浏览器渲染市场发票列表接口真实 JSON。",
    "TI4-invoice-negative.png": "浏览器渲染缺凭据开具发票的 400「请提供 market_user_id 或 opportunity_id」。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 税务通道 → 发票开具写读回 → 市场发票 → 负例。",
}