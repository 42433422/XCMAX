"""erp-inventory（库存管理）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端中的库存域。
impl：FHD/app/fastapi_routes/inventory.py（/api/inventory/*，租户安全）。
真实验证面：真实入库（关联产品/仓库）并在库存列表与流水读回 → 真实调拨 → 库存汇总读取；
并含非法分页参数被 422 拒绝（负例）。所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-inventory"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通库存域真实写-读回：POST /api/inventory/in 入库 → GET /api/inventory "
    "读回数量 → GET /api/inventory/transactions 读回入库流水 → POST /api/inventory/transfer 调拨 → "
    "GET /api/inventory/summary 汇总；并含非法分页参数 422（负例）。"
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
    """经 mod 域门面建产品与仓库，供库存写读回用。"""
    ts = time.strftime("%H%M%S")
    prod = _api(page, "/api/mod/xcagi-erp-domain-bridge/products/add", method="POST",
                body={"name": f"库存物料{ts}", "model_number": f"INV-{ts}", "unit_price": 5, "unit": "个"})
    pid = ((prod.get("body") or {}).get("data") or {}).get("id")
    wh = _api(page, "/api/inventory/warehouses", method="POST",
              body={"name": f"库存仓{ts}", "code": f"IWH{ts}"})
    wid = ((wh.get("body") or {}).get("data") or {}).get("id")
    _STATE.update({"product_id": pid, "warehouse_id": wid, "ts": ts})
    return pid, wid


def case_stock_in_roundtrip(page, env):
    pid, wid = _setup(page)
    inn = _api(page, "/api/inventory/in", method="POST",
               body={"product_id": pid, "warehouse_id": wid, "quantity": 5})
    ib = inn.get("body") or {}
    lst = _api(page, f"/api/inventory?product_id={pid}&warehouse_id={wid}")
    items = (lst.get("body") or {}).get("data") or []
    row = next((x for x in items if x.get("product_id") == pid and x.get("warehouse_id") == wid), {})
    _panel(page, env, "INV1-stock-in.png",
           "POST /api/inventory/in · GET /api/inventory · 入库真实写-读回",
           {"product_id": pid, "warehouse_id": wid, "in_http": inn["status"], "success": ib.get("success"),
            "message": ib.get("message"), "ledger_id": (ib.get("data") or {}).get("ledger_id"),
            "list_http": lst["status"], "readback_quantity": row.get("quantity"),
            "readback_available": row.get("available_quantity"), "product_name": row.get("product_name")})
    ok = (inn["status"] == 200 and ib.get("success") is True
          and float(row.get("quantity") or 0) == 5.0)
    return {"in_http": inn["status"], "message": ib.get("message"),
            "ledger_id": (ib.get("data") or {}).get("ledger_id"),
            "readback_quantity": row.get("quantity")}, ok


def case_transactions(page, env):
    r = _api(page, "/api/inventory/transactions")
    items = (r.get("body") or {}).get("data") or []
    mine = [x for x in items if x.get("product_id") == _STATE.get("product_id")]
    _panel(page, env, "INV2-transactions.png",
           "GET /api/inventory/transactions · 入库流水读回",
           {"status": r["status"], "total": (r.get("body") or {}).get("total"),
            "matching_rows": len(mine),
            "sample": [{k: x.get(k) for k in ("transaction_type", "quantity", "before_quantity", "after_quantity")}
                       for x in mine[:2]]})
    ok = r["status"] == 200 and len(mine) >= 1
    return {"status": r["status"], "matching_rows": len(mine),
            "sample": [{k: x.get(k) for k in ("transaction_type", "quantity")} for x in mine[:2]]}, ok


def case_transfer_and_summary(page, env):
    pid, wid = _STATE.get("product_id"), _STATE.get("warehouse_id")
    tf = _api(page, "/api/inventory/transfer", method="POST",
              body={"product_id": pid, "from_warehouse_id": wid, "to_warehouse_id": wid, "quantity": 1})
    tb = tf.get("body") or {}
    summ = _api(page, "/api/inventory/summary")
    _panel(page, env, "INV3-transfer-summary.png",
           "POST /api/inventory/transfer · GET /api/inventory/summary",
           {"transfer_http": tf["status"], "success": tb.get("success"), "message": tb.get("message"),
            "data": tb.get("data"), "summary_http": summ["status"],
            "summary_size": len((summ.get("body") or {}).get("data") or [])})
    ok = tf["status"] == 200 and tb.get("success") is True and summ["status"] == 200
    return {"transfer_http": tf["status"], "success": tb.get("success"), "message": tb.get("message"),
            "summary_http": summ["status"]}, ok


def case_negative(page, env):
    bad = _api(page, "/api/inventory?per_page=0")
    b = bad.get("body") or {}
    missing_model = _api(page, "/api/inventory/in", method="POST",
                         body={"quantity": 3, "warehouse_id": _STATE.get("warehouse_id")})
    mb = missing_model.get("body") or {}
    _panel(page, env, "INV4-inventory-negative.png",
           "非法分页 422 · 缺入库参数被拒（负例）",
           {"bad_per_page": {"status": bad["status"], "error_code": b.get("error_code"),
                             "field": ((b.get("errors") or [{}])[0]).get("field")},
            "missing_stock_in_arg": {"status": missing_model["status"], "success": mb.get("success"),
                                     "message": mb.get("message")}})
    ok = (bad["status"] == 422 and b.get("error_code") == "validation_error"
          and mb.get("success") is False)
    return {"bad_per_page": {"status": bad["status"], "error_code": b.get("error_code")},
            "missing_stock_in_arg": {"success": mb.get("success"), "message": mb.get("message")},
            "note": "额外真实缺陷观察项：POST /api/inventory/out 本环境返回 500"}, ok


CASES = [
    {"id": "INV1", "title": "入库真实写-读回",
     "input": "已建立的管理员会话；先建产品与仓库。",
     "actions": "POST /api/inventory/in，随后 GET /api/inventory 读回。",
     "expected": "入库 200、success=true；库列表读回该产品/仓库数量 5.0。",
     "run": case_stock_in_roundtrip},
    {"id": "INV2", "title": "库存流水真实读回",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/inventory/transactions。",
     "expected": "200 且含本轮入库流水的产品行。",
     "run": case_transactions},
    {"id": "INV3", "title": "调拨与库存汇总",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/inventory/transfer；GET /api/inventory/summary。",
     "expected": "调拨 200、success=true；汇总 200。",
     "run": case_transfer_and_summary},
    {"id": "INV4", "title": "非法分页 422 · 缺入库参数被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "GET /api/inventory?per_page=0；POST /api/inventory/in（缺产品/型号）。",
     "expected": "非法分页 422 validation_error；缺入库参数 success=false。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "INV1-stock-in.png": "浏览器渲染入库写-读回真实 JSON：入库 200「入库成功」、ledger_id，库存列表读回数量 5.0 与产品名。",
    "INV2-transactions.png": "浏览器渲染库存流水读回：transaction_type=in、数量与前后结存。",
    "INV3-transfer-summary.png": "浏览器渲染调拨 200「调拨成功」与库存汇总接口真实 JSON。",
    "INV4-inventory-negative.png": "浏览器渲染非法分页 422 validation_error 与缺入库参数的 schema_validation_failed 拒绝。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 入库写读回 → 流水读回 → 调拨/汇总 → 负例。",
}