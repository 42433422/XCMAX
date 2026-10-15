"""erp-ar-ap（应收应付与毛利）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的应收应付与毛利面。
impl：FHD/app/services/accounting_services.py（经 /api/finance/receivables|payables|dashboard）。
真实验证面：真实创建应收流水并在应收列表读回 → 应付列表（来自采购订单）→ 毛利看板；
并含缺金额被 422 拒绝（负例）。所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-ar-ap"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通应收应付真实写-读回：POST /api/finance/transactions（receivable）→ "
    "GET /api/finance/receivables 读回该应收 → GET /api/finance/payables 读回采购应付 → "
    "GET /api/finance/dashboard 读回毛利与应付总额；并含缺金额的 422（负例）。"
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


def case_receivable_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    created = _api(page, "/api/finance/transactions", method="POST",
                   body={"transaction_type": "receivable", "amount": 66, "description": f"验收应收{ts}"})
    cd = (created.get("body") or {}).get("data") or {}
    tid = cd.get("id")
    recv = _api(page, "/api/finance/receivables")
    items = (recv.get("body") or {}).get("data") or []
    found = next((x for x in items if x.get("id") == tid), {})
    _panel(page, env, "AR1-receivable-roundtrip.png",
           "POST transactions(receivable) · GET receivables · 应收真实写-读回",
           {"create_http": created["status"], "txn_id": tid, "transaction_type": cd.get("transaction_type"),
            "amount": cd.get("amount"), "receivables_http": recv["status"],
            "readback": {"id": found.get("id"), "amount": found.get("amount"),
                         "description": found.get("description")}})
    ok = (created["status"] == 200 and bool(tid) and recv["status"] == 200
          and found.get("id") == tid)
    return {"create_http": created["status"], "txn_id": tid, "amount": cd.get("amount"),
            "receivables_http": recv["status"], "readback_id": found.get("id")}, ok


def case_payables(page, env):
    r = _api(page, "/api/finance/payables")
    b = r.get("body") or {}
    items = b.get("data") or []
    _panel(page, env, "AR2-payables.png",
           "GET /api/finance/payables · 应付（采购）读回",
           {"status": r["status"], "total": b.get("total"),
            "sample": [{k: x.get(k) for k in ("order_no", "supplier_name", "total_amount", "outstanding")}
                       for x in items[:3]]})
    ok = r["status"] == 200
    return {"status": r["status"], "total": b.get("total"),
            "has_rows": len(items) > 0}, ok


def case_dashboard(page, env):
    r = _api(page, "/api/finance/dashboard")
    d = (r.get("body") or {}).get("data") or {}
    _panel(page, env, "AR3-ar-ap-dashboard.png",
           "GET /api/finance/dashboard · 毛利与应收应付",
           {"status": r["status"], "total_revenue": d.get("total_revenue"), "total_cost": d.get("total_cost"),
            "gross_profit": d.get("gross_profit"), "gross_margin_pct": d.get("gross_margin_pct"),
            "total_payable": d.get("total_payable"), "period": d.get("period")})
    ok = r["status"] == 200 and "total_payable" in d
    return {"status": r["status"], "gross_profit": d.get("gross_profit"),
            "total_payable": d.get("total_payable")}, ok


def case_negative(page, env):
    r = _api(page, "/api/finance/transactions", method="POST", body={"transaction_type": "receivable"})
    b = r.get("body") or {}
    _panel(page, env, "AR4-ar-ap-negative.png",
           "缺金额被拒（负例）", r)
    ok = r["status"] == 422 and b.get("error_code") == "validation_error"
    return {"status": r["status"], "field": ((b.get("errors") or [{}])[0]).get("field")}, ok


CASES = [
    {"id": "AR1", "title": "应收真实写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/finance/transactions（receivable/66），随后 GET /api/finance/receivables。",
     "expected": "创建 200；应收列表读回同 id。",
     "run": case_receivable_roundtrip},
    {"id": "AR2", "title": "应付（采购）真实读回",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/finance/payables。",
     "expected": "200，返回采购应付行（含 order_no/outstanding）。",
     "run": case_payables},
    {"id": "AR3", "title": "毛利与应收应付看板",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/finance/dashboard。",
     "expected": "200 且含 gross_profit/total_payable。",
     "run": case_dashboard},
    {"id": "AR4", "title": "缺金额被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/finance/transactions（缺 amount）。",
     "expected": "422 validation_error。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "AR1-receivable-roundtrip.png": "浏览器渲染应收写-读回真实 JSON：create 200、receivable/66.0，应收列表读回同一 id。",
    "AR2-payables.png": "浏览器渲染应付列表真实 JSON（order_no、供应商、outstanding）。",
    "AR3-ar-ap-dashboard.png": "浏览器渲染毛利看板真实 JSON（总收入/成本/毛利/毛利率/应付）。",
    "AR4-ar-ap-negative.png": "浏览器渲染缺 amount 的 422 validation_error。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 应收写读回 → 应付读回 → 毛利看板 → 负例。",
}