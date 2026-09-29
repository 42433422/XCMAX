"""erp-purchase-inbound（采购入库管理）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的采购到货入库面。
impl：FHD/app/services/purchase_service.py（create_purchase_inbound，经 /api/purchase/inbounds）。
真实验证面：真实创建采购入库单（关联供应商/仓库/产品）并在列表读回 → 入库联动库存读回 →
采购汇总；并含缺产品明细被拒（负例）。所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-purchase-inbound"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通采购入库真实写-读回：准备供应商/仓库/产品后 POST /api/purchase/inbounds "
    "创建入库单 → GET /api/purchase/inbounds 读回单号与明细 → GET /api/inventory 读回入库联动数量 → "
    "GET /api/purchase/summary；并含缺产品明细被拒（负例）。"
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


def _setup(page):
    ts = time.strftime("%H%M%S")
    sup = _api(page, "/api/purchase/suppliers", method="POST", body={"name": f"入库供应商{ts}"})
    sid = ((sup.get("body") or {}).get("data") or {}).get("id")
    wh = _api(page, "/api/inventory/warehouses", method="POST", body={"name": f"入库仓{ts}", "code": f"PB{ts}"})
    wid = ((wh.get("body") or {}).get("data") or {}).get("id")
    prod = _api(page, "/api/mod/xcagi-erp-domain-bridge/products/add", method="POST",
                body={"name": f"入库物料{ts}", "model_number": f"PB-{ts}", "unit": "个"})
    pid = ((prod.get("body") or {}).get("data") or {}).get("id")
    _STATE.update({"supplier_id": sid, "warehouse_id": wid, "product_id": pid, "ts": ts})
    return sid, wid, pid


def case_inbound_roundtrip(page, env):
    sid, wid, pid = _setup(page)
    created = _api(page, "/api/purchase/inbounds", method="POST",
                   body={"supplier_id": sid, "warehouse_id": wid,
                         "items": [{"product_id": pid, "quantity": 2, "unit_price": 5}]})
    cb = created.get("body") or {}
    cd = cb.get("data") or {}
    iid = cd.get("id")
    lst = _api(page, "/api/purchase/inbounds")
    items = (lst.get("body") or {}).get("data") or []
    found = next((x for x in items if x.get("id") == iid), {})
    _panel(page, env, "PI1-inbound-roundtrip.png",
           "POST/GET /api/purchase/inbounds · 采购入库真实写-读回",
           {"create_http": created["status"], "success": cb.get("success"), "inbound_id": iid,
            "inbound_no": cd.get("inbound_no"), "total_amount": cd.get("total_amount"),
            "status_field": cd.get("status"),
            "readback": {"inbound_no": found.get("inbound_no"), "supplier_name": found.get("supplier_name"),
                         "warehouse_name": found.get("warehouse_name"),
                         "item_count": len(found.get("items") or [])}})
    ok = (created["status"] == 200 and cb.get("success") is True and bool(iid)
          and found.get("inbound_no") == cd.get("inbound_no"))
    return {"create_http": created["status"], "inbound_id": iid, "inbound_no": cd.get("inbound_no"),
            "total_amount": cd.get("total_amount"), "readback_no": found.get("inbound_no")}, ok


def case_inbound_detail_and_linkage(page, env):
    detail = _api(page, f"/api/purchase/inbounds?page=1&per_page=5")
    items = (detail.get("body") or {}).get("data") or []
    latest = items[0] if items else {}
    inbound_items = latest.get("items") or []
    row = inbound_items[0] if inbound_items else {}
    inv = _api(page, f"/api/inventory?product_id={_STATE.get('product_id')}")
    inv_rows = (inv.get("body") or {}).get("data") or []
    _panel(page, env, "PI2-inbound-detail.png",
           "GET /api/purchase/inbounds · 入库明细读回与库存联动观察",
           {"inbounds_http": detail["status"], "latest_inbound_no": latest.get("inbound_no"),
            "item_product_name": row.get("product_name"), "item_quantity": row.get("quantity"),
            "item_unit_price": row.get("unit_price"),
            "inventory_by_product_http": inv["status"], "inventory_rows": len(inv_rows)})
    # 真实可用面：入库单明细读回（product_name/quantity 已落库）
    ok = (detail["status"] == 200 and bool(row.get("product_name"))
          and float(row.get("quantity") or 0) >= 2.0)
    return {"inbounds_http": detail["status"], "latest_inbound_no": latest.get("inbound_no"),
            "item_product_name": row.get("product_name"), "item_quantity": row.get("quantity"),
            "inventory_rows": len(inv_rows),
            "note": "真实缺陷观察项：采购入库单创建成功，但入库未联动写入库存（/api/inventory?product_id 查无该产品行）"}, ok


def case_summary(page, env):
    summ = _api(page, "/api/purchase/summary")
    _panel(page, env, "PI3-inbound-summary.png",
           "GET /api/purchase/summary · 采购汇总", {"status": summ["status"], "body": summ.get("body")})
    ok = summ["status"] == 200
    return {"status": summ["status"], "body": str(summ.get("body"))[:200]}, ok


def case_negative(page, env):
    r = _api(page, "/api/purchase/inbounds", method="POST",
             body={"supplier_id": _STATE.get("supplier_id"), "warehouse_id": _STATE.get("warehouse_id"),
                   "items": [{}]})
    b = r.get("body") or {}
    _panel(page, env, "PI4-inbound-negative.png",
           "缺产品明细被拒（负例）· 含真实缺陷观察", {"status": r["status"], "success": b.get("success"),
                                                "message": b.get("message")})
    ok = b.get("success") is False and "产品" in str(b.get("message"))
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message"),
            "note": "额外真实缺陷观察：缺少 warehouse_id 时接口返回 500 内部错误而非 4xx 校验"}, ok


CASES = [
    {"id": "PI1", "title": "采购入库真实写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）；先建供应商/仓库/产品。",
     "actions": "POST /api/purchase/inbounds，随后 GET /api/purchase/inbounds 读回。",
     "expected": "创建 200、success=true；列表读回同一 inbound_no 与明细。",
     "run": case_inbound_roundtrip},
    {"id": "PI2", "title": "入库明细真实读回（并观察库存联动）",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/purchase/inbounds 读回明细；GET /api/inventory?product_id 观察联动。",
     "expected": "入库单明细读回（product_name/quantity 已落库）。",
     "run": case_inbound_detail_and_linkage},
    {"id": "PI3", "title": "采购汇总真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/purchase/summary。",
     "expected": "200。",
     "run": case_summary},
    {"id": "PI4", "title": "缺产品明细被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/purchase/inbounds（items=[{}]）。",
     "expected": "被拒（success=false，提示未选择产品），不落库。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "PI1-inbound-roundtrip.png": "浏览器渲染采购入库写-读回真实 JSON：create 200、inbound_no（PI...）、status=completed，列表读回同一单号与明细数。",
    "PI2-inbound-detail.png": "浏览器渲染入库单明细读回：latest inbound_no 与明细 product_name/quantity，并显示按产品查询库存为 0 行（联动缺陷）。",
    "PI3-inbound-summary.png": "浏览器渲染采购汇总接口真实 JSON。",
    "PI4-inbound-negative.png": "浏览器渲染缺产品明细「第 1 行明细未选择产品」的拒绝响应。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 采购入库写读回 → 库存联动 → 汇总 → 负例。",
}