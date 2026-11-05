"""erp-ocr（OCR 单据识别）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的 OCR 识别面。
impl：FHD/app/services/ocr_service.py、FHD/app/application/ocr_app_service.py（/api/ocr/*）。
真实验证面：OCR 服务健康读取（真实后端 macos_vision）→ 浏览器内绘制真实文本文档图并 multipart 上传识别，
读回真实识别文本；并含未提供图像被 400 拒绝（负例）。所有请求在真实浏览器页面上下文发起。
"""

FEATURE = "erp-ocr"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端读取 OCR 服务健康（active_backend=macos_vision）→ 页面内用 canvas 绘制含"
    "「INVOICE NO 12345678 / TOTAL CNY 100.00」的真实文档图并以 multipart 上传 POST /api/ocr/recognize → "
    "读回真实识别文本；并含未提供图像的 400（负例）。"
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
        " const fd=new FormData(); fd.append('image', blob, 'vc-ocr.png');"
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


def case_health(page, env):
    r = _api(page, "/api/ocr/test")
    b = r.get("body") or {}
    _panel(page, env, "OC1-ocr-health.png",
           "GET /api/ocr/test · OCR 服务健康", r)
    ok = r["status"] == 200 and b.get("success") is True and bool(b.get("active_backend"))
    return {"status": r["status"], "active_backend": b.get("active_backend"), "message": b.get("message")}, ok


def case_recognize_upload(page, env):
    up = _ocr_upload(page, "/api/ocr/recognize", ["INVOICE NO 12345678", "TOTAL CNY 100.00"])
    b = up.get("body") or {}
    text = str(b.get("text") or "")
    _panel(page, env, "OC2-ocr-recognize.png",
           "POST /api/ocr/recognize · 真实上传文档图并识别",
           {"status": up["status"], "success": b.get("success"), "message": b.get("message"),
            "recognized_text": text[:200], "has_no": "12345678" in text, "has_total": "100.00" in text,
            "file_path": b.get("file_path"), "run_id": b.get("run_id")})
    ok = (up["status"] == 200 and b.get("success") is True
          and "12345678" in text and "100.00" in text)
    return {"status": up["status"], "recognized_text": text[:160], "has_no": "12345678" in text,
            "has_total": "100.00" in text, "file_path": b.get("file_path")}, ok


def case_negative(page, env):
    r = _api(page, "/api/ocr/recognize", method="POST", body={})
    b = r.get("body") or {}
    _panel(page, env, "OC3-ocr-negative.png",
           "未提供图像被拒（负例）", r)
    ok = r["status"] == 400 and "图像" in str(b.get("message"))
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "OC1", "title": "OCR 服务健康真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/ocr/test。",
     "expected": "200、success=true，返回 active_backend（macos_vision）。",
     "run": case_health},
    {"id": "OC2", "title": "真实上传文档图并识别（写-读回）",
     "input": "已建立的管理员会话；页面内 canvas 绘制的真实文档图。",
     "actions": "multipart POST /api/ocr/recognize（image 文件）。",
     "expected": "200、success=true，识别文本包含 12345678 与 100.00。",
     "run": case_recognize_upload},
    {"id": "OC3", "title": "未提供图像被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/ocr/recognize（无文件）。",
     "expected": "400「请提供图像文件或文件路径」。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "OC1-ocr-health.png": "浏览器渲染 OCR 服务健康真实 JSON：message「OCR服务运行正常」、active_backend=macos_vision。",
    "OC2-ocr-recognize.png": "浏览器渲染真实上传与识别结果：200、识别文本含 INVOICE NO 12345678 / TOTAL CNY 100.00、file_path 与 run_id。",
    "OC3-ocr-negative.png": "浏览器渲染未提供图像的 400「请上传图片文件或文件路径」拒绝。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → OCR 健康 → 真实文档图上传识别 → 负例。",
}