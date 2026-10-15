"""erp-sales-order（销售订单/发货单管理）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的订单面（租户安全 mod 域门面 + 计划器对话成单）。
impl：FHD/app/services/tools_execution/order_parser.py（订单文本解析）、
FHD/app/infrastructure/documents/shipment_document_generator_impl.py（发货单文档生成）、
FHD/mods/xcagi-erp-domain-bridge/backend/blueprints.py（订单/客户/产品/发货记录读面）。

本轮实测（正向闭环，customer 与 model 取自本租户真实数据）：
  * GET 订单清单与下一单号（mod 域门面）→ 200，单号形如 26-09-00001A；
  * GET 客户清单 / 产品清单 → 200（租户隔离读面）；
  * 计划器对话「开发货单 客户 <真实客户> 5桶 <真实型号> 规格20」→ action=tool_call，
    发货单文档生成成功（doc_name=发货单_<单号>_<时间>.xlsx、服务端文件真实存在且非空）；
  * 读回：发货记录清单含新建记录（purchase_unit 命中该客户）；
  * 负例：旧 /api/orders、/api/shipment/orders 按设计 fail-closed（403 租户隔离未就绪）。

修复说明：此前同一话术被解析成客户「开」（「开发货单」只剥「发货单」残留动词），
已修复并通过 tests/test_services/test_order_parser.py 回归用例；本 spec 用真实客户验证修复后的完整链路。
"""

import time
from pathlib import Path

FEATURE = "erp-sales-order"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端完成销售订单/发货单链路实测：读取订单清单与下一单号（200，26-09-00001A）→ "
    "读取本租户真实客户与产品 → 计划器对话「开发货单 客户 <真实客户> 5桶 <真实型号> 规格20」返回 action=tool_call "
    "且发货单文档生成成功（doc_name/file_path 非空，服务端文件真实存在且非空）→ 发货记录清单读回该单 "
    "（purchase_unit 命中）→ 旧 /api/orders 与 /api/shipment/orders 按设计 fail-closed 403。"
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


def case_orders_read(page, env):
    orders = _api(page, "/api/mod/xcagi-erp-domain-bridge/orders")
    nxt = _api(page, "/api/mod/xcagi-erp-domain-bridge/orders/next_number")
    nd = (nxt.get("body") or {}).get("data") or {}
    _panel(page, env, "SO1-orders-read.png",
           "GET 租户安全订单清单 / 下一单号",
           {"orders_http": orders["status"], "orders_count": len(_items(orders)),
            "next_number_http": nxt["status"], "next_order_number": nd.get("order_number"),
            "sequence": nd.get("sequence"), "year_month": nd.get("year_month")})
    ok = orders["status"] == 200 and nxt["status"] == 200 and bool(nd.get("order_number"))
    return {"orders_http": orders["status"], "orders_count": len(_items(orders)),
            "next_order_number": nd.get("order_number"), "sequence": nd.get("sequence")}, ok


def case_master_data(page, env):
    cust = _api(page, "/api/mod/xcagi-erp-domain-bridge/customers/list")
    prod = _api(page, "/api/mod/xcagi-erp-domain-bridge/products/list")
    customers, products = _items(cust), _items(prod)
    name = str((customers[0].get("customer_name") if customers else "") or "")
    model = str((products[0].get("model_number") if products else "") or "")
    _panel(page, env, "SO2-master-data.png",
           "本租户真实客户与产品（租户隔离读面）",
           {"customers_http": cust["status"], "customers": len(customers), "picked_customer": name,
            "products_http": prod["status"], "products": len(products), "picked_model": model})
    ok = cust["status"] == 200 and prod["status"] == 200 and bool(name) and bool(model)
    return {"customers_http": cust["status"], "customers": len(customers), "customer": name,
            "products_http": prod["status"], "products": len(products), "model": model}, ok


def case_planner_generate_document(page, env):
    """核心正向：对话成单 → 发货单文档真实生成（含服务端文件落地校验）。"""
    cust = _api(page, "/api/mod/xcagi-erp-domain-bridge/customers/list")
    prod = _api(page, "/api/mod/xcagi-erp-domain-bridge/products/list")
    customers, products = _items(cust), _items(prod)
    name = str((customers[0].get("customer_name") if customers else "") or "")
    model = str((products[0].get("model_number") if products else "") or "")
    qty, spec = 5, 20
    message = f"开发货单 客户 {name} {qty}桶 {model} 规格{spec}"
    chat = _api(page, "/api/mod/xcagi-planner-bridge/chat", method="POST", body={"message": message})
    body = chat.get("body") or {}
    data = body.get("data") or {}
    inner = data.get("data") or {}
    doc = inner.get("document") if isinstance(inner, dict) else None
    doc = doc if isinstance(doc, dict) else {}
    file_path = str(doc.get("file_path") or "")
    file_ok = False
    file_bytes = 0
    if file_path:
        p = Path(file_path)
        file_ok = p.is_file()
        file_bytes = p.stat().st_size if file_ok else 0
    _panel(page, env, "SO3-planner-generate.png",
           "核心正向：对话成单 → 发货单文档生成（服务端文件落地校验）",
           {"message": message, "chat_http": chat["status"], "action": data.get("action"),
            "text": str(data.get("text"))[:80],
            "document": {k: doc.get(k) for k in
                         ("success", "message", "doc_name", "file_path", "order_number")},
            "server_file_exists": file_ok, "server_file_bytes": file_bytes})
    ok = (chat["status"] == 200 and data.get("action") == "tool_call"
          and doc.get("success") is True and bool(doc.get("doc_name")) and file_ok and file_bytes > 0)
    return {"message": message, "action": data.get("action"), "doc_success": doc.get("success"),
            "doc_name": doc.get("doc_name"), "order_number": doc.get("order_number"),
            "file_exists": file_ok, "file_bytes": file_bytes}, ok


def case_records_readback(page, env):
    """读回：发货记录清单含本轮新建记录（purchase_unit 命中真实客户）。"""
    cust = _api(page, "/api/mod/xcagi-erp-domain-bridge/customers/list")
    customers = _items(cust)
    name = str((customers[0].get("customer_name") if customers else "") or "")
    prod = _api(page, "/api/mod/xcagi-erp-domain-bridge/products/list")
    products = _items(prod)
    model = str((products[0].get("model_number") if products else "") or "")
    before = _api(page, "/api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/records")
    before_items = _items(before)
    message = f"开发货单 客户 {name} 3桶 {model} 规格20"
    chat = _api(page, "/api/mod/xcagi-planner-bridge/chat", method="POST", body={"message": message})
    after = _api(page, "/api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/records")
    after_items = _items(after)
    matched = [x for x in after_items if str(x.get("purchase_unit") or "") == name]
    _panel(page, env, "SO4-records-readback.png",
           "读回：发货记录清单含新建记录（purchase_unit 命中）",
           {"records_http": after["status"], "records_before": len(before_items), "records_after": len(after_items),
            "chat_http": chat["status"], "matched_records": len(matched),
            "latest_record": (matched[-1] if matched else None)})
    ok = (after["status"] == 200 and len(after_items) > len(before_items) and bool(matched))
    return {"records_before": len(before_items), "records_after": len(after_items),
            "matched_records": len(matched)}, ok


def case_legacy_fail_closed(page, env):
    legacy_orders = _api(page, "/api/orders", method="POST",
                         body={"unit_name": "验收客户", "products": [{"name": "验收产品", "quantity": 1}]})
    legacy_shipment_read = _api(page, "/api/shipment/orders")
    legacy_shipment_post = _api(page, "/api/shipment/orders", method="POST",
                                body={"unit_name": "验收客户", "products": [{"name": "验收产品", "quantity": 1}]})
    ob = legacy_orders.get("body") or {}
    sb = legacy_shipment_read.get("body") or {}
    _panel(page, env, "SO5-legacy-fail-closed.png",
           "负例：旧业务接口按设计 fail-closed（租户隔离未就绪）",
           {"POST /api/orders": {"status": legacy_orders["status"], "body": ob},
            "GET /api/shipment/orders": {"status": legacy_shipment_read["status"], "body": sb},
            "POST /api/shipment/orders（旧路由无写面）": {"status": legacy_shipment_post["status"],
                                                          "body": legacy_shipment_post.get("body")}})
    ok = (legacy_orders["status"] == 403 and legacy_shipment_read["status"] == 403
          and legacy_shipment_post["status"] == 405
          and "租户数据隔离" in str(ob.get("detail") or ob.get("message")))
    return {"orders_post_status": legacy_orders["status"],
            "shipment_get_status": legacy_shipment_read["status"],
            "shipment_post_status": legacy_shipment_post["status"],
            "orders_detail": str(ob.get("detail") or ob.get("message"))[:80]}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "SO1-orders-read.png": "卡片显示本轮真实响应：GET /api/mod/xcagi-erp-domain-bridge/orders 返回 200（清单条数）、orders/next_number 返回 200 且 next_order_number 形如 26-09-00001A。",
    "SO2-master-data.png": "卡片显示本租户真实客户清单与产品清单（均 200）及选中的客户名与型号。",
    "SO3-planner-generate.png": "卡片显示对话成单真实响应：chat 200、action=tool_call、document.success=true、doc_name=发货单_<单号>_<时间>.xlsx、file_path 指向服务端文件，并附该文件真实存在与非空字节数。",
    "SO4-records-readback.png": "卡片显示发货记录清单条数前后对比（after>before）、命中该客户(purchase_unit)的记录数与最新一条记录内容。",
    "SO5-legacy-fail-closed.png": "卡片显示 POST /api/orders 403（detail 指明「该旧业务接口尚未提供安全的租户数据隔离」）、GET /api/shipment/orders 403、POST /api/shipment/orders 405（旧路由无写面）。",
    "__video__": "本轮真实浏览器会话录像（webm，ffmpeg 实测 20.16s，1600x1000 VP8/25fps）：管理员登录 → 订单清单/单号 → 真实客户与产品 → 对话成单并生成发货单文件 → 发货记录读回 → 旧接口 403/405 负例。",
}

CASES = [
    {"id": "SO1", "title": "租户安全订单清单与下一单号真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/mod/xcagi-erp-domain-bridge/orders 与 /orders/next_number。",
     "expected": "均 HTTP 200，且 next_order_number 非空。",
     "run": case_orders_read},
    {"id": "SO2", "title": "本租户真实客户与产品读取（租户隔离读面）",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET customers/list 与 products/list。",
     "expected": "均 HTTP 200，且至少各有 1 条真实数据（客户名/型号非空）。",
     "run": case_master_data},
    {"id": "SO3", "title": "对话成单 → 发货单文档真实生成（核心正向）",
     "input": "管理员会话 + 真实客户名/型号（取自本租户数据），5桶 规格20。",
     "actions": "页面上下文 POST /api/mod/xcagi-planner-bridge/chat，随后校验服务端生成的 xlsx 文件。",
     "expected": "chat 200 且 action=tool_call；document.success=true、doc_name 非空、file_path 对应文件真实存在且字节数>0。",
     "run": case_planner_generate_document},
    {"id": "SO4", "title": "发货记录读回含本轮新建记录",
     "input": "管理员会话 + 真实客户名。",
     "actions": "读发货记录清单 → 对话再成一单 → 再读回对比。",
     "expected": "两次均 200，记录数增加且存在 purchase_unit 命中该客户的记录。",
     "run": case_records_readback},
    {"id": "SO5", "title": "旧业务接口 fail-closed（负例）",
     "input": "管理员会话。",
     "actions": "页面上下文 POST /api/orders、GET/POST /api/shipment/orders。",
     "expected": "POST /api/orders 与 GET /api/shipment/orders 均 403（detail 指明未提供安全的租户数据隔离）；POST /api/shipment/orders 405（无写面）。",
     "run": case_legacy_fail_closed},
]