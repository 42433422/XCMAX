"""erp-uom（计量单位管理：多计量单位与换算）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的计量单位面（单位主数据读取 + 下单/发货链路的真实换算与入单）。
impl（实际实现面，已按代码核实）：FHD/app/services/tools_execution/order_parser.py（桶/规格解析）、
FHD/app/infrastructure/documents/shipment_document_generator_impl.py（换算与单据生成）、
FHD/mods/xcagi-erp-domain-bridge/backend/blueprints.py（单位/产品/客户/发货记录读面）。
说明：`FHD/app/services/uom_service.py` 当前在仓库内无调用点（未接线），故本能力以真实运行的
换算链路为准做验收，未把未接线模块当作已验证对象。

本轮实测（真实数据 + 真实换算）：
  * 单位读面：GET /purchase_units 与 /products 列表均 200，产品带计量单位（如「箱」），客户单位名非空；
  * 换算一致性：对话成单「开发货单 客户 <真实客户> 5桶 <真实型号> 规格20」→ 发货记录
    quantity_tins=5、tin_spec=20、quantity_kg=100（5×20=100，桶↔公斤换算一致）；3桶同规格 → kg=60（随量线性）；
  * 换算结果入单：对应发货单文档生成成功（doc_name/file_path 非空且服务端文件真实存在）；
  * 观察项：客户名不存在时对话仍会生成单据（产品按「下单即建客户」处理），如实记录，不作为验收用例。
"""

from pathlib import Path

FEATURE = "erp-uom"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端核验多计量单位与换算：单位读面（/purchase_units、/products 的单位字段）均 200；"
    "对话成单 5桶 规格20 → 发货记录 quantity_tins=5 / tin_spec=20 / quantity_kg=100（换算一致，5×20=100）；"
    "3桶同规格 → quantity_kg=60（随量线性）；对应发货单文档真实生成（服务端文件存在且非空）；"
    "观察项：客户名不存在时仍会生成单据（下单即建客户）。"
)


EXTRA_OBSERVATIONS = [
    "观察项：客户名不存在时（如「不存在的验收客户XYZ」）对话仍返回单据生成成功——产品按「下单即建客户」处理，未做存在性拦截；本轮如实记录，不作为验收用例。",
]


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        "async ([p,m,b]) => { try { const init={credentials:'include',method:m,headers:{}};"
        " if(b!==null){init.headers['Content-Type']='application/json';init.body=JSON.stringify(b);}"
        " if(m!=='GET'&&m!=='HEAD'){const cm=document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);"
        "   if(cm)init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]);}"
        " const r=await fetch(p,init);const t=await r.text();let j=null;try{j=JSON.parse(t);}catch(e){}"
        " return {status:r.status, body:j!==null?j:t.slice(0,240)};"
        " } catch(e){ return {status:0, body:String(e)}; } }", [path, method, body])


def _items(resp):
    data = (resp.get("body") or {}).get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("items") or []
    return []


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


def _context(page):
    units = _api(page, "/api/mod/xcagi-erp-domain-bridge/purchase_units")
    products = _api(page, "/api/mod/xcagi-erp-domain-bridge/products/list")
    customers = _api(page, "/api/mod/xcagi-erp-domain-bridge/customers/list")
    uitems, pitems, citems = _items(units), _items(products), _items(customers)
    return {
        "units": units, "products": products, "customers": customers,
        "unit_items": uitems, "product_items": pitems, "customer_items": citems,
        "unit_name": str((uitems[0].get("unit_name") if uitems else "") or ""),
        "product_unit": str((pitems[0].get("unit") if pitems else "") or ""),
        "model": str((pitems[0].get("model_number") if pitems else "") or ""),
        "customer": str((citems[0].get("customer_name") if citems else "") or ""),
    }


def _last_record(page, model):
    resp = _api(page, "/api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/records")
    rows = [x for x in _items(resp) if str(x.get("model_number") or "") == model]
    latest = max(rows, key=lambda x: int(x.get("id") or 0), default=None)
    return resp, latest


def case_units_read(page, env):
    c = _context(page)
    _panel(page, env, "UOM1-units-read.png",
           "单位读面：客户采购单位清单 + 产品计量单位",
           {"GET /purchase_units": {"status": c["units"]["status"], "count": len(c["unit_items"]),
                                     "first_unit_name": c["unit_name"]},
            "GET /products/list": {"status": c["products"]["status"], "count": len(c["product_items"]),
                                   "first_product_unit": c["product_unit"], "first_model": c["model"]}})
    ok = (c["units"]["status"] == 200 and c["products"]["status"] == 200
          and bool(c["unit_name"]) and bool(c["product_unit"]) and bool(c["model"]))
    return {"units_http": c["units"]["status"], "unit_name": c["unit_name"],
            "products_http": c["products"]["status"], "product_unit": c["product_unit"]}, ok


def case_conversion_consistency(page, env):
    """核心正向：桶 × 每桶规格 = 公斤，真实换算一致。"""
    c = _context(page)
    tins, spec = 5, 20
    message = f"开发货单 客户 {c['customer']} {tins}桶 {c['model']} 规格{spec}"
    chat = _api(page, "/api/mod/xcagi-planner-bridge/chat", method="POST", body={"message": message})
    chat_data = (chat.get("body") or {}).get("data") or {}
    _rec_resp, rec = _last_record(page, c["model"])
    rec = rec or {}
    t = int(rec.get("quantity_tins") or 0)
    s = float(rec.get("tin_spec") or 0)
    kg = float(rec.get("quantity_kg") or 0)
    _panel(page, env, "UOM2-conversion.png",
           "核心正向：桶 ↔ 公斤换算一致（tins × tin_spec = quantity_kg）",
           {"message": message, "chat_http": chat["status"], "action": chat_data.get("action"),
            "record": {"purchase_unit": rec.get("purchase_unit"), "model_number": rec.get("model_number"),
                       "quantity_tins": t, "tin_spec": s, "quantity_kg": kg,
                       "expected_kg": t * s, "consistent": t * s == kg}})
    ok = (chat["status"] == 200 and chat_data.get("action") == "tool_call"
          and t == tins and s == float(spec) and kg == tins * spec)
    return {"action": chat_data.get("action"), "tins": t, "spec": s, "kg": kg, "consistent": t * s == kg}, ok


def case_conversion_scales_with_qty(page, env):
    """换算随量线性：3桶 同规格 → kg=60。"""
    c = _context(page)
    tins, spec = 3, 20
    message = f"开发货单 客户 {c['customer']} {tins}桶 {c['model']} 规格{spec}"
    chat = _api(page, "/api/mod/xcagi-planner-bridge/chat", method="POST", body={"message": message})
    _rec_resp, rec = _last_record(page, c["model"])
    rec = rec or {}
    t = int(rec.get("quantity_tins") or 0)
    kg = float(rec.get("quantity_kg") or 0)
    _panel(page, env, "UOM3-conversion-scales.png",
           "换算随量线性：3桶 × 规格20 = 60 公斤",
           {"message": message, "record_tins": t, "record_kg": kg, "expected_kg": tins * spec})
    ok = t == tins and kg == float(tins * spec)
    return {"tins": t, "kg": kg, "expected_kg": tins * spec}, ok


def case_conversion_into_document(page, env):
    """换算结果入单：发货单文档真实生成（服务端文件存在且非空）。"""
    c = _context(page)
    message = f"开发货单 客户 {c['customer']} 2桶 {c['model']} 规格20"
    chat = _api(page, "/api/mod/xcagi-planner-bridge/chat", method="POST", body={"message": message})
    data = (chat.get("body") or {}).get("data") or {}
    inner = data.get("data") or {}
    doc = inner.get("document") if isinstance(inner, dict) else None
    doc = doc if isinstance(doc, dict) else {}
    file_path = str(doc.get("file_path") or "")
    file_ok = bool(file_path) and Path(file_path).is_file()
    size = Path(file_path).stat().st_size if file_ok else 0
    _panel(page, env, "UOM4-document.png",
           "换算结果入单：发货单文档生成并落地",
           {"message": message, "document": {k: doc.get(k) for k in
                                             ("success", "message", "doc_name", "file_path", "order_number")},
            "server_file_exists": file_ok, "server_file_bytes": size})
    ok = data.get("action") == "tool_call" and doc.get("success") is True and file_ok and size > 0
    return {"doc_success": doc.get("success"), "doc_name": doc.get("doc_name"),
            "file_exists": file_ok, "file_bytes": size}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "UOM1-units-read.png": "卡片显示 GET /purchase_units 200（条数、首个 unit_name）与 GET /products/list 200（条数、首个产品 unit 与 model_number）。",
    "UOM2-conversion.png": "卡片显示成单消息、chat 200/action=tool_call，以及发货记录中 quantity_tins=5、tin_spec=20、quantity_kg=100、expected_kg=100、consistent=true。",
    "UOM3-conversion-scales.png": "卡片显示 3 桶同规格的成单消息与记录值（record_tins=3、record_kg=60、expected_kg=60）。",
    "UOM4-document.png": "卡片显示发货单 document.success=true、doc_name、file_path，以及服务端文件存在与字节数>0。",
    "__video__": "本轮真实浏览器会话录像（webm，ffmpeg 实测 19.64s，1600x1000 VP8/25fps）：管理员登录 → 单位读面 → 5桶换算一致 → 3桶线性换算 → 换算入单生成文档。",
}

CASES = [
    {"id": "UOM1", "title": "单位读面：采购单位清单与产品计量单位",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /purchase_units 与 /products/list。",
     "expected": "均 200；首个客户单位名与产品计量单位、型号均非空。",
     "run": case_units_read},
    {"id": "UOM2", "title": "桶↔公斤换算一致（核心正向）",
     "input": "管理员会话 + 真实客户/型号，5桶 规格20。",
     "actions": "对话成单后读取发货记录并核对 quantity_tins/tin_spec/quantity_kg。",
     "expected": "tins=5、spec=20、kg=100（5×20）。",
     "run": case_conversion_consistency},
    {"id": "UOM3", "title": "换算随量线性（3桶 → 60 公斤）",
     "input": "管理员会话 + 真实客户/型号，3桶 规格20。",
     "actions": "对话成单后读取发货记录。",
     "expected": "tins=3、kg=60。",
     "run": case_conversion_scales_with_qty},
    {"id": "UOM4", "title": "换算结果写入发货单文档",
     "input": "管理员会话 + 真实客户/型号，2桶 规格20。",
     "actions": "对话成单并核验服务端文档文件。",
     "expected": "document.success=true、doc_name 非空、file_path 文件存在且字节数>0。",
     "run": case_conversion_into_document},
]