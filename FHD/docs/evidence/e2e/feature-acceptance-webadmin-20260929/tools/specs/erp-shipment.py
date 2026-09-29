"""erp-shipment（发货单与出货管理）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的发货/出货面。
impl：FHD/app/application/shipment_app_service.py、shipment_document_workflows.py；
      租户安全读取 /api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/*；
      业务出口 POST /api/business/shipment/create。
真实验证面：真实发布发货单创建事件 → 经 mod 域门面读回出货记录/单位 → 出货管理员工状态；
并含缺 unit_name 422、旧未隔离接口 403 fail-closed（负例）。所有请求在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-shipment"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通发货面：POST /api/business/shipment/create 真实发布 shipment.created 事件 → "
    "GET /api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/records|units 读回出货记录/单位 → "
    "GET /api/mod/xcagi-core-workflow-employees/employees/shipment_mgmt/status 读取出货管理员工状态；"
    "并含缺 unit_name 422 与旧 /api/shipment/orders 403 fail-closed（负例）。"
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


def case_shipment_event(page, env):
    ts = time.strftime("%H%M%S")
    unit = f"发货单位{ts}"
    _api(page, "/api/mod/xcagi-erp-domain-bridge/customers", method="POST", body={"customer_name": unit})
    created = _api(page, "/api/business/shipment/create", method="POST",
                   body={"unit_name": unit, "items": [{"name": "验收产品", "quantity": 1}],
                         "contact_person": "张三", "contact_phone": "13800000000"})
    b = created.get("body") or {}
    _panel(page, env, "SH1-shipment-create.png",
           "POST /api/business/shipment/create · 真实发布发货单创建事件",
           {"status": created["status"], "success": b.get("success"), "published": b.get("published"),
            "event": b.get("event"), "run_id": b.get("run_id"), "unit_name": unit})
    ok = (created["status"] == 200 and b.get("success") is True and b.get("published") is True
          and b.get("event") == "shipment.created" and bool(b.get("run_id")))
    return {"status": created["status"], "published": b.get("published"), "event": b.get("event"),
            "run_id": b.get("run_id")}, ok


def case_records_read(page, env):
    rec = _api(page, "/api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/records")
    units = _api(page, "/api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/units")
    _panel(page, env, "SH2-shipment-records.png",
           "GET shipment-records/records · units · 出货记录/单位读回",
           {"records_http": rec["status"], "records": str(rec.get("body"))[:220],
            "units_http": units["status"], "units": str(units.get("body"))[:220]})
    ok = rec["status"] == 200 and units["status"] == 200
    return {"records_http": rec["status"], "records": str(rec.get("body"))[:220],
            "units_http": units["status"]}, ok


def case_employee_status(page, env):
    r = _api(page, "/api/mod/xcagi-core-workflow-employees/employees/shipment_mgmt/status")
    d = (r.get("body") or {}).get("data") or {}
    _panel(page, env, "SH3-shipment-employee.png",
           "GET .../employees/shipment_mgmt/status · 出货管理员工状态",
           {"status": r["status"], "ok": d.get("ok"), "summary": d.get("summary"),
            "meta": d.get("meta")})
    ok = r["status"] == 200 and d.get("ok") is True
    return {"status": r["status"], "ok": d.get("ok"), "summary": d.get("summary")}, ok


def case_negative(page, env):
    bad = _api(page, "/api/business/shipment/create", method="POST",
               body={"items": [{"name": "x", "quantity": 1}]})
    bb = bad.get("body") or {}
    legacy = _api(page, "/api/shipment/orders")
    lb = legacy.get("body") or {}
    _panel(page, env, "SH4-shipment-negative.png",
           "缺 unit_name 422 · 旧 /api/shipment/orders 403（负例）",
           {"missing_unit_name": {"status": bad["status"], "error_code": bb.get("error_code"),
                                  "field": ((bb.get("errors") or [{}])[0]).get("field")},
            "legacy_shipment_orders": {"status": legacy["status"], "error_code": lb.get("error_code"),
                                       "message": lb.get("message")}})
    ok = bad["status"] == 422 and legacy["status"] == 403
    return {"missing_unit_name": {"status": bad["status"], "error_code": bb.get("error_code")},
            "legacy_shipment_orders": {"status": legacy["status"], "error_code": lb.get("error_code")}}, ok


CASES = [
    {"id": "SH1", "title": "真实发布发货单创建事件",
     "input": "已建立的管理员会话（带 CSRF 令牌）；先建购买单位。",
     "actions": "POST /api/business/shipment/create（含 unit_name 与明细）。",
     "expected": "200、success=true、published=true、event=shipment.created、含 run_id。",
     "run": case_shipment_event},
    {"id": "SH2", "title": "出货记录与单位真实读回",
     "input": "已建立的管理员会话。",
     "actions": "GET shipment-records/records 与 shipment-records/units。",
     "expected": "两者均 200，返回出货记录/单位集合。",
     "run": case_records_read},
    {"id": "SH3", "title": "出货管理员工状态真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/mod/xcagi-core-workflow-employees/employees/shipment_mgmt/status。",
     "expected": "200 且 ok=true。",
     "run": case_employee_status},
    {"id": "SH4", "title": "缺 unit_name 422 · 旧接口 403（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/business/shipment/create（缺 unit_name）；GET /api/shipment/orders。",
     "expected": "缺参 422 validation_error；旧接口 403 fail-closed。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "SH1-shipment-create.png": "浏览器渲染发货单事件发布真实响应：200、published=true、event=shipment.created、run_id。",
    "SH2-shipment-records.png": "浏览器渲染出货记录与单位读取的真实 JSON（租户安全门面）。",
    "SH3-shipment-employee.png": "浏览器渲染出货管理员工 status 真实 JSON（ok、summary、meta）。",
    "SH4-shipment-negative.png": "浏览器渲染缺 unit_name 的 422 validation_error 与旧 /api/shipment/orders 403 fail-closed。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 发货事件发布 → 出货记录读取 → 员工状态 → 负例。",
}