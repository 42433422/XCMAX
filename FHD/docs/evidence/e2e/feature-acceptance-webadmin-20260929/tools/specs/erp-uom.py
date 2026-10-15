"""erp-uom（计量单位管理）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的计量单位面。
impl：FHD/app/services/uom_service.py（多计量单位与换算）。
真实验证面：产品单位字段读回、购买单位门面读回、旧单位接口 403 fail-closed（负例）；
并如实探测「租户安全的多计量单位/换算接口」（本环境未暴露，记录真实 403/缺口）。
"""

import time

FEATURE = "erp-uom"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端读取产品计量单位字段（/api/mod/xcagi-erp-domain-bridge/products/list）→ "
    "读数购买单位门面（/purchase_units）→ 对旧 /api/products/units、/api/units 发起请求并记录 403 fail-closed（负例）→ "
    "如实探测租户安全的多计量单位/换算接口（本环境未暴露 → 后门 403）。"
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


def case_product_unit(page, env):
    ts = time.strftime("%H%M%S")
    _api(page, "/api/mod/xcagi-erp-domain-bridge/products/add", method="POST",
         body={"name": f"单位产品{ts}", "model_number": f"UOM-{ts}", "unit": "箱"})
    r = _api(page, "/api/mod/xcagi-erp-domain-bridge/products/list")
    items = (r.get("body") or {}).get("data") or []
    mine = next((x for x in items if x.get("model_number") == f"UOM-{ts}"), {})
    _panel(page, env, "UOM1-product-unit.png",
           "GET /api/mod/.../products/list · 产品计量单位字段读回",
           {"status": r["status"], "total": (r.get("body") or {}).get("total"),
            "product_name": mine.get("name"), "model_number": mine.get("model_number"),
            "unit": mine.get("unit")})
    ok = r["status"] == 200 and mine.get("unit") == "箱"
    return {"status": r["status"], "unit": mine.get("unit"), "model_number": mine.get("model_number")}, ok


def case_purchase_units(page, env):
    r = _api(page, "/api/mod/xcagi-erp-domain-bridge/purchase_units")
    b = r.get("body") or {}
    items = b.get("data") or []
    _panel(page, env, "UOM2-purchase-units.png",
           "GET /api/mod/.../purchase_units · 购买单位门面读回",
           {"status": r["status"], "success": b.get("success"),
            "count": len(items) if isinstance(items, list) else None,
            "sample": [{k: x.get(k) for k in ("id", "unit_name", "is_active")} for x in (items[:3] if isinstance(items, list) else [])]})
    ok = r["status"] == 200 and b.get("success") is True and isinstance(items, list)
    return {"status": r["status"], "count": len(items) if isinstance(items, list) else None}, ok


def case_legacy_denied(page, env):
    a = _api(page, "/api/products/units")
    b = _api(page, "/api/units")
    ab, bb = a.get("body") or {}, b.get("body") or {}
    _panel(page, env, "UOM3-legacy-denied.png",
           "旧单位接口 403 fail-closed（负例）",
           {"products_units": {"status": a["status"], "error_code": ab.get("error_code")},
            "units": {"status": b["status"], "error_code": bb.get("error_code")}})
    ok = a["status"] == 403 and b["status"] == 403
    return {"products_units": {"status": a["status"]}, "units": {"status": b["status"]}}, ok


def case_uom_surface(page, env):
    units = _api(page, "/api/units")
    p_units = _api(page, "/api/products/units")
    o_punits = _api(page, "/api/orders/purchase-units")
    bridge = _api(page, "/api/mod/xcagi-erp-domain-bridge/purchase_units")
    ship_units = _api(page, "/api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/units")
    create = _api(page, "/api/mod/xcagi-erp-domain-bridge/purchase_units", method="POST",
                  body={"unit_name": "箱"})
    by_name = _api(page, "/api/mod/xcagi-erp-domain-bridge/purchase_units/by_name/箱")
    cb = create.get("body") or {}
    bn = by_name.get("body") or {}
    _panel(page, env, "UOM4-uom-surface.png",
           "租户安全多计量单位 / 换算读写面探测（本环境缺失 → 失败）",
           {"GET /api/units": {"status": units["status"], "message": (units.get("body") or {}).get("message")},
            "GET /api/products/units": {"status": p_units["status"], "message": (p_units.get("body") or {}).get("message")},
            "GET /api/orders/purchase-units": {"status": o_punits["status"], "message": (o_punits.get("body") or {}).get("message")},
            "GET mod bridge purchase_units（只读门面）": {"status": bridge["status"], "data": (bridge.get("body") or {}).get("data")},
            "GET mod bridge shipment-records/units（只读）": {"status": ship_units["status"]},
            "POST mod bridge purchase_units（创建单位）": {"status": create["status"], "message": cb.get("message")},
            "GET mod bridge purchase_units/by_name/箱（换算/读回）": {"status": by_name["status"], "message": bn.get("message")},
            "verdict": "无租户安全的多计量单位创建/换算接口（/api/units、/api/products/units、"
                       "/api/orders/purchase-units 均 403 fail-closed；mod 门面 purchase_units 仅 GET 列表，"
                       "POST 405、by_name 404；uom_service 未接入任何路由）"})
    # 期望：存在租户安全的多计量单位/换算读写面（创建或换算返回 200）
    ok = create["status"] == 200 or by_name["status"] == 200
    return {"status": bridge["status"], "create_status": create["status"], "by_name_status": by_name["status"],
            "legacy_units": units["status"], "legacy_products_units": p_units["status"],
            "legacy_orders_purchase_units": o_punits["status"], "ship_records_units": ship_units["status"],
            "note": "本环境无租户安全的多计量单位创建/换算接口；legacy /api/units、/api/products/units、"
                    "/api/orders/purchase-units 均 403 fail-closed，mod 门面 purchase_units 仅 GET 列表，"
                    "POST 405、by_name 404；uom_service 未接入任何路由"}, ok


CASES = [
    {"id": "UOM1", "title": "产品计量单位字段真实读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST products/add（unit=箱），GET products/list。",
     "expected": "列表读回该产品的 unit=箱。",
     "run": case_product_unit},
    {"id": "UOM2", "title": "购买单位门面真实读回",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/mod/xcagi-erp-domain-bridge/purchase_units。",
     "expected": "HTTP 200、success=true，返回购买单位集合。",
     "run": case_purchase_units},
    {"id": "UOM3", "title": "旧单位接口 403 fail-closed（负例）",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/products/units 与 /api/units。",
     "expected": "两者均 403，不返回未隔离单位数据。",
     "run": case_legacy_denied},
    {"id": "UOM4", "title": "租户安全多计量单位/换算读写面（本环境缺失）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "GET /api/units、/api/products/units、/api/orders/purchase-units 与 mod 门面 purchase_units"
                "（含 POST 与 by_name）。",
     "expected": "存在租户安全的多计量单位创建或换算读写面（返回 200）。",
     "run": case_uom_surface},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "UOM1-product-unit.png": "浏览器渲染产品单位字段读回真实 JSON：status=200、total=1、product_name=单位产品164033、model_number=UOM-164033、unit=箱。",
    "UOM2-purchase-units.png": "浏览器渲染购买单位门面读取的真实 JSON：status=200、success=true、count=1，sample=[{id:4,unit_name:VC验收客户SO,is_active:1}]。",
    "UOM3-legacy-denied.png": "浏览器渲染 /api/products/units 与 /api/units 的 403 fail-closed 响应：error_code=http_403，message=该旧业务接口尚未提供安全的租户数据隔离。",
    "UOM4-uom-surface.png": "浏览器渲染多计量单位/换算读写面探测：GET /api/units、/api/products/units、/api/orders/purchase-units 均 403；mod 门面 purchase_units GET 200（只读列表，含 unit_name=VC验收客户SO）、shipment-records/units 200（只读）；POST purchase_units 405 Method Not Allowed、by_name/箱 404 购买单位不存在；verdict=无租户安全的多计量单位创建/换算接口（uom_service 未接入路由）。核心用例失败（产品面缺失）。",
    "__video__": "本轮真实浏览器会话录像（webm，17.48s，ffmpeg 实测）：管理端登录 → 产品单位读回 → 购买单位门面 → 旧接口 403 → 换算面探测（缺失）。",
}