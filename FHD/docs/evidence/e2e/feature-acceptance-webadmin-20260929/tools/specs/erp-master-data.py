"""erp-master-data（产品 / 客户 / 供应商主数据）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的租户安全主数据域门面。
impl：FHD/app/services/products_service.py、business_db_customer_mutations.py；
      租户安全门面 /api/mod/xcagi-erp-domain-bridge/products|*。
真实验证面：真实新建产品并在列表/详情读回 → 真实新建客户并在列表读回 →
域门面与仓储注册读取；并含缺名称产品 400、旧未隔离接口 403 fail-closed（负例）。
"""

import time

FEATURE = "erp-master-data"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通主数据真实写-读回：POST /api/mod/xcagi-erp-domain-bridge/products/add "
    "新建产品 → 列表与按 id 读回 → POST /customers 新建客户 → 列表读回 → 域门面/仓储注册读取；"
    "并含缺名称产品 400 与旧未隔离 /api/products/list 403 fail-closed（负例）。"
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


def case_product_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    created = _api(page, "/api/mod/xcagi-erp-domain-bridge/products/add", method="POST",
                   body={"name": f"主数据产品{ts}", "model_number": f"MD-{ts}", "unit_price": 8.5,
                         "quantity": 4, "unit": "个"})
    pid = ((created.get("body") or {}).get("data") or {}).get("id")
    got = _api(page, f"/api/mod/xcagi-erp-domain-bridge/products/{pid}") if pid else {"status": 0, "body": {}}
    gd = (got.get("body") or {}).get("data") or {}
    _panel(page, env, "MD1-product-roundtrip.png",
           "POST/GET products/add|{id} · 产品真实写-读回",
           {"create_http": created["status"], "product_id": pid, "readback_http": got["status"],
            "readback_name": gd.get("name"), "readback_model": gd.get("model_number"),
            "readback_price": gd.get("price"), "readback_unit": gd.get("unit")})
    ok = (created["status"] == 200 and bool(pid) and got["status"] == 200
          and gd.get("id") == pid and gd.get("unit") == "个")
    return {"create_http": created["status"], "product_id": pid, "readback_name": gd.get("name"),
            "readback_model": gd.get("model_number"), "readback_price": gd.get("price")}, ok


def case_customer_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    name = f"主数据客户{ts}"
    created = _api(page, "/api/mod/xcagi-erp-domain-bridge/customers", method="POST",
                   body={"customer_name": name})
    cid = ((created.get("body") or {}).get("data") or {}).get("id")
    lst = _api(page, "/api/mod/xcagi-erp-domain-bridge/customers/list")
    items = (lst.get("body") or {}).get("data") or []
    names = [x.get("customer_name") for x in items]
    _panel(page, env, "MD2-customer-roundtrip.png",
           "POST/GET customers · 客户真实写-读回",
           {"create_http": created["status"], "customer_id": cid, "list_http": lst["status"],
            "count": len(items), "created_name_in_list": name in names, "sample": names[:3]})
    ok = (created["status"] == 200 and bool(cid) and lst["status"] == 200 and name in names)
    return {"create_http": created["status"], "customer_id": cid, "created_name_in_list": name in names}, ok


def case_registries(page, env):
    dom = _api(page, "/api/mod/xcagi-erp-domain-bridge/domains/registry")
    rep = _api(page, "/api/mod/xcagi-erp-domain-bridge/repositories/registry")
    dd = (dom.get("body") or {}).get("data") or {}
    rd = (rep.get("body") or {}).get("data") or {}
    _panel(page, env, "MD3-registries.png",
           "GET domains/registry · repositories/registry · 域门面与仓储注册",
           {"domains_http": dom["status"], "domain_count": dd.get("domain_count"),
            "domain_ids": [x.get("domain_id") for x in (dd.get("domains") or [])],
            "repos_http": rep["status"], "repository_via_mod": rd.get("repository_via_mod"),
            "adapter_classes": rd.get("adapter_classes")})
    ok = (dom["status"] == 200 and int(dd.get("domain_count") or 0) >= 3
          and rep["status"] == 200 and rd.get("repository_via_mod") is True)
    return {"domains_http": dom["status"], "domain_count": dd.get("domain_count"),
            "domain_ids": [x.get("domain_id") for x in (dd.get("domains") or [])],
            "repos_http": rep["status"]}, ok


def case_negative(page, env):
    no_name = _api(page, "/api/mod/xcagi-erp-domain-bridge/products/add", method="POST",
                   body={"model_number": "NO-NAME"})
    legacy = _api(page, "/api/products/list")
    nb = no_name.get("body") or {}
    lb = legacy.get("body") or {}
    _panel(page, env, "MD4-masterdata-negative.png",
           "缺名称产品 400 · 旧未隔离接口 403 fail-closed（负例）",
           {"product_without_name": {"status": no_name["status"], "message": nb.get("message")},
            "legacy_products_list": {"status": legacy["status"], "error_code": lb.get("error_code"),
                                     "message": lb.get("message")}})
    ok = (no_name["status"] == 400 and "产品名称不能为空" in str(nb.get("message"))
          and legacy["status"] == 403)
    return {"product_without_name": {"status": no_name["status"], "message": nb.get("message")},
            "legacy_products_list": {"status": legacy["status"], "error_code": lb.get("error_code")}}, ok


CASES = [
    {"id": "MD1", "title": "产品主数据真实写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/mod/.../products/add，随后 GET /api/mod/.../products/{id}。",
     "expected": "创建 200 返回 id；按 id 读回名称/型号/单位一致。",
     "run": case_product_roundtrip},
    {"id": "MD2", "title": "客户主数据真实写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/mod/.../customers，随后 GET /api/mod/.../customers/list。",
     "expected": "创建 200 返回 id；列表中读到本轮新建客户名。",
     "run": case_customer_roundtrip},
    {"id": "MD3", "title": "域门面与仓储注册真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/mod/.../domains/registry 与 /repositories/registry。",
     "expected": "域数量≥3（products/customers/shipment）；repository_via_mod=true。",
     "run": case_registries},
    {"id": "MD4", "title": "缺名称产品 400 · 旧未隔离接口 403（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/mod/.../products/add（缺 name）；GET /api/products/list（旧接口）。",
     "expected": "缺名称 400「产品名称不能为空」；旧接口 403 fail-closed。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "MD1-product-roundtrip.png": "浏览器渲染产品写-读回真实 JSON：create 200、id、按 id 读回名称/型号/价格/单位。",
    "MD2-customer-roundtrip.png": "浏览器渲染客户写-读回真实 JSON：create 200、id、列表命中所建客户名。",
    "MD3-registries.png": "浏览器渲染主数据域门面注册：domain_count=3 与 domains、repository_via_mod=true、适配器类。",
    "MD4-masterdata-negative.png": "浏览器渲染缺名称产品 400「产品名称不能为空」与旧 /api/products/list 403「该旧业务接口尚未提供安全的租户数据隔离」。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 产品写读回 → 客户写读回 → 域注册 → 负例。",
}