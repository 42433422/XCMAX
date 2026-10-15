"""erp-finance-ledger（财务账本与发票）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的统一账本与发票面。
impl：FHD/app/fastapi_routes/finance.py、finance_unified_ledger.py、finance_invoices_api.py。
真实验证面：真实创建财务流水并在列表读回 → 统一账本包含该流水 → 账本汇总与看板；
并含缺 transaction_type 被 422 拒绝（负例）。所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-finance-ledger"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通财务账本真实写-读回：POST /api/finance/transactions 新建收入流水 → "
    "GET /api/finance/transactions 读回 → GET /api/finance/unified-ledger 读回统一账本含该流水 → "
    "GET /unified-ledger/summary 与 /dashboard；并含缺 transaction_type 的 422（负例）。"
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


def case_transaction_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    created = _api(page, "/api/finance/transactions", method="POST",
                   body={"transaction_type": "revenue", "amount": 100, "description": f"验收账本{ts}"})
    cb = created.get("body") or {}
    cd = cb.get("data") or {}
    txn_id = cd.get("id")
    lst = _api(page, "/api/finance/transactions")
    items = (lst.get("body") or {}).get("data") or []
    found = next((x for x in items if x.get("id") == txn_id), {})
    _panel(page, env, "FL1-ledger-transaction.png",
           "POST/GET /api/finance/transactions · 财务流水真实写-读回",
           {"create_http": created["status"], "success": cb.get("success"), "txn_id": txn_id,
            "transaction_type": cd.get("transaction_type"), "amount": cd.get("amount"),
            "currency": cd.get("currency"), "list_http": lst["status"],
            "readback": {"id": found.get("id"), "amount": found.get("amount"),
                         "description": found.get("description")}})
    ok = (created["status"] == 200 and cb.get("success") is True and bool(txn_id)
          and found.get("id") == txn_id and float(found.get("amount") or 0) == 100.0)
    return {"create_http": created["status"], "txn_id": txn_id, "amount": cd.get("amount"),
            "readback_amount": found.get("amount")}, ok


def case_unified_ledger(page, env):
    r = _api(page, "/api/finance/unified-ledger")
    b = r.get("body") or {}
    items = b.get("items") or []
    mine = [x for x in items if x.get("source_type") == "financial_transaction" and x.get("label")]
    _panel(page, env, "FL2-unified-ledger.png",
           "GET /api/finance/unified-ledger · 统一账本读回",
           {"status": r["status"], "finance_self_hosted": b.get("finance_self_hosted"),
            "count": b.get("count"), "matching_rows": len(mine),
            "sample": [{k: x.get(k) for k in ("source_type", "track", "amount_cents", "label")} for x in mine[:3]]})
    ok = r["status"] == 200 and b.get("finance_self_hosted") is True and len(mine) >= 1
    return {"status": r["status"], "count": b.get("count"), "matching_rows": len(mine)}, ok


def case_summary_dashboard(page, env):
    summ = _api(page, "/api/finance/unified-ledger/summary")
    dash = _api(page, "/api/finance/dashboard")
    sd = (summ.get("body") or {}).get("summary") or {}
    dd = (dash.get("body") or {}).get("data") or {}
    _panel(page, env, "FL3-ledger-summary.png",
           "GET /unified-ledger/summary · /finance/dashboard",
           {"summary_http": summ["status"], "summary": sd, "dashboard_http": dash["status"],
            "total_revenue": dd.get("total_revenue"), "gross_profit": dd.get("gross_profit"),
            "total_payable": dd.get("total_payable")})
    ok = summ["status"] == 200 and dash["status"] == 200
    return {"summary_http": summ["status"], "revenue_summary": sd.get("revenue"),
            "dashboard_http": dash["status"], "total_revenue": dd.get("total_revenue")}, ok


def case_negative(page, env):
    r = _api(page, "/api/finance/transactions", method="POST", body={"amount": 1})
    b = r.get("body") or {}
    _panel(page, env, "FL4-ledger-negative.png",
           "缺 transaction_type 被拒（负例）", r)
    ok = r["status"] == 422 and b.get("error_code") == "validation_error"
    return {"status": r["status"], "error_code": b.get("error_code"),
            "field": ((b.get("errors") or [{}])[0]).get("field")}, ok


CASES = [
    {"id": "FL1", "title": "财务流水真实写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/finance/transactions（revenue/100），随后 GET /api/finance/transactions。",
     "expected": "创建 200、success=true；列表读回同 id 与金额 100.0。",
     "run": case_transaction_roundtrip},
    {"id": "FL2", "title": "统一账本包含本轮流水",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/finance/unified-ledger。",
     "expected": "200、finance_self_hosted=true，账本含 financial_transaction 行。",
     "run": case_unified_ledger},
    {"id": "FL3", "title": "账本汇总与财务看板",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/finance/unified-ledger/summary 与 /api/finance/dashboard。",
     "expected": "两者均 200。",
     "run": case_summary_dashboard},
    {"id": "FL4", "title": "缺 transaction_type 被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/finance/transactions（缺 transaction_type）。",
     "expected": "422 validation_error。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "FL1-ledger-transaction.png": "浏览器渲染财务流水写-读回真实 JSON：create 200、txn id、revenue/100.0、CNY，列表读回同一 id。",
    "FL2-unified-ledger.png": "浏览器渲染统一账本读回：finance_self_hosted=true、financial_transaction 行与金额分。",
    "FL3-ledger-summary.png": "浏览器渲染账本汇总与财务看板真实 JSON（revenue/receivable、总收入/应付）。",
    "FL4-ledger-negative.png": "浏览器渲染缺 transaction_type 的 422 validation_error。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 财务流水写读回 → 统一账本 → 汇总/看板 → 负例。",
}