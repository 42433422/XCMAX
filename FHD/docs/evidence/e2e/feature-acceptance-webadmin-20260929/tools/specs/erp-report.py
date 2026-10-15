"""erp-report（价格表 / 报表 / 统计分析）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的报表与统计面。
impl：FHD/app/services/report_service.py、FHD/app/fastapi_routes/reports.py。
真实验证面：经营看板/销售/库存/采购报表真实读取 → 真实导出报表文件（二进制 xlsx）；
并含非法方法/路径被拒（负例）。所有请求均在真实浏览器页面上下文发起。
"""

FEATURE = "erp-report"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端读取经营看板与销售/库存/采购报表 → POST /api/report/export 真实导出报表文件"
    "（页面上下文校验响应为二进制且字节数>0）→ 并含 GET /api/report/export 被 404 拒绝（负例）。"
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


def _binary(page, path, method="POST", body=None):
    return page.evaluate(
        "async ([p,m,b]) => { try { const init={credentials:'include',method:m,headers:{}};"
        " if(b!==null){init.headers['Content-Type']='application/json';init.body=JSON.stringify(b);}"
        " if(m!=='GET'&&m!=='HEAD'){const cm=document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);"
        "   if(cm)init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]);}"
        " const r=await fetch(p,init); const buf=await r.arrayBuffer();"
        " return {status:r.status, bytes:buf.byteLength, ctype:r.headers.get('content-type')||''};"
        " } catch(e){ return {status:0, bytes:0, ctype:String(e)}; } }", [path, method, body])


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


def case_reports(page, env):
    dash = _api(page, "/api/report/dashboard")
    sales = _api(page, "/api/report/sales")
    inv = _api(page, "/api/report/inventory")
    pur = _api(page, "/api/report/purchase")
    dd = (dash.get("body") or {}).get("data") or {}
    sd = (sales.get("body") or {}).get("summary") or {}
    idd = (inv.get("body") or {}).get("summary") or {}
    pdd = (pur.get("body") or {}).get("summary") or {}
    _panel(page, env, "RP1-reports.png",
           "GET /api/report/dashboard · sales · inventory · purchase",
           {"dashboard": {"http": dash["status"], "product_count": dd.get("product_count"),
                          "supplier_count": dd.get("supplier_count"), "monthly_sales": dd.get("monthly_sales"),
                          "monthly_purchases": dd.get("monthly_purchases"), "alerts": dd.get("alerts")},
            "sales": {"http": sales["status"], "summary": sd},
            "inventory": {"http": inv["status"], "summary": idd},
            "purchase": {"http": pur["status"], "summary": pdd}})
    ok = (dash["status"] == 200 and sales["status"] == 200 and inv["status"] == 200
          and pur["status"] == 200 and "product_count" in dd)
    return {"dashboard_http": dash["status"], "product_count": dd.get("product_count"),
            "sales_http": sales["status"], "sales_summary": sd,
            "inventory_http": inv["status"], "purchase_http": pur["status"]}, ok


def case_export(page, env):
    r = _binary(page, "/api/report/export", method="POST", body={"report_type": "inventory"})
    _panel(page, env, "RP2-report-export.png",
           "POST /api/report/export · 真实导出报表文件", r)
    ok = r["status"] == 200 and r["bytes"] > 500
    return {"status": r["status"], "bytes": r["bytes"], "ctype": r["ctype"]}, ok


def case_negative(page, env):
    r = _api(page, "/api/report/export")
    b = r.get("body") or {}
    _panel(page, env, "RP3-report-negative.png",
           "GET /api/report/export 被拒（负例）", r)
    ok = r["status"] == 404
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "RP1", "title": "经营看板与销售/库存/采购报表真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/report/dashboard、/sales、/inventory、/purchase。",
     "expected": "四者均 200；看板含 product_count/monthly_sales/monthly_purchases/alerts。",
     "run": case_reports},
    {"id": "RP2", "title": "真实导出报表文件",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/report/export（页面上下文校验二进制）。",
     "expected": "HTTP 200，响应为二进制文件且字节数>0。",
     "run": case_export},
    {"id": "RP3", "title": "非法方法/路径被拒（负例）",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/report/export。",
     "expected": "404，不返回文件。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "RP1-reports.png": "浏览器渲染经营看板与销售/库存/采购报表真实 JSON（产品数、供应商数、月度销售/采购、预警）。",
    "RP2-report-export.png": "浏览器上下文校验 POST /api/report/export 的真实响应：status=200、二进制字节数与 content-type。",
    "RP3-report-negative.png": "浏览器渲染 GET /api/report/export 的 404 拒绝响应。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 报表读取 → 真实导出 → 负例。",
}