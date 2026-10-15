"""erp-inventory-warehouse（仓库 / 库位 / 调拨 / 预警）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的多仓库存面。
impl：FHD/app/services/inventory_warehouses.py、inventory_movements.py（经 /api/inventory/*）。
真实验证面：真实新建仓库并在列表读回 → 真实新建库位并在按仓查询读回 → 库存预警读取；
并含缺仓库 ID 查询库位被拒（负例）。所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-inventory-warehouse"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通多仓面：POST /api/inventory/warehouses 新建仓库 → GET /api/inventory/warehouses "
    "读回 → POST /api/inventory/locations 新建库位 → GET /api/inventory/locations?warehouse_id 读回 → "
    "GET /api/inventory/alert 与 /combined-alert 读取预警；并含缺 warehouse_id 查询被拒（负例）。"
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


def case_warehouse_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    name = f"多仓仓库{ts}"
    created = _api(page, "/api/inventory/warehouses", method="POST",
                   body={"name": name, "code": f"MW{ts}", "location": "上海"})
    cd = (created.get("body") or {}).get("data") or {}
    wid = cd.get("id")
    _STATE["warehouse_id"] = wid
    lst = _api(page, "/api/inventory/warehouses")
    items = (lst.get("body") or {}).get("data") or []
    found = next((x for x in items if x.get("id") == wid), {})
    _panel(page, env, "IW1-warehouse-roundtrip.png",
           "POST/GET /api/inventory/warehouses · 仓库真实写-读回",
           {"create_http": created["status"], "warehouse_id": wid, "code": cd.get("code"),
            "list_http": lst["status"], "count": len(items), "readback_name": found.get("name"),
            "readback_code": found.get("code")})
    ok = (created["status"] == 200 and bool(wid) and lst["status"] == 200
          and found.get("name") == name)
    return {"create_http": created["status"], "warehouse_id": wid, "code": cd.get("code"),
            "readback_name": found.get("name")}, ok


def case_location_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    wid = _STATE.get("warehouse_id")
    name = f"库位{ts}"
    created = _api(page, "/api/inventory/locations", method="POST",
                   body={"warehouse_id": wid, "name": name, "code": f"LOC{ts}"})
    cd = (created.get("body") or {}).get("data") or {}
    lid = cd.get("id")
    lst = _api(page, f"/api/inventory/locations?warehouse_id={wid}")
    items = (lst.get("body") or {}).get("data") or []
    found = next((x for x in items if x.get("id") == lid), {})
    _panel(page, env, "IW2-location-roundtrip.png",
           "POST/GET /api/inventory/locations · 库位真实写-读回",
           {"create_http": created["status"], "location_id": lid, "warehouse_id": wid,
            "list_http": lst["status"], "count": len(items), "readback_name": found.get("name")})
    ok = (created["status"] == 200 and bool(lid) and lst["status"] == 200
          and found.get("name") == name)
    return {"create_http": created["status"], "location_id": lid, "readback_name": found.get("name")}, ok


def case_alerts(page, env):
    a = _api(page, "/api/inventory/alert")
    c = _api(page, "/api/inventory/combined-alert")
    ab = a.get("body") or {}
    cb = c.get("body") or {}
    _panel(page, env, "IW3-warehouse-alerts.png",
           "GET /api/inventory/alert · /combined-alert · 库存预警读取",
           {"alert_http": a["status"], "alert_count": ab.get("count"), "alert": str(ab.get("data"))[:150],
            "combined_http": c["status"], "total_alerts": cb.get("total_alerts"),
            "inventory_alerts": len(cb.get("inventory_alerts") or []),
            "material_low_stock": len(cb.get("material_low_stock") or [])})
    ok = a["status"] == 200 and c["status"] == 200 and "total_alerts" in cb
    return {"alert_http": a["status"], "combined_http": c["status"], "total_alerts": cb.get("total_alerts")}, ok


def case_negative(page, env):
    r = _api(page, "/api/inventory/locations")
    b = r.get("body") or {}
    _panel(page, env, "IW4-warehouse-negative.png",
           "缺 warehouse_id 查询库位被拒（负例）", r)
    ok = b.get("success") is False and "仓库" in str(b.get("message"))
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message")}, ok


CASES = [
    {"id": "IW1", "title": "仓库真实写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/inventory/warehouses，随后 GET /api/inventory/warehouses。",
     "expected": "创建 200 返回仓库 id/code；列表读回同名仓库。",
     "run": case_warehouse_roundtrip},
    {"id": "IW2", "title": "库位真实写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/inventory/locations，随后 GET /api/inventory/locations?warehouse_id。",
     "expected": "创建 200 返回库位 id；按仓查询读回同名库位。",
     "run": case_location_roundtrip},
    {"id": "IW3", "title": "库存预警真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/inventory/alert 与 /combined-alert。",
     "expected": "两者均 200；combined-alert 含 total_alerts。",
     "run": case_alerts},
    {"id": "IW4", "title": "缺 warehouse_id 查询库位被拒（负例）",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/inventory/locations（无参）。",
     "expected": "success=false，提示仓库 ID 不能为空。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "IW1-warehouse-roundtrip.png": "浏览器渲染仓库写-读回真实 JSON：create 200、仓库 id/code，列表读回同名仓库。",
    "IW2-location-roundtrip.png": "浏览器渲染库位写-读回真实 JSON：create 200、库位 id，按仓查询读回同名库位。",
    "IW3-warehouse-alerts.png": "浏览器渲染库存预警接口真实 JSON（alert count 与 combined total_alerts）。",
    "IW4-warehouse-negative.png": "浏览器渲染缺 warehouse_id 查询库位的拒绝响应「仓库ID不能为空」。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 仓库写读回 → 库位写读回 → 预警 → 负例。",
}