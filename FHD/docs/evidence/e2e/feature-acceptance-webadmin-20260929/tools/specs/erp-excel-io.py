"""erp-excel-io（Excel 导入导出）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的 Excel 导入导出面。
impl：FHD/app/fastapi_routes/excel_templates.py、FHD/app/application/excel_imports.py、
      FHD/mods/xcagi-erp-domain-bridge/backend/blueprints.py（products 导出）。
真实验证面：Excel 模板清单读取 → 真实生成 Excel 数据文件 → 产品库真实导出 xlsx（二进制）；
并含缺数据参数 400 与旧导入接口 403 fail-closed（负例）。所有请求在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-excel-io"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端读取 Excel 模板清单 → POST /api/excel/data/generate 真实生成 xlsx 文件（返回真实 file_path）→ "
    "页面上下文校验 GET /api/mod/xcagi-erp-domain-bridge/products/export.xlsx 为真实二进制（字节数>0）；"
    "并含缺 data 参数 400 与旧 /api/excel/data/import/products 403 fail-closed（负例）。"
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


def _binary(page, path, method="GET"):
    return page.evaluate(
        "async ([p,m]) => { try { const r=await fetch(p,{credentials:'include',method:m});"
        " const buf=await r.arrayBuffer();"
        " return {status:r.status, bytes:buf.byteLength, ctype:r.headers.get('content-type')||''};"
        " } catch(e){ return {status:0, bytes:0, ctype:String(e)}; } }", [path, method])


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


def case_templates(page, env):
    r = _api(page, "/api/excel/templates")
    items = (r.get("body") or {}).get("templates") or []
    _panel(page, env, "EX1-excel-templates.png",
           "GET /api/excel/templates · Excel 模板清单",
           {"status": r["status"], "count": len(items),
            "sample": [{k: x.get(k) for k in ("id", "name", "template_type", "category")} for x in items[:5]]})
    ok = r["status"] == 200 and len(items) >= 1
    return {"status": r["status"], "count": len(items),
            "ids": [x.get("id") for x in items[:5]]}, ok


def case_generate(page, env):
    ts = time.strftime("%H%M%S")
    r = _api(page, "/api/excel/data/generate", method="POST",
             body={"template_id": "seed:customer-ledger",
                   "data": [{"customer_code": f"C{ts}", "customer_name": "验收客户"}]})
    b = r.get("body") or {}
    _panel(page, env, "EX2-excel-generate.png",
           "POST /api/excel/data/generate · 真实生成 Excel 数据文件",
           {"status": r["status"], "success": b.get("success"), "file_path": b.get("file_path"),
            "filename": b.get("filename"), "sheet": b.get("sheet"), "rows": b.get("rows")})
    ok = r["status"] == 200 and b.get("success") is True and bool(b.get("file_path")) and int(b.get("rows") or 0) >= 1
    return {"status": r["status"], "filename": b.get("filename"), "rows": b.get("rows"),
            "file_path": b.get("file_path")}, ok


def case_export_binary(page, env):
    r = _binary(page, "/api/mod/xcagi-erp-domain-bridge/products/export.xlsx")
    _panel(page, env, "EX3-excel-export.png",
           "GET /api/mod/.../products/export.xlsx · 产品库真实导出", r)
    ok = r["status"] == 200 and r["bytes"] > 1000
    return {"status": r["status"], "bytes": r["bytes"], "ctype": r["ctype"]}, ok


def case_negative(page, env):
    missing = _api(page, "/api/excel/data/generate", method="POST", body={"template_id": "seed:customer-ledger"})
    legacy = _api(page, "/api/excel/data/import/products", method="POST",
                  body={"rows": [{"name": "x", "model_number": "X1"}], "confirmed": True})
    mb, lb = missing.get("body") or {}, legacy.get("body") or {}
    _panel(page, env, "EX4-excel-negative.png",
           "缺 data 参数 400 · 旧导入接口 403（负例）",
           {"missing_data": {"status": missing["status"], "message": mb.get("message")},
            "legacy_import": {"status": legacy["status"], "error_code": lb.get("error_code"),
                              "message": lb.get("message")}})
    ok = missing["status"] == 400 and legacy["status"] == 403
    return {"missing_data": {"status": missing["status"], "message": mb.get("message")},
            "legacy_import": {"status": legacy["status"], "error_code": lb.get("error_code")}}, ok


CASES = [
    {"id": "EX1", "title": "Excel 模板清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/excel/templates。",
     "expected": "200 且模板数≥1，含 id/name/category。",
     "run": case_templates},
    {"id": "EX2", "title": "真实生成 Excel 数据文件",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/excel/data/generate（模板+数据）。",
     "expected": "200、success=true，返回真实 file_path 与 rows≥1。",
     "run": case_generate},
    {"id": "EX3", "title": "产品库真实导出二进制",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文校验 GET products/export.xlsx 的二进制字节数。",
     "expected": "200 且字节数>1000。",
     "run": case_export_binary},
    {"id": "EX4", "title": "缺 data 参数 400 · 旧导入接口 403（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/excel/data/generate（缺 data）；POST /api/excel/data/import/products。",
     "expected": "缺 data 400「请提供数据 data 参数」；旧导入 403 fail-closed。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "EX1-excel-templates.png": "浏览器渲染 Excel 模板清单真实 JSON（id/name/category）。",
    "EX2-excel-generate.png": "浏览器渲染真实生成 Excel 的响应：200、file_path、filename、sheet、rows。",
    "EX3-excel-export.png": "浏览器上下文校验产品导出 xlsx 的真实二进制字节数与 content-type。",
    "EX4-excel-negative.png": "浏览器渲染缺 data 参数的 400「请提供数据 data 参数」与旧导入接口 403 fail-closed。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 模板清单 → 生成 Excel → 导出二进制 → 负例。",
}