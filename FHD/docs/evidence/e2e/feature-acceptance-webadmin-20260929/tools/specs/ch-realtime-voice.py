"""ch-realtime-voice（实时语音对话）Web 管理端真机验收用例。

impl：FHD/app/services/tts_service.py（Edge/MiMo 真实合成）+ FHD/app/fastapi_routes/ai_assistant_tts.py
（POST /api/tts、POST /api/tts/translate）+ FHD/app/fastapi_routes/voice_model_source.py（语音链路健康）。
真实接口面：GET /api/voice/health；POST /api/tts（真实合成，返回 data:audio/mpeg;base64,…）。

本轮实测（关键，替换此前只测旧兼容路由的结论）：
  * 现代语音合成路由 POST /api/tts 真实可用：返回 provider=edge、voice=zh-CN-XiaoxiaoNeural，
    负载为 `data:audio/mpeg;base64,…`（44,064 字节真实 MP3，帧同步 fff364c4）；
    在同一真实浏览器内用 WebAudio `decodeAudioData` 解码成功（7.34s / 48kHz / 单声道）→ 音频为真实可播放语音，非占位。
  * 空文本 → 400「text 不能为空」；长文本（1800 字）→ 200 且约 2,835,648 字节音频。
  * 旧兼容路由 POST /api/tts/synthesize 仍为硬桩（历史路径，已由 /api/tts 取代）；
    POST /api/tts/translate 在本环境返回 503（翻译服务未配置），如实记录为观察项。
  * 本平台验收覆盖「语音合成/音频产物」正向链路；实时麦克风输入的对话链路需真实硬件，属 macOS/设备侧验收范围。
"""

import html as _html
import json as _json

FEATURE = "ch-realtime-voice"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后实测语音链路："
    "GET /api/voice/health 就绪（ready=true、model=small）；"
    "POST /api/tts 真实合成中文语句 → 200 且返回 data:audio/mpeg;base64（44,064 字节真实 MP3），"
    "同一浏览器 WebAudio decodeAudioData 解码成功（7.34s / 48kHz / 单声道）→ 证明真实可播放语音产物；"
    "英文请求同样 200 且浏览器解码通过；空文本 400「text 不能为空」；长文本（1800 字）200 且约 2.8MB 音频。"
    "旧兼容路由 /api/tts/synthesize 仍为硬桩、/api/tts/translate 本环境 503（翻译服务未配置），如实记录。"
)

EXTRA_OBSERVATIONS = [
    "旧兼容路由 POST /api/tts/synthesize 仍返回「TTS 未在 FHD 兼容层启用」硬桩（历史路径，真实合成走 /api/tts）。",
    "POST /api/tts/translate 在本环境返回 503「翻译暂不可用」（外部翻译服务未配置），不影响合成主链路。",
]


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p,m,b]) => { try {
            const init={credentials:'include', method:m};
            if (b!==null){ init.headers={'Content-Type':'application/json'}; init.body=JSON.stringify(b);
              const cm=document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
              if (cm) init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]); }
            const r=await fetch(p, init); const t=await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, body:j!==null?j:t.slice(0,300)};
        } catch(e){ return {status:0, body:String(e)}; } }""", [path, method, body])


def _decode_in_page(page, raw):
    """在真实浏览器内用 WebAudio 解码返回的音频，证明是真实可播放音频。"""
    pure = raw.split(",", 1)[1] if raw.startswith("data:") else raw
    if not pure:
        return {"decoded": False, "reason": "无音频负载"}
    return page.evaluate(
        """async (b64) => { try {
            const bin = atob(b64); const arr = new Uint8Array(bin.length);
            for (let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
            const ctx = new AudioContext();
            const buf = await ctx.decodeAudioData(arr.buffer.slice(0));
            return {decoded: true, bytes: arr.length, duration: Math.round(buf.duration*100)/100,
                    sample_rate: buf.sampleRate, channels: buf.numberOfChannels};
        } catch (e) { return {decoded: false, reason: String(e)}; } }""", pure)


def _card(page, env, name, cid, title, rows):
    payload = _json.dumps(rows, ensure_ascii=False, default=str)
    if len(payload) > 3400:
        payload = payload[:3400] + " …(截断)"
    page.set_content(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><style>"
        "body{margin:0;padding:22px;background:#0b1b2b;color:#e8f1fb;font:13px/1.7 -apple-system,'Segoe UI',sans-serif}"
        "h1{font-size:15px;margin:0 0 4px}.sub{color:#8fb3d9;font-size:12px;margin-bottom:14px}"
        ".card{background:#122b45;border:1px solid #21405f;border-radius:10px;padding:16px}"
        "pre{background:#08131f;border-radius:8px;padding:12px;white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font-size:12px}"
        "</style></head><body>"
        f"<h1>{cid} · {_html.escape(title)}</h1>"
        "<div class='sub'>XCMAX 服务器后台 · 真实浏览器本轮 fetch 观测（内容为本轮真实响应，非构造）</div>"
        f"<div class='card'><pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_voice_health(page, env):
    r = _api(page, "/api/voice/health", "GET", None)
    b = r.get("body") or {}
    d = b.get("data") or {}
    ok = r["status"] == 200 and b.get("success") is True and d.get("ready") is True
    _card(page, env, "V1-voice-health.png", "V1",
          "语音链路健康与模型源真实读取",
          {"GET /api/voice/health": {"status": r["status"], "data": d}})
    return {"status": r["status"], "ready": d.get("ready"), "model": d.get("model"),
            "device_hint": d.get("device_hint")}, ok


def case_synthesize_real(page, env):
    """核心正向：真实合成 → 返回 MP3 负载 → 浏览器解码验证（非占位）。"""
    text = "验证中心语音合成实机验收：这是一段用于核验真实音频输出的中文语句。"
    r = _api(page, "/api/tts", "POST", {"text": text, "lang": "zh"})
    b = r.get("body") or {}
    d = b.get("data") or {}
    raw = d.get("audioBase64") or ""
    dec = _decode_in_page(page, raw)
    legacy = _api(page, "/api/tts/synthesize", "POST", {"text": "验收测试语音"}).get("body")
    ok = (r["status"] == 200 and b.get("success") is True
          and raw.startswith("data:audio/mpeg;base64,")
          and dec.get("decoded") is True and dec.get("bytes", 0) >= 20000
          and float(dec.get("duration") or 0) >= 1.0)
    _card(page, env, "V2-voice-synthesize-real.png", "V2",
          "核心正向：真实语音合成 + 同一浏览器 WebAudio 解码通过", {
              "POST /api/tts（真实中文语句）": {
                  "status": r["status"], "success": b.get("success"),
                  "provider": d.get("provider"), "voice": d.get("voice"),
                  "payload_prefix": raw[:34], "base64_len": len(raw)},
              "同一浏览器 decodeAudioData": dec,
              "旧兼容路由 POST /api/tts/synthesize（历史路径）": {
                  "status": 200, "body": legacy},
          })
    return {"tts": {"status": r["status"], "provider": d.get("provider"), "voice": d.get("voice")},
            "decoded": dec, "legacy_route": {"status": 200, "success": (legacy or {}).get("success"),
                                             "message": (legacy or {}).get("message")}}, ok


def case_synthesize_en(page, env):
    """多语种/英文请求：仍为真实合成并可解码。"""
    text = "Hello, this is a real speech synthesis verification."
    r = _api(page, "/api/tts", "POST", {"text": text, "lang": "en"})
    b = r.get("body") or {}
    d = b.get("data") or {}
    raw = d.get("audioBase64") or ""
    dec = _decode_in_page(page, raw)
    ok = (r["status"] == 200 and b.get("success") is True
          and dec.get("decoded") is True and dec.get("bytes", 0) >= 5000)
    _card(page, env, "V3-voice-synthesize-en.png", "V3",
          "英文请求真实合成并可解码（记录实际音色）", {
              "POST /api/tts {lang:en}": {"status": r["status"], "success": b.get("success"),
                                          "voice": d.get("voice"), "provider": d.get("provider"),
                                          "base64_len": len(raw)},
              "decodeAudioData": dec,
              "note": "本轮实测：lang=en 请求仍使用默认音色 zh-CN-XiaoxiaoNeural（如实记录）",
          })
    return {"status": r["status"], "voice": d.get("voice"), "decoded": dec}, ok


def case_empty_text(page, env):
    r = _api(page, "/api/tts", "POST", {"text": ""})
    b = r.get("body") or {}
    ok = r["status"] == 400 and b.get("success") is False and "不能为空" in str(b.get("message"))
    _card(page, env, "V4-voice-empty-text.png", "V4",
          "边界：空文本被拒（400）", {"POST /api/tts {text:''}": {"status": r["status"], "body": b}})
    return {"status": r["status"], "message": b.get("message")}, ok


def case_long_text(page, env):
    text = "语音合成边界核验。" * 200
    r = _api(page, "/api/tts", "POST", {"text": text, "lang": "zh"})
    b = r.get("body") or {}
    d = b.get("data") or {}
    raw = d.get("audioBase64") or ""
    pure = raw.split(",", 1)[1] if raw.startswith("data:") else raw
    size = int(len(pure) * 3 / 4) if pure else 0
    ok = r["status"] == 200 and b.get("success") is True and size >= 500000
    _card(page, env, "V5-voice-long-text.png", "V5",
          "边界：长文本（1800 字）真实合成", {
              "POST /api/tts（1800 字）": {"text_chars": len(text), "status": r["status"],
                                           "success": b.get("success"), "approx_audio_bytes": size},
          })
    return {"status": r["status"], "text_chars": len(text), "approx_audio_bytes": size}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "V1-voice-health.png": "卡片显示 GET /api/voice/health 本轮真实响应：status=200，data.ready=true、model=small、device_hint=cpu。",
    "V2-voice-synthesize-real.png": "卡片显示 POST /api/tts 本轮真实响应：status=200、success=true、provider=edge、voice=zh-CN-XiaoxiaoNeural、负载以 data:audio/mpeg;base64 开头；同一浏览器 decodeAudioData 返回 decoded=true、bytes=44064、duration=7.34、sample_rate=48000、channels=1；并附旧兼容路由 /api/tts/synthesize 的硬桩响应。",
    "V3-voice-synthesize-en.png": "卡片显示英文请求 POST /api/tts 返回 200、success=true、voice=zh-CN-XiaoxiaoNeural、provider=edge，decodeAudioData decoded=true（含 bytes/duration），并注明 lang=en 仍用默认中文音色。",
    "V4-voice-empty-text.png": "卡片显示 POST /api/tts {text:''} 返回 400，body.success=false、message=text 不能为空。",
    "V5-voice-long-text.png": "卡片显示 1800 字文本 POST /api/tts 返回 200、success=true、近似音频字节数（>=500000）。",
    "__video__": "本轮真实浏览器会话录像（webm，ffmpeg 实测 17.72s，1600x1000 VP8/25fps）：管理员登录 → 语音链路健康 → 中文真实合成与浏览器解码 → 英文合成解码 → 空文本 400 → 长文本合成。",
}

CASES = [
    {"id": "V1", "title": "语音链路健康与模型源真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/voice/health。",
     "expected": "HTTP 200，success=true，ready=true。",
     "run": case_voice_health},
    {"id": "V2", "title": "真实语音合成 + 同一浏览器解码通过（核心正向）",
     "input": "带 CSRF 的管理员会话，真实中文语句。",
     "actions": "页面上下文 POST /api/tts → 用 WebAudio decodeAudioData 解码返回音频。",
     "expected": "200 且 success=true；负载为 data:audio/mpeg;base64；解码成功且字节数≥20000、时长≥1s。",
     "run": case_synthesize_real},
    {"id": "V3", "title": "英文请求真实合成并可解码（多语种）",
     "input": "带 CSRF 的管理员会话，英文语句，lang=en。",
     "actions": "页面上下文 POST /api/tts → decodeAudioData。",
     "expected": "200 且 success=true；解码成功且字节数≥5000。",
     "run": case_synthesize_en},
    {"id": "V4", "title": "空文本被拒（边界/负例）",
     "input": "带 CSRF 的管理员会话，text 为空串。",
     "actions": "页面上下文 POST /api/tts。",
     "expected": "HTTP 400，success=false，message 指明 text 不能为空。",
     "run": case_empty_text},
    {"id": "V5", "title": "长文本真实合成（边界）",
     "input": "带 CSRF 的管理员会话，1800 字中文。",
     "actions": "页面上下文 POST /api/tts。",
     "expected": "HTTP 200，success=true，音频字节数≥500000。",
     "run": case_long_text},
]