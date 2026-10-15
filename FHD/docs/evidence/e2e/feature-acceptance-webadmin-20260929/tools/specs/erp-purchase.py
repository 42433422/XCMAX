"""erp-purchase（采购管理）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端中的采购域。
impl：FHD/app/fastapi_routes/purchase.py（/api/purchase/*，租户安全）。
真实验证面：真实新建供应商并在列表读回 → 真实创建采购订单（关联产品）并在列表读回 →
汇总读取；并含缺名称供应商与缺产品明细被拒（负例）。所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-purchase"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通采购域真实写-读回：POST /api/purchase/suppliers 新建供应商 → "
    "GET /api/purchase/suppliers 列表读回（含真实 code）→（经 mod 域门面建产品后）"
    "POST /api/purchase/orders 新建采购订单 → GET /api/purchase/orders 读回订单号与明细金额 → "
    "GET /api/purchase/summary 汇总；并含缺名称供应商与缺产品明细被拒（负例）。"
)

_STATE: dict = {}


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


def case_supplier_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    name = f"验收供应商{ts}"
    created = _api(page, "/api/purchase/suppliers", method="POST",
                   body={"name": name, "contact_person": "李四", "contact_phone": "13900000000"})
    cd = (created.get("body") or {}).get("data") or {}
    sid = cd.get("id")
    _STATE["supplier_id"] = sid
    lst = _api(page, "/api/purchase/suppliers")
    items = (lst.get("body") or {}).get("data") or []
    names = [x.get("name") for x in items]
    _panel(page, env, "PU1-supplier-roundtrip.png",
           "POST/GET /api/purchase/suppliers · 供应商真实写-读回",
           {"create_http": created["status"], "supplier_id": sid, "code": cd.get("code"),
            "tenant_id": cd.get("tenant_id"), "list_http": lst["status"], "count": len(items),
            "created_name_in_list": name in names, "list_sample": names[:3]})
    ok = (created["status"] == 200 and bool(sid) and lst["status"] == 200 and name in names)
    return {"create_http": created["status"], "supplier_id": sid, "code": cd.get("code"),
            "list_http": lst["status"], "created_name_in_list": name in names}, ok


def case_purchase_order_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    prod = _api(page, "/api/mod/xcagi-erp-domain-bridge/products/add", method="POST",
                body={"name": f"采购物料{ts}", "model_number": f"PU-{ts}", "unit_price": 10, "unit": "个"})
    pid = ((prod.get("body") or {}).get("data") or {}).get("id")
    created = _api(page, "/api/purchase/orders", method="POST",
                   body={"supplier_id": _STATE.get("supplier_id"), "remark": "vc",
                         "items": [{"product_id": pid, "quantity": 2, "unit_price": 10}]})
    cb = created.get("body") or {}
    cd = cb.get("data") or {}
    oid = cd.get("id")
    lst = _api(page, "/api/purchase/orders")
    items = (lst.get("body") or {}).get("data") or []
    found = next((x for x in items if x.get("id") == oid), {})
    _panel(page, env, "PU2-purchase-order.png",
           "POST/GET /api/purchase/orders · 采购订单真实写-读回",
           {"product_id": pid, "create_http": created["status"], "success": cb.get("success"),
            "order_id": oid, "order_no": cd.get("order_no"), "total_amount": cd.get("total_amount"),
            "status_field": cd.get("status"),
            "readback": {"order_no": found.get("order_no"), "supplier_name": found.get("supplier_name"),
                         "total_amount": found.get("total_amount"),
                         "item_count": len(found.get("items") or [])}})
    ok = (created["status"] == 200 and cb.get("success") is True and bool(oid)
          and found.get("order_no") == cd.get("order_no") and float(found.get("total_amount") or 0) == 20.0)
    return {"create_http": created["status"], "order_id": oid, "order_no": cd.get("order_no"),
            "total_amount": cd.get("total_amount"), "readback_total": found.get("total_amount"),
            "item_count": len(found.get("items") or [])}, ok


def case_summary(page, env):
    summ = _api(page, "/api/purchase/summary")
    sup = _api(page, "/api/purchase/suppliers/summary")
    _panel(page, env, "PU3-purchase-summary.png",
           "GET /api/purchase/summary · /suppliers/summary",
           {"summary_http": summ["status"], "summary": summ.get("body"),
            "supplier_summary_http": sup["status"], "supplier_summary": sup.get("body")})
    ok = summ["status"] == 200 and sup["status"] == 200
    return {"summary_http": summ["status"], "summary": str(summ.get("body"))[:200],
            "supplier_summary_http": sup["status"]}, ok


def case_negative(page, env):
    no_name = _api(page, "/api/purchase/suppliers", method="POST", body={})
    no_product = _api(page, "/api/purchase/orders", method="POST",
                      body={"supplier_id": _STATE.get("supplier_id"), "items": [{}]})
    nn = no_name.get("body") or {}
    npb = no_product.get("body") or {}
    _panel(page, env, "PU4-purchase-negative.png",
           "缺名称供应商 / 缺产品明细被拒（负例）",
           {"supplier_without_name": {"status": no_name["status"], "success": nn.get("success"),
                                      "message": nn.get("message")},
            "order_without_product": {"status": no_product["status"], "success": npb.get("success"),
                                      "message": npb.get("message")}})
    ok = (no_name["status"] == 200 and nn.get("success") is False
          and no_product["status"] == 200 and npb.get("success") is False)
    return {"supplier_without_name": {"success": nn.get("success"), "message": nn.get("message")},
            "order_without_product": {"success": npb.get("success"), "message": npb.get("message")}}, ok


CASES = [
    {"id": "PU1", "title": "供应商真实写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/purchase/suppliers 新建，随后 GET /api/purchase/suppliers 读回。",
     "expected": "创建 200 返回真实 id/code；列表中能读到本轮新建的供应商名称。",
     "run": case_supplier_roundtrip},
    {"id": "PU2", "title": "采购订单真实写-读回（含明细与金额）",
     "input": "已建立的管理员会话；先经 mod 域门面建一个产品。",
     "actions": "POST /api/purchase/orders（关联供应商与产品），随后 GET /api/purchase/orders 读回。",
     "expected": "创建 200、success=true；列表读回同一 order_no、金额 20.0 且含明细。",
     "run": case_purchase_order_roundtrip},
    {"id": "PU3", "title": "采购汇总真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/purchase/summary 与 /api/purchase/suppliers/summary。",
     "expected": "两者均 200。",
     "run": case_summary},
    {"id": "PU4", "title": "缺名称供应商 / 缺产品明细被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/purchase/suppliers（空 body）；POST /api/purchase/orders（items=[{}]）。",
     "expected": "均被拒（success=false，含明确校验提示），不发生落库。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "PU1-supplier-roundtrip.png": "浏览器渲染供应商写-读回真实 JSON：create 200、供应商 id/code（SUP...）、列表命中新建名称。",
    "PU2-purchase-order.png": "浏览器渲染采购订单写-读回真实 JSON：create 200、order_no（PO...）、total_amount=20.0，列表读回同一 order_no 与明细数。",
    "PU3-purchase-summary.png": "浏览器渲染采购汇总接口的真实 JSON。",
    "PU4-purchase-negative.png": "浏览器渲染缺名称供应商「供应商名称不能为空」与缺产品明细「第 1 行明细未选择产品」的拒绝响应。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 供应商写读回 → 采购订单写读回 → 汇总 → 负例。",
}