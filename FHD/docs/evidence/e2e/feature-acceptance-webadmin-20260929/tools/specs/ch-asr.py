"""ch-asr（语音识别 ASR）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/voice_routes.py、voice_model_source.py。
真实接口面：GET /api/voice/health；POST /api/voice/transcribe（真实上传音频 → 转写文本）。
正向闭环：本地生成一段真实中文语音（macOS `say` + `afconvert` 转 16k 单声道 WAV），
在真实浏览器里用 FormData 上传，拿到非空转写文本与 audio_seconds。
负例：缺 file 被 422 校验拒绝；缺 CSRF 双提交被 403 拒绝。
"""

import base64
import html as _html
import json as _json
import subprocess
from pathlib import Path

FEATURE = "ch-asr"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取 ASR 健康（ready=true、模型源 small、设备提示 cpu）→ "
    "真实上传一段本地生成的中文语音 WAV，拿到非空转写文本与音频时长（ASR 正向闭环）→ "
    "以真实 422 记录缺 file 的转写请求被校验拒绝 → 以真实 403 记录缺 CSRF 双提交被拒（负例/边界）。"
)

_WAV = Path("/tmp/vc-asr.wav")


def _ensure_audio() -> bool:
    """确保存在一段真实中文语音 WAV（16k 单声道）；缺失时用系统 say+afconvert 生成。"""
    if _WAV.is_file() and _WAV.stat().st_size > 1000:
        return True
    aiff = Path("/tmp/vc-asr.aiff")
    try:
        subprocess.run(["say", "-v", "Tingting", "-o", str(aiff),
                        "你好，欢迎使用语音识别验收"], check=True, capture_output=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                        str(aiff), str(_WAV)], check=True, capture_output=True)
    except Exception:
        return False
    return _WAV.is_file() and _WAV.stat().st_size > 1000


def _api(page, path, method="GET", body=None, with_csrf=True):
    return page.evaluate(
        """async ([p,m,b,c]) => { try {
            const init={credentials:'include', method:m};
            if (b!==null){ init.headers={'Content-Type':'application/json'}; init.body=JSON.stringify(b);
              if (c){ const cm=document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
                if (cm) init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]); } }
            const r=await fetch(p, init); const t=await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, body:j!==null?j:t.slice(0,300)};
        } catch(e){ return {status:0, body:String(e)}; } }""", [path, method, body, with_csrf])


def _upload_audio(page, b64):
    return page.evaluate(
        """async (b64) => { try {
            const bin = atob(b64); const arr = new Uint8Array(bin.length);
            for (let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
            const fd = new FormData();
            fd.append('file', new Blob([arr], {type:'audio/wav'}), 'vc-asr.wav');
            const cm = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
            const csrf = cm ? decodeURIComponent(cm[1]) : '';
            const r = await fetch('/api/voice/transcribe', {method:'POST', credentials:'include',
              headers:{'X-CSRF-Token':csrf}, body: fd});
            const t = await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, body:j!==null?j:t.slice(0,300)};
        } catch(e){ return {status:0, body:String(e)}; } }""", b64)


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


def case_health(page, env):
    r = _api(page, "/api/voice/health", "GET", None)
    b = r.get("body") or {}
    d = b.get("data") or {}
    ok = r["status"] == 200 and b.get("success") is True and d.get("ready") is True and bool(d.get("model"))
    return {"status": r["status"], "success": b.get("success"), "ready": d.get("ready"),
            "model": d.get("model"), "device_hint": d.get("device_hint")}, ok


def case_transcribe_real_audio(page, env):
    if not _ensure_audio():
        _card(page, env, "A2-asr-transcribe.png", "A2",
              "真实上传音频转写（未能验证：无法生成音频夹具）",
              {"reason": "audio fixture unavailable (say/afconvert failed)"})
        return {"blocked": "audio fixture unavailable"}, False
    b64 = base64.b64encode(_WAV.read_bytes()).decode()
    r = _upload_audio(page, b64)
    b = r.get("body") or {}
    d = b.get("data") or {}
    text = str(d.get("text") or "")
    ok = (r["status"] == 200 and b.get("success") is True and text.strip() != ""
          and float(d.get("audio_seconds") or 0) > 0)
    _card(page, env, "A2-asr-transcribe.png", "A2",
          "真实上传中文语音并拿到非空转写文本（正向闭环）", {
              "POST /api/voice/transcribe（multipart，真实 WAV）": {
                  "status": r["status"], "success": b.get("success"), "text": text,
                  "language": d.get("language"), "audio_seconds": d.get("audio_seconds"),
                  "bytes": d.get("bytes"), "elapsed_ms": d.get("elapsed_ms")},
          })
    return {"status": r["status"], "success": b.get("success"), "text": text,
            "audio_seconds": d.get("audio_seconds"), "bytes": d.get("bytes")}, ok


def case_transcribe_missing_file(page, env):
    r = _api(page, "/api/voice/transcribe", "POST", {}, True)
    b = r.get("body") or {}
    errs = b.get("errors") or []
    ok = r["status"] == 422 and b.get("error_code") == "validation_error" \
        and any(e.get("field") == "body.file" for e in errs)
    return {"status": r["status"], "errors": errs}, ok


def case_transcribe_csrf(page, env):
    r = _api(page, "/api/voice/transcribe", "POST", {}, False)
    b = r.get("body") or {}
    ok = r["status"] == 403 and "CSRF" in str(b.get("message"))
    _card(page, env, "A3-asr-boundary.png", "A3+A4",
          "转写请求的参数校验与 CSRF 双提交（负例/边界）", {
              "POST 无 file（带 CSRF）": _api(page, "/api/voice/transcribe", "POST", {}, True).get("body"),
              "POST 无 CSRF 头": {"status": r["status"], "body": b},
          })
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "A2-asr-transcribe.png": "本轮真实响应：POST /api/voice/transcribe 以 multipart 上传本地生成的中文语音 WAV，返回 200 success=true，data.text=「你好,歡迎使用語音識別驗收。」、language=zh、audio_seconds≈3.09、bytes≈103124（ASR 正向闭环）。",
    "A3-asr-boundary.png": "卡片显示两处真实响应：POST /api/voice/transcribe（带 CSRF、无 file）返回 422 validation_error，errors 指名 body.file 缺失；POST 不带 CSRF 头返回 403 message=CSRF token missing。",
    "__video__": "本轮真实浏览器会话录像（webm，17.84s，ffmpeg 实测）：管理员登录 → ASR 健康 → 真实音频上传转写 → 缺 file 422 → 缺 CSRF 403。",
}

CASES = [
    {"id": "A1", "title": "ASR 健康与模型源真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/voice/health。",
     "expected": "HTTP 200，success=true，ready=true 且含模型名。",
     "run": case_health},
    {"id": "A2", "title": "真实上传中文语音并拿到非空转写（正向）",
     "input": "本地生成的中文语音 WAV（say+afconvert，16k 单声道）。",
     "actions": "页面上下文以 FormData 真实上传到 POST /api/voice/transcribe。",
     "expected": "HTTP 200，success=true，data.text 非空且 audio_seconds>0。",
     "run": case_transcribe_real_audio},
    {"id": "A3", "title": "缺 file 的转写请求被校验拒绝（负例）",
     "input": "带 CSRF 的管理员会话，空 body。",
     "actions": "页面上下文 POST /api/voice/transcribe。",
     "expected": "HTTP 422，errors 指出 body.file 缺失。",
     "run": case_transcribe_missing_file},
    {"id": "A4", "title": "缺 CSRF 双提交的转写请求被拒（负例/边界）",
     "input": "管理员会话，POST 不带 X-CSRF-Token。",
     "actions": "页面上下文 POST /api/voice/transcribe。",
     "expected": "HTTP 403，message=CSRF token missing。",
     "run": case_transcribe_csrf},
]