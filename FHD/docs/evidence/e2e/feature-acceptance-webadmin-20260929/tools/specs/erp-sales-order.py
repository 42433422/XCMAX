"""erp-sales-order（销售订单管理）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的销售/发货订单面。
impl：FHD/app/fastapi_routes/shipment_orders.py（旧 /api/shipment/orders，按设计 fail-closed）。
真实验证面：经租户安全 mod 域门面读取订单清单与下一单号 → 规划器对话识别订单意图 →
旧接口 403 fail-closed（负例）；并如实探测租户安全的销售订单创建面（本环境不可用，记录真实 400/403）。
"""

import time

FEATURE = "erp-sales-order"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端读取租户安全订单清单（/api/mod/xcagi-erp-domain-bridge/orders）与下一单号 → "
    "POST /api/mod/xcagi-planner-bridge/chat 触发订单意图识别（返回 action=tool_call）→ "
    "如实探测租户安全销售订单创建面（旧 /api/orders 403、mod 门面 GET-only、planner 400，均失败；"
    "附 /api/purchase/orders 采购订单写面旁证）与旧 /api/shipment/orders 403 fail-closed（负例）。"
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


def case_orders_read(page, env):
    orders = _api(page, "/api/mod/xcagi-erp-domain-bridge/orders")
    nxt = _api(page, "/api/mod/xcagi-erp-domain-bridge/orders/next_number")
    ob = orders.get("body") or {}
    nd = (nxt.get("body") or {}).get("data") or {}
    _panel(page, env, "SO1-orders-read.png",
           "GET /api/mod/.../orders · next_number · 订单清单与单号读回",
           {"orders_http": orders["status"], "orders_body": str(ob)[:200],
            "next_number_http": nxt["status"], "next_order_number": nd.get("order_number"),
            "sequence": nd.get("sequence"), "year_month": nd.get("year_month")})
    ok = orders["status"] == 200 and nxt["status"] == 200 and bool(nd.get("order_number"))
    return {"orders_http": orders["status"], "next_number_http": nxt["status"],
            "next_order_number": nd.get("order_number"), "sequence": nd.get("sequence")}, ok


def case_order_intent(page, env):
    r = _api(page, "/api/mod/xcagi-planner-bridge/chat", method="POST",
             body={"message": "开发货单，客户 验收客户，产品 验收产品，数量 1"})
    b = r.get("body") or {}
    d = b.get("data") or {}
    _panel(page, env, "SO2-order-intent.png",
           "POST /api/mod/xcagi-planner-bridge/chat · 订单意图真实识别",
           {"status": r["status"], "success": b.get("success"), "message": b.get("message"),
            "action": d.get("action"), "text": str(d.get("text"))[:120],
            "run_id": b.get("run_id")})
    ok = (r["status"] == 200 and b.get("success") is True and d.get("action") == "tool_call"
          and bool(b.get("run_id")))
    return {"status": r["status"], "action": d.get("action"), "run_id": b.get("run_id"),
            "text": str(d.get("text"))[:120],
            "note": "本环境订单文档生成因客户名解析缺陷失败（真实缺陷观察项）"}, ok


def case_order_write(page, env):
    direct = _api(page, "/api/orders", method="POST",
                  body={"unit_name": "验收客户", "products": [{"name": "验收产品", "quantity": 1}]})
    mod_post = _api(page, "/api/mod/xcagi-erp-domain-bridge/orders", method="POST",
                    body={"unit_name": "验收客户", "products": [{"name": "验收产品", "quantity": 1}]})
    purchase = _api(page, "/api/purchase/orders", method="POST",
                    body={"supplier_name": "验收供应商",
                          "items": [{"name": "验收物料", "quantity": 1}]})
    planner = _api(page, "/api/mod/xcagi-planner-bridge/tools/execute", method="POST",
                   body={"tool_name": "execute_erp_capability",
                         "arguments": {"tool_id": "shipment_orders", "action": "generate",
                                       "params": {"unit_name": "验收客户",
                                                  "products": [{"name": "验收产品", "quantity": 1}]}}})
    db = direct.get("body") or {}
    mb = mod_post.get("body") or {}
    pb = purchase.get("body") or {}
    pl = planner.get("body") or {}
    _panel(page, env, "SO3-order-write.png",
           "租户安全销售订单创建面探测（本环境缺失 → 失败；附采购订单写面旁证）",
           {"POST /api/orders（旧直写）": {"status": direct["status"], "message": db.get("message")},
            "POST mod bridge /orders": {"status": mod_post["status"], "message": mb.get("message")},
            "POST /api/mod/xcagi-planner-bridge/tools/execute（shipment_orders.generate）":
                {"status": planner["status"], "error_code": (pl.get("data") or {}).get("error_code")},
            "POST /api/purchase/orders（采购订单写面，非销售）":
                {"status": purchase["status"], "success": pb.get("success"), "message": pb.get("message")},
            "verdict": "无租户安全的销售订单创建面：旧 /api/orders 403 fail-closed，"
                       "mod 门面 /orders 仅 GET（POST 405），planner 高风险动作 400；"
                       "仅 /api/purchase/orders 存在采购订单写面（非销售）"})
    # 期望：销售订单创建成功（200 且 success=true）
    ok = (direct["status"] == 200 and db.get("success") is True) or \
         (mod_post["status"] == 200 and mb.get("success") is True)
    return {"direct_orders": {"status": direct["status"]}, "mod_orders_post": mod_post["status"],
            "planner": {"status": planner["status"],
                        "error_code": (pl.get("data") or {}).get("error_code")},
            "purchase_orders": {"status": purchase["status"], "success": pb.get("success")},
            "note": "本环境无租户安全的销售订单创建面（旧 /api/orders 403、mod 门面 GET-only、"
                    "planner 400）；/api/purchase/orders 为采购订单写面，非销售订单"}, ok


def case_negative(page, env):
    r = _api(page, "/api/shipment/orders")
    b = r.get("body") or {}
    _panel(page, env, "SO4-orders-negative.png",
           "旧 /api/shipment/orders 403 fail-closed（负例）", r)
    ok = r["status"] == 403
    return {"status": r["status"], "error_code": b.get("error_code"), "message": b.get("message")}, ok


CASES = [
    {"id": "SO1", "title": "订单清单与下一单号真实读回",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/mod/xcagi-erp-domain-bridge/orders 与 /orders/next_number。",
     "expected": "两者均 200，next_number 返回真实订单号。",
     "run": case_orders_read},
    {"id": "SO2", "title": "订单意图真实识别（规划器）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/mod/xcagi-planner-bridge/chat（开单意图）。",
     "expected": "200、success=true、action=tool_call、含 run_id。",
     "run": case_order_intent},
    {"id": "SO3", "title": "租户安全销售订单创建面（本环境缺失）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/orders、POST mod 门面 /orders、planner execute_erp_capability，"
                "并旁证 POST /api/purchase/orders。",
     "expected": "创建成功（200 且 success=true），并可在订单清单读回。",
     "run": case_order_write},
    {"id": "SO4", "title": "旧 /api/shipment/orders 403（负例）",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/shipment/orders。",
     "expected": "403 fail-closed，不返回未隔离订单数据。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "SO1-orders-read.png": "浏览器渲染租户安全订单清单与下一单号：orders_http=200（data.success=true、data.data.count=0）；next_number_http=200，next_order_number=26-09-00001A，sequence=1，year_month=26-09。",
    "SO2-order-intent.png": "浏览器渲染规划器对话的订单意图识别：status=200、success=true、message=处理完成、action=tool_call、text=已识别订单，正在生成发货单…、run_id=run_8af2597abdc194450ad0d1d87c3e821b4。",
    "SO3-order-write.png": "浏览器渲染销售订单创建面探测：POST /api/orders 403（该旧业务接口尚未提供安全的租户数据隔离）；POST mod 门面 /orders 405 Method Not Allowed；planner tools/execute 400 planner_tool_failed；旁证 POST /api/purchase/orders 200（采购订单写面，非销售，success=false「第 1 行明细未选择产品」）；verdict=无租户安全的销售订单创建面。核心用例失败（产品面缺失）。",
    "SO4-orders-negative.png": "浏览器渲染旧 /api/shipment/orders 403 fail-closed：error_code=http_403，message=该旧业务接口尚未提供安全的租户数据隔离。",
    "__video__": "本轮真实浏览器会话录像（webm，21.56s，ffmpeg 实测）：管理端登录 → 订单清单读回 → 订单意图识别 → 写面探测（缺失）→ 旧接口 403。",
}