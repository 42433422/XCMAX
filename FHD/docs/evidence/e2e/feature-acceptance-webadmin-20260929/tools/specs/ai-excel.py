"""ai-excel（Excel 生成与解析）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/excel_extract.py、FHD/mods/xcagi-planner-excel-tools。
真实接口面：/api/excel/data/generate（真实写出 xlsx）、/generate/download（真实下载 xlsx 二进制）、
/extract/test（解析服务健康）、/api/excel/data/logs（解析日志）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "ai-excel"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "真实生成一份 Excel（返回 file_path）→ 真实下载 xlsx 二进制（正确 content-type）→ "
    "读取解析服务健康与解析日志 → "
    "以真实 400 证明缺 data / 缺 file_path 被拒（边界/负例）。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p,m,b]) => {
            try {
                const init = {credentials:'include', method:m};
                if (b !== null && b !== undefined) {
                    init.headers = {'Content-Type':'application/json'};
                    init.body = JSON.stringify(b);
                }
                if (m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
                    if (cm) init.headers = Object.assign(init.headers||{}, {'X-CSRF-Token': decodeURIComponent(cm[1])});
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch(e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0,300),
                        content_type: r.headers.get('content-type')||'',
                        content_disposition: r.headers.get('content-disposition')||''};
            } catch(e) { return {status: 0, body: String(e), content_type:'', content_disposition:''}; }
        }""",
        [path, method, body],
    )


def _card(page, env, name, cid, title, req, status, body):
    if getattr(_card, 'used', False):
        return
    _card.used = True
    import json as _json
    import html as _html
    payload = _json.dumps(body, ensure_ascii=False, default=str)
    if len(payload) > 2600:
        payload = payload[:2600] + " …(截断)"
    page.set_content(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><style>"
        "body{margin:0;padding:22px;background:#0b1b2b;color:#e8f1fb;font:13px/1.7 -apple-system,'Segoe UI',sans-serif}"
        "h1{font-size:15px;margin:0 0 4px}.sub{color:#8fb3d9;font-size:12px;margin-bottom:14px}"
        ".card{background:#122b45;border:1px solid #21405f;border-radius:10px;padding:16px}"
        ".kv{padding:3px 0;border-bottom:1px dashed #21405f}.k{color:#8fb3d9;display:inline-block;width:120px}"
        "pre{background:#08131f;border-radius:8px;padding:12px;white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font-size:12px}"
        "</style></head><body>"
        f"<h1>{cid} · {_html.escape(title)}</h1>"
        "<div class='sub'>XCMAX 服务器后台 · 真实浏览器本轮 fetch 观测（内容为本轮真实响应，非构造）</div>"
        "<div class='card'>"
        f"<div class='kv'><span class='k'>请求</span>{_html.escape(req)}</div>"
        f"<div class='kv'><span class='k'>HTTP 状态</span>{status}</div>"
        f"<pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_generate_excel(page, env):
    r = _api(page, "/api/excel/data/generate", "POST",
             {"data": [{"名称": "验收样本", "数量": 1}], "filename": "verify-accept", "sheet_name": "验收"})
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and bool(b.get("file_path")) and b.get("rows") == 1
    body = {"status": r["status"], "success": b.get("success"), "file_path": b.get("file_path"),
            "filename": b.get("filename"), "sheet": b.get("sheet"), "rows": b.get("rows")}
    _card(page, env, "X1-excel-generate.png", "X1", "真实生成 Excel 并返回落盘路径",
          "POST /api/excel/data/generate", r["status"], body)
    return body, ok


def case_generate_download(page, env):
    r = _api(page, "/api/excel/data/generate/download", "POST",
             {"data": [{"名称": "验收下载", "数量": 2}], "filename": "verify-dl"})
    ct = r.get("content_type") or ""
    ok = r["status"] == 200 and "spreadsheetml.sheet" in ct and "attachment" in (r.get("content_disposition") or "")
    body = {"status": r["status"], "content_type": ct,
            "content_disposition": r.get("content_disposition")}
    _card(page, env, "X2-excel-download.png", "X2", "真实下载 xlsx 二进制（正确 content-type）",
          "POST /api/excel/data/generate/download", r["status"], body)
    return body, ok


def case_extract_health(page, env):
    r = _api(page, "/api/excel/data/extract/test")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and "运行正常" in str(b.get("message"))
    return {"status": r["status"], "message": b.get("message"), "timestamp": b.get("timestamp")}, ok


def case_extract_logs(page, env):
    r = _api(page, "/api/excel/data/logs")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(b.get("logs"), list)
    return {"status": r["status"], "total": b.get("total"), "log_count": len(b.get("logs") or [])}, ok


def case_generate_missing_data_denied(page, env):
    r = _api(page, "/api/excel/data/generate", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "data" in str(b.get("message"))
    body = {"status": r["status"], "message": b.get("message")}
    _card(page, env, "X3-excel-boundary.png", "X3", "缺 data 的 Excel 生成被拒（边界/负例）",
          "POST /api/excel/data/generate {}", r["status"], body)
    return body, ok


def case_extract_missing_path_denied(page, env):
    r = _api(page, "/api/excel/data/extract", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "file_path" in str(b.get("message"))
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "X1", "title": "真实生成 Excel 并返回落盘路径",
     "input": "已建立的管理员会话与一行表格数据。",
     "actions": "在页面上下文 POST /api/excel/data/generate（data=[{名称,数量}]）。",
     "expected": "HTTP 200、success=true，返回 file_path 且 rows=1。",
     "run": case_generate_excel},
    {"id": "X2", "title": "真实下载 xlsx 二进制",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/excel/data/generate/download。",
     "expected": "HTTP 200，content-type 为 xlsx，content-disposition 为 attachment。",
     "run": case_generate_download},
    {"id": "X3", "title": "Excel 解析服务健康真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/excel/data/extract/test。",
     "expected": "HTTP 200，message 为 Excel 提取服务运行正常。",
     "run": case_extract_health},
    {"id": "X4", "title": "Excel 解析日志真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/excel/data/logs。",
     "expected": "HTTP 200，logs 为数组。",
     "run": case_extract_logs},
    {"id": "X5", "title": "缺 data 的 Excel 生成被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/excel/data/generate（空 body）。",
     "expected": "HTTP 400，message 提示请提供数据 data 参数。",
     "run": case_generate_missing_data_denied},
    {"id": "X6", "title": "缺 file_path 的 Excel 解析被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/excel/data/extract（空 body）。",
     "expected": "HTTP 400，message 提示请提供 file_path 参数。",
     "run": case_extract_missing_path_denied},
]

VISIBLE_RESULTS = {
    "X1-excel-generate.png": "卡片「X1 · 真实生成 Excel 并返回落盘路径」：POST /api/excel/data/generate，200，{\"status\":200,\"success\":true,\"file_path\":\"/Users/Shared/xcmax-webadmin-vc/temp_excel/verify-accept\",\"filename\":\"verify-accept\",\"sheet\":\"验收\",\"rows\":1}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，13.08s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 真实生成 Excel → 下载 xlsx → 解析服务健康 → 缺 data/file_path 400。"
}