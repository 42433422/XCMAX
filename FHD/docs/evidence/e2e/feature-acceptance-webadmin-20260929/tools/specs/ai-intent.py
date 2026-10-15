"""ai-intent（意图识别与工具路由）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/ai_intent.py、FHD/app/ai_engines/deepseek/intent_service.py。
真实接口面：/api/intent/health（引擎健康）、/api/intent/predict（真实意图分类与概率分布）、
/api/intent-packages（意图包目录）、/api/ai/intent/test（兼容入口）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "ai-intent"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取意图引擎健康 → 对「帮我生成一张出货单」真实分类出 intent 与各候选概率 → "
    "读取意图包目录 → 以真实 400 证明缺 text 与空消息被拒（边界/负例）。"
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
                return {status: r.status, body: j !== null ? j : t.slice(0,300)};
            } catch(e) { return {status: 0, body: String(e)}; }
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


def case_intent_health(page, env):
    r = _api(page, "/api/intent/health")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("status") == "ok"
    body = {"status": r["status"], "engine_status": b.get("status"),
            "model_available": b.get("model_available")}
    _card(page, env, "N1-intent-health.png", "N1", "意图引擎健康真实读取",
          "GET /api/intent/health", r["status"], body)
    return body, ok


def case_intent_predict(page, env):
    r = _api(page, "/api/intent/predict", "POST", {"text": "帮我生成一张出货单"})
    b = r.get("body") or {}
    probs = b.get("all_probs") or {}
    ok = (r["status"] == 200 and bool(b.get("intent"))
          and isinstance(b.get("confidence"), (int, float)) and len(probs) > 0)
    body = {"status": r["status"], "text": b.get("text"), "intent": b.get("intent"),
            "confidence": b.get("confidence"), "model": b.get("model"),
            "top_probs": dict(sorted(probs.items(), key=lambda kv: -kv[1])[:5])}
    _card(page, env, "N2-intent-predict.png", "N2", "真实意图分类与候选概率分布",
          "POST /api/intent/predict {text:帮我生成一张出货单}", r["status"], body)
    return body, ok


def case_intent_packages(page, env):
    r = _api(page, "/api/intent-packages")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(b.get("data"), list)
    return {"status": r["status"], "success": b.get("success"),
            "package_count": len(b.get("data") or [])}, ok


def case_predict_missing_text_denied(page, env):
    r = _api(page, "/api/intent/predict", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "text is required" in str(b.get("error"))
    body = {"status": r["status"], "error": b.get("error")}
    _card(page, env, "N3-intent-boundary.png", "N3", "缺 text 的意图预测被拒（边界/负例）",
          "POST /api/intent/predict {}", r["status"], body)
    return body, ok


def case_intent_test_empty_denied(page, env):
    r = _api(page, "/api/ai/intent/test", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "消息内容不能为空" in str(b.get("message"))
    return {"status": r["status"], "message": b.get("message")}, ok


CASES = [
    {"id": "N1", "title": "意图引擎健康真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/intent/health。",
     "expected": "HTTP 200，status=ok。",
     "run": case_intent_health},
    {"id": "N2", "title": "真实意图分类与候选概率",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/intent/predict（text=帮我生成一张出货单）。",
     "expected": "HTTP 200，返回 intent、confidence 数值与 all_probs 概率分布（非空）。",
     "run": case_intent_predict},
    {"id": "N3", "title": "意图包目录真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/intent-packages。",
     "expected": "HTTP 200、success=true，data 为数组。",
     "run": case_intent_packages},
    {"id": "N4", "title": "缺 text 的意图预测被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/intent/predict（空 body）。",
     "expected": "HTTP 400，error=text is required。",
     "run": case_predict_missing_text_denied},
    {"id": "N5", "title": "兼容入口空消息被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/ai/intent/test（空 body）。",
     "expected": "HTTP 400，message 为消息内容不能为空。",
     "run": case_intent_test_empty_denied},
]

VISIBLE_RESULTS = {
    "N1-intent-health.png": "卡片「N1 · 意图引擎健康真实读取」：GET /api/intent/health，200，{\"status\":200,\"engine_status\":\"ok\",\"model_available\":false}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，12.8s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 意图引擎健康 → 意图分类与概率 → 意图包目录 → 缺 text 400。"
}