"""ai-tts（语音合成与播报）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/ai_assistant_tts.py、voice_routes.py、tts_install.py。
真实接口面：/api/tts（真实合成音频，返回 audioBase64）、/api/voice/health（本地语音引擎健康）、
/api/tts/synthesize（FHD 兼容层，未启用时 fail-closed）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "ai-tts"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "真实合成一段中文语音（返回 data:audio/mpeg;base64）→ "
    "读取本地语音引擎健康（model=small, ready）→ "
    "读取未启用的兼容层返回 fail-closed → 以真实 400 证明空文本被拒（边界/负例）。"
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


def case_tts_synthesize(page, env):
    r = _api(page, "/api/tts", "POST", {"text": "验收语音合成测试"})
    b = r.get("body") or {}
    d = b.get("data") or {}
    audio = str(d.get("audioBase64") or "")
    ok = r["status"] == 200 and b.get("success") is True and audio.startswith("data:audio/") and len(audio) > 200
    body = {"status": r["status"], "success": b.get("success"), "message": b.get("message"),
            "audio_prefix": audio[:48], "audio_base64_len": len(audio)}
    _card(page, env, "T1-tts-synthesize.png", "T1", "真实合成中文语音（返回 base64 音频）",
          "POST /api/tts {text:验收语音合成测试}", r["status"], body)
    return body, ok


def case_voice_health(page, env):
    r = _api(page, "/api/voice/health")
    d = (r.get("body") or {}).get("data") or {}
    ok = r["status"] == 200 and d.get("ready") is True and bool(d.get("model"))
    return {"status": r["status"], "ready": d.get("ready"), "model": d.get("model"),
            "device_hint": d.get("device_hint")}, ok


def case_synthesize_compat_failclosed(page, env):
    r = _api(page, "/api/tts/synthesize", "POST", {"text": "验收"})
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is False and "未" in str(b.get("message"))
    body = {"status": r["status"], "success": b.get("success"), "message": b.get("message")}
    _card(page, env, "T2-tts-failclosed.png", "T2", "未启用的兼容层如实返回未启用（fail-closed）",
          "POST /api/tts/synthesize {text:验收}", r["status"], body)
    return body, ok


def case_empty_text_denied(page, env):
    r = _api(page, "/api/tts", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "text" in str(b.get("message"))
    body = {"status": r["status"], "message": b.get("message")}
    _card(page, env, "T3-tts-boundary.png", "T3", "空文本的语音合成被拒（边界/负例）",
          "POST /api/tts {}", r["status"], body)
    return body, ok


CASES = [
    {"id": "T1", "title": "真实合成中文语音并返回音频",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/tts（text=验收语音合成测试）。",
     "expected": "HTTP 200、success=true，data.audioBase64 为 data:audio/ 前缀的音频数据。",
     "run": case_tts_synthesize},
    {"id": "T2", "title": "本地语音引擎健康真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/voice/health。",
     "expected": "HTTP 200，ready=true，返回模型名（small）。",
     "run": case_voice_health},
    {"id": "T3", "title": "未启用的兼容层如实 fail-closed",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/tts/synthesize（text=验收）。",
     "expected": "HTTP 200 且 success=false，message 说明 TTS 未在兼容层启用（不伪装成功）。",
     "run": case_synthesize_compat_failclosed},
    {"id": "T4", "title": "空文本的语音合成被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/tts（空 body）。",
     "expected": "HTTP 400，message 为 text 不能为空。",
     "run": case_empty_text_denied},
]

VISIBLE_RESULTS = {
    "T1-tts-synthesize.png": "卡片「T1 · 真实合成中文语音（返回 base64 音频）」：POST /api/tts {text:验收语音合成测试}，200，{\"status\":200,\"success\":true,\"message\":\"ok\",\"audio_prefix\":\"data:audio/mpeg;base64,//NkxAAAN…\",\"audio_base64_len\":20375}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，12.64s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 真实合成语音 → 语音引擎健康 → 未启用兼容层 fail-closed → 空文本 400。"
}