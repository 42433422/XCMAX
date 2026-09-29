"""erp-templates（单据模板与套打）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的单据模板面。
impl：FHD/app/fastapi_routes/document_templates.py、template_create.py、template_api.py。
真实验证面：真实创建租户模板并在列表/详情读回 → 单据模板与销售合同模板读取；
并含缺字段创建被 400 与不存在模板 404（负例）。所有请求在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-templates"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通单据模板真实写-读回：POST /api/templates/create 新建租户模板 → "
    "GET /api/templates 列表读回 → GET /api/templates/detail/{id} 读回字段 → "
    "GET /api/document-templates 与 /api/sales-contract/templates 读回内置单据模板；"
    "并含缺字段创建 400 与不存在模板 404（负例）。"
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


def case_template_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    name = f"验收单据模板{ts}"
    created = _api(page, "/api/templates/create", method="POST",
                   body={"name": name, "category": "excel",
                         "fields": [{"key": "f1", "label": "字段1"}, {"key": "f2", "label": "字段2"}]})
    cb = created.get("body") or {}
    tmpl = cb.get("template") or {}
    tid = tmpl.get("id")
    lst = _api(page, "/api/templates")
    items = (lst.get("body") or {}).get("templates") or []
    names = [x.get("name") for x in items]
    detail = _api(page, f"/api/templates/detail/{tid}") if tid else {"status": 0, "body": {}}
    dd = (detail.get("body") or {}).get("template") or {}
    _panel(page, env, "TPL1-template-roundtrip.png",
           "POST/GET /api/templates/create|list|detail · 模板真实写-读回",
           {"create_http": created["status"], "success": cb.get("success"), "template_id": tid,
            "template_key": tmpl.get("template_key"), "list_http": lst["status"],
            "created_name_in_list": name in names,
            "readback_http": detail["status"], "readback_name": dd.get("name"),
            "readback_fields": [f.get("key") for f in (dd.get("fields") or [])]})
    ok = (created["status"] == 200 and cb.get("success") is True and bool(tid) and name in names
          and detail["status"] == 200 and dd.get("name") == name
          and len(dd.get("fields") or []) == 2)
    return {"create_http": created["status"], "template_id": tid, "created_name_in_list": name in names,
            "readback_name": dd.get("name"), "readback_fields": len(dd.get("fields") or [])}, ok


def case_builtin_templates(page, env):
    doc = _api(page, "/api/document-templates")
    sale = _api(page, "/api/sales-contract/templates")
    dd = (doc.get("body") or {}).get("data") or []
    sd = (sale.get("body") or {}).get("data") or []
    _panel(page, env, "TPL2-builtin-templates.png",
           "GET /api/document-templates · /api/sales-contract/templates",
           {"document_templates_http": doc["status"], "document_count": len(dd),
            "document_slugs": [x.get("slug") for x in dd],
            "sales_templates_http": sale["status"], "sales_count": len(sd),
            "sales_slugs": [x.get("slug") for x in sd]})
    ok = doc["status"] == 200 and len(dd) >= 1 and sale["status"] == 200 and len(sd) >= 1
    return {"document_templates_http": doc["status"], "document_count": len(dd),
            "sales_templates_http": sale["status"], "sales_count": len(sd)}, ok


def case_negative(page, env):
    empty = _api(page, "/api/templates/create", method="POST", body={})
    missing = _api(page, "/api/templates/detail/db:999999")
    eb = empty.get("body") or {}
    mb = missing.get("body") or {}
    _panel(page, env, "TPL3-template-negative.png",
           "缺字段创建 400 · 不存在模板 404（负例）",
           {"create_empty": {"status": empty["status"], "error_code": eb.get("error_code"),
                             "message": eb.get("message")},
            "missing_template": {"status": missing["status"], "error_code": mb.get("error_code"),
                                 "message": mb.get("message")}})
    ok = empty["status"] == 400 and missing["status"] == 404
    return {"create_empty": {"status": empty["status"], "message": eb.get("message")},
            "missing_template": {"status": missing["status"], "message": mb.get("message")}}, ok


CASES = [
    {"id": "TPL1", "title": "租户模板真实写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/templates/create，随后 GET /api/templates 与 /detail/{id}。",
     "expected": "创建 200 返回 id；列表命中；按 id 读回名称与 2 个字段。",
     "run": case_template_roundtrip},
    {"id": "TPL2", "title": "内置单据模板读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/document-templates 与 /api/sales-contract/templates。",
     "expected": "两者均 200 且模板数≥1。",
     "run": case_builtin_templates},
    {"id": "TPL3", "title": "缺字段创建 400 · 不存在模板 404（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/templates/create（空 body）；GET /api/templates/detail/db:999999。",
     "expected": "空 body 400 tool_failed；不存在模板 404。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "TPL1-template-roundtrip.png": "浏览器渲染模板写-读回真实 JSON：create 200、template_id=db:2，列表命中新建名称，按 id 读回名称与 2 个字段。",
    "TPL2-builtin-templates.png": "浏览器渲染内置单据与销售合同模板真实 JSON（slug 清单）。",
    "TPL3-template-negative.png": "浏览器渲染空 body 创建 400 tool_failed 与不存在模板 404。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 模板写读回 → 内置模板 → 负例。",
}