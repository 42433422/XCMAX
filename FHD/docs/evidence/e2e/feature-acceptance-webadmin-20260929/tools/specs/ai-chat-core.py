"""ai-chat-core（多轮智能对话 · 流式）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/ai_assistant.py、xcagi_compat_chat_stream.py。
真实接口面：/api/ai/chat、/api/ai/chat-unified（同一回合的兼容入口）、/api/ai/chat/stream（SSE 流）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "ai-chat-core"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "真实发起一轮对话（/api/ai/chat）得到助手回复与 run_id → "
    "经兼容入口 /api/ai/chat-unified 再发起一轮 → "
    "以 SSE 流式入口 /api/ai/chat/stream 观测真实事件流 → "
    "以真实 422 证明空消息被拒（边界/负例）。"
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
                return {status: r.status, body: j !== null ? j : t.slice(0,400), content_type: r.headers.get('content-type')||''};
            } catch(e) { return {status: 0, body: String(e), content_type:''}; }
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


def case_chat(page, env):
    r = _api(page, "/api/ai/chat", "POST", {"message": "你好"})
    b = r.get("body") or {}
    data = b.get("data") or {}
    ok = (r["status"] == 200 and b.get("success") is True
          and bool(b.get("response")) and bool(data.get("run_id")))
    body = {"status": r["status"], "success": b.get("success"), "response": b.get("response"),
            "run_id": data.get("run_id"), "action": data.get("action"),
            "intent": ((data.get("data") or {}).get("intent"))}
    _card(page, env, "C1-chat-core.png", "C1", "真实一轮对话：助手回复与 run_id",
          "POST /api/ai/chat {message:你好}", r["status"], body)
    return body, ok


def case_chat_unified(page, env):
    r = _api(page, "/api/ai/chat-unified", "POST", {"message": "你好"})
    b = r.get("body") or {}
    data = b.get("data") or {}
    ok = r["status"] == 200 and b.get("success") is True and bool(data.get("run_id"))
    return {"status": r["status"], "success": b.get("success"),
            "run_id": data.get("run_id"), "action": data.get("action")}, ok


def case_chat_stream(page, env):
    r = _api(page, "/api/ai/chat/stream", "POST", {"message": "你好"})
    text = r.get("body") if isinstance(r.get("body"), str) else ""
    ok = r["status"] == 200 and "data:" in text and ("tool_progress" in text or "error" in text or "message" in text)
    body = {"status": r["status"], "content_type": r.get("content_type"),
            "sse_head": text[:280]}
    _card(page, env, "C2-chat-stream.png", "C2", "SSE 流式对话入口真实下发事件流",
          "POST /api/ai/chat/stream {message:你好}", r["status"], body)
    return body, ok


def case_empty_message_denied(page, env):
    r = _api(page, "/api/ai/chat", "POST", {})
    b = r.get("body") or {}
    fields = [e.get("field") for e in (b.get("errors") or []) if isinstance(e, dict)]
    ok = r["status"] == 422 and b.get("error_code") == "validation_error" and "body.message" in fields
    body = {"status": r["status"], "error_code": b.get("error_code"), "fields": fields,
            "message": b.get("message")}
    _card(page, env, "C3-chat-boundary.png", "C3", "空消息被拒（边界/负例）",
          "POST /api/ai/chat {}", r["status"], body)
    return body, ok


CASES = [
    {"id": "C1", "title": "真实一轮对话得到助手回复与 run_id",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/ai/chat（message=你好）。",
     "expected": "HTTP 200、success=true，response 非空且返回 run_id。",
     "run": case_chat},
    {"id": "C2", "title": "兼容入口 chat-unified 同上应答",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/ai/chat-unified（message=你好）。",
     "expected": "HTTP 200、success=true 且返回 run_id。",
     "run": case_chat_unified},
    {"id": "C3", "title": "SSE 流式入口真实下发事件流",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/ai/chat/stream，读取事件流文本。",
     "expected": "HTTP 200，响应为 SSE（含 data: 事件），事件含 tool_progress / message / error 之一。",
     "run": case_chat_stream},
    {"id": "C4", "title": "空消息被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/ai/chat（空 body）。",
     "expected": "HTTP 422、error_code=validation_error，缺失字段 body.message。",
     "run": case_empty_message_denied},
]

VISIBLE_RESULTS = {
    "C1-chat-core.png": "卡片「C1 · 真实一轮对话：助手回复与 run_id」：POST /api/ai/chat {message:你好}，200，{\"status\":200,\"success\":true,\"response\":\"您好！我是 XCAGI 智能助手。您可以直接吩咐：开发货单、查产品/客户库存、打印标签、管理考勤人员，或上传 Excel 让我分析。请问有什么可以帮您？\",\"run_id\":\"run_b10de9e5627403c960143be697ce560f\",\"action\":\"greeting\",\"intent\":\"smalltalk_greeting\"}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，12.84s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → /api/ai/chat 一轮对话 → chat-unified → SSE 流式 → 空消息 422。"
}