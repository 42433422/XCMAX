"""ch-realtime-voice（实时语音对话）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/voice_model_source.py（语音模型源解析）+ 语音链路 /api/voice/health、/api/tts/*。
真实接口面：GET /api/voice/health；POST /api/tts/synthesize；POST /api/tts/translate。

结论（如实）：实时语音合成的核心正向路径在本产品面【不存在 / 未能验证】：
  * POST /api/tts/synthesize 为硬桩（FHD/app/legacy/routes/conversation/compat_routes.py 直接返回
    「TTS 未在 FHD 兼容层启用」，success=false，无音频产物）；
  * 实时语音对话还需麦克风硬件与 WS 音频流，本环境（无麦克风）不可验证。
故核心正向用例 V0 如实判为失败（不登记为 PASS）。
"""

import html as _html
import json as _json

FEATURE = "ch-realtime-voice"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取语音链路健康与模型源（ready=true、model=small，可读）；"
    "尝试语音合成 → 硬桩返回 success=false「TTS 未在 FHD 兼容层启用」，无音频产物；"
    "翻译链路 503「翻译暂不可用」。"
    "核心实时语音合成正向路径在本产品面不存在（硬桩）且需麦克风硬件，本轮【未能验证】，不登记为 PASS。"
)


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
          {"GET /api/voice/health": {"status": r["status"], "ready": d.get("ready"),
                                     "model": d.get("model"), "device_hint": d.get("device_hint")}})
    return {"status": r["status"], "ready": d.get("ready"), "model": d.get("model")}, ok


def case_synthesize_core(page, env):
    """核心正向：期望真实合成音频；实测硬桩 → 如实判失败（未能验证）。"""
    r = _api(page, "/api/tts/synthesize", "POST", {"text": "验收测试语音"})
    b = r.get("body") or {}
    core_ok = r["status"] == 200 and b.get("success") is True and bool(b.get("data") or b.get("audio"))
    _card(page, env, "V2-voice-core-unverified.png", "V2",
          "实时语音合成核心正向【未能验证】：TTS 硬桩 + 需麦克风硬件", {
              "POST /api/tts/synthesize {text}": {"status": r["status"], "body": b},
              "POST /api/tts/translate {text}": _api(page, "/api/tts/translate", "POST", {"text": "hello"}).get("body"),
              "core_unverified_reason": "TTS 硬桩（compat_routes 直接返回未启用，无音频产物）；实时语音对话需麦克风硬件",
          })
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message"),
            "core_unverified": True}, core_ok


def case_tts_translate(page, env):
    r = _api(page, "/api/tts/translate", "POST", {"text": "hello"})
    b = r.get("body") or {}
    ok = r["status"] == 503 and b.get("success") is False
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "V1-voice-health.png": "本轮响应：GET /api/voice/health 返回 200，data.ready=true、model=small、device_hint=cpu（语音链路与模型源就绪）。",
    "V2-voice-core-unverified.png": "卡片显示：POST /api/tts/synthesize 返回 200 但 success=false、message=TTS 未在 FHD 兼容层启用（硬桩，无音频产物）；POST /api/tts/translate 返回 503 翻译暂不可用。核心实时语音合成正向路径【未能验证】。",
    "__video__": "本轮真实浏览器会话录像（webm，15.32s，ffmpeg 实测）：管理员登录 → 语音健康 → 合成硬桩未启用 → 翻译 503。核心正向未验证。",
}

CASES = [
    {"id": "V1", "title": "语音链路健康与模型源真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/voice/health。",
     "expected": "HTTP 200，success=true，ready=true。",
     "run": case_voice_health},
    {"id": "V0", "title": "实时语音合成核心正向【未能验证】（硬桩 + 需麦克风）",
     "input": "带 CSRF 的管理员会话，text=验收测试语音。",
     "actions": "页面上下文 POST /api/tts/synthesize，期望真实音频产物。",
     "expected": "（核心）HTTP 200 success=true 且返回音频；实测为硬桩 success=false，判为失败/未验证。",
     "run": case_synthesize_core},
    {"id": "V2", "title": "翻译链路不可用时 fail-closed（观察项）",
     "input": "带 CSRF 的管理员会话，text=hello。",
     "actions": "页面上下文 POST /api/tts/translate。",
     "expected": "HTTP 503，success=false。",
     "run": case_tts_translate},
]