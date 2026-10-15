"""erp-ocr-clean（识别结果清洗与入库）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的 OCR 结果结构化清洗面。
impl：FHD/app/application/ocr_app_service.py（/api/ocr/extract|analyze|recognize-and-extract）。
真实验证面：文本结构化提取 → 字段分析 → 图像识别+提取闭环；并含空文本被 400 拒绝（负例）。
所有请求均在真实浏览器页面上下文发起。
"""

FEATURE = "erp-ocr-clean"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端对识别文本做结构化清洗：POST /api/ocr/extract 提取结构化字段 → "
    "POST /api/ocr/analyze 分析文本类型/缺失字段 → 页面内 canvas 绘制的文档图 POST /api/ocr/recognize-and-extract "
    "完成识别+提取闭环；并含空文本 400（负例）。"
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


def _ocr_upload(page, path, lines):
    return page.evaluate(
        "async ([p, lines]) => { try {"
        " const c=document.createElement('canvas'); c.width=760; c.height=60+lines.length*60;"
        " const g=c.getContext('2d'); g.fillStyle='#fff'; g.fillRect(0,0,c.width,c.height);"
        " g.fillStyle='#000'; g.font='40px Arial';"
        " lines.forEach((t,i)=>g.fillText(t,20,55+i*60));"
        " const blob=await new Promise(res=>c.toBlob(res,'image/png'));"
        " const fd=new FormData(); fd.append('image', blob, 'vc-ocr-clean.png');"
        " const headers={}; const cm=document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);"
        " if(cm)headers['X-CSRF-Token']=decodeURIComponent(cm[1]);"
        " const r=await fetch(p,{method:'POST',credentials:'include',headers,body:fd});"
        " const t=await r.text(); let j=null; try{ j=JSON.parse(t);}catch(e){}"
        " return {status:r.status, body:j!==null?j:t.slice(0,240)};"
        " } catch(e){ return {status:0, body:String(e)}; } }", [path, lines])


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


def case_extract(page, env):
    r = _api(page, "/api/ocr/extract", method="POST",
             body={"text": "购买单位：张三商贸 联系人：李四 电话：13800000000 采购日期：2026-09-29 金额：100.00"})
    b = r.get("body") or {}
    d = b.get("data") or {}
    _panel(page, env, "OCC1-ocr-extract.png",
           "POST /api/ocr/extract · 识别文本结构化提取",
           {"status": r["status"], "success": b.get("success"), "message": b.get("message"),
            "structured_keys": sorted(d.keys()) if isinstance(d, dict) else None,
            "purchase_unit": d.get("purchase_unit"), "contact_person": d.get("contact_person"),
            "contact_phone": d.get("contact_phone"), "purchase_date": d.get("purchase_date"),
            "total_amount": d.get("total_amount"), "raw_text": str(d.get("raw_text"))[:120]})
    ok = (r["status"] == 200 and b.get("success") is True and isinstance(d, dict)
          and "raw_text" in d and "products" in d)
    return {"status": r["status"], "structured_keys": sorted(d.keys()) if isinstance(d, dict) else None,
            "raw_text": str(d.get("raw_text"))[:120]}, ok


def case_analyze(page, env):
    r = _api(page, "/api/ocr/analyze", method="POST",
             body={"text": "发票号码 12345678 金额 100.00"})
    b = r.get("body") or {}
    d = b.get("data") or {}
    _panel(page, env, "OCC2-ocr-analyze.png",
           "POST /api/ocr/analyze · 文本类型与缺失字段分析",
           {"status": r["status"], "success": b.get("success"), "text_type": d.get("text_type"),
            "confidence": d.get("confidence"), "missing_fields": d.get("missing_fields"),
            "suggestions": d.get("suggestions")})
    ok = r["status"] == 200 and b.get("success") is True and bool(d.get("text_type"))
    return {"status": r["status"], "text_type": d.get("text_type"), "confidence": d.get("confidence"),
            "missing_fields": d.get("missing_fields")}, ok


def case_recognize_and_extract(page, env):
    up = _ocr_upload(page, "/api/ocr/recognize-and-extract",
                     ["PURCHASE UNIT ACME", "CONTACT JOHN 13800000000", "TOTAL CNY 100.00"])
    b = up.get("body") or {}
    d = b.get("data") or {}
    _panel(page, env, "OCC3-ocr-recognize-extract.png",
           "POST /api/ocr/recognize-and-extract · 识别+提取闭环",
           {"status": up["status"], "success": b.get("success"), "message": b.get("message"),
            "text": str(b.get("text"))[:160], "data_keys": sorted(d.keys()) if isinstance(d, dict) else None,
            "analysis": b.get("analysis")})
    ok = (up["status"] == 200 and b.get("success") is True and bool(b.get("text"))
          and isinstance(d, dict) and "raw_text" in d)
    return {"status": up["status"], "text": str(b.get("text"))[:120],
            "data_keys": sorted(d.keys()) if isinstance(d, dict) else None}, ok


def case_negative(page, env):
    r = _api(page, "/api/ocr/extract", method="POST", body={"text": ""})
    b = r.get("body") or {}
    _panel(page, env, "OCC4-ocr-clean-negative.png",
           "空文本被拒（负例）", r)
    ok = r["status"] == 400 and "文本" in str(b.get("message"))
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "OCC1", "title": "识别文本结构化提取",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/ocr/extract（含购买单位/联系人/金额的文本）。",
     "expected": "200、success=true，返回结构化字段集合（含 raw_text/products）。",
     "run": case_extract},
    {"id": "OCC2", "title": "文本类型与缺失字段分析",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/ocr/analyze。",
     "expected": "200、success=true，返回 text_type/confidence/missing_fields。",
     "run": case_analyze},
    {"id": "OCC3", "title": "图像识别+提取闭环",
     "input": "已建立的管理员会话；页面内 canvas 绘制文档图。",
     "actions": "multipart POST /api/ocr/recognize-and-extract。",
     "expected": "200、success=true，返回识别文本与结构化 data。",
     "run": case_recognize_and_extract},
    {"id": "OCC4", "title": "空文本被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/ocr/extract（text 为空）。",
     "expected": "400「文本不能为空」。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "OCC1-ocr-extract.png": "浏览器渲染文本结构化提取真实 JSON：success=true、结构化字段键、raw_text。",
    "OCC2-ocr-analyze.png": "浏览器渲染文本分析真实 JSON：text_type、confidence、missing_fields。",
    "OCC3-ocr-recognize-extract.png": "浏览器渲染识别+提取闭环真实 JSON：识别文本、结构化 data 与 analysis。",
    "OCC4-ocr-clean-negative.png": "浏览器渲染空文本的 400「文本不能为空」。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 文本提取 → 文本分析 → 识别+提取闭环 → 负例。",
}