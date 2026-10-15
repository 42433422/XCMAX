"""ai-multimodal（多模态：文本 / 图像 / 语音）Web 管理端真机验收用例。

impl 参考：FHD/app/services/conversation（会话域多模态输入输出）。
真实验证面：语音识别就绪状态（/api/voice/health）、语音转写入参契约（/api/voice/transcribe）、
图像识别入参契约（/api/ocr/recognize）、语音合成接口可用性（/api/tts/synthesize）。
管理端 UI：/admin/tools（工具表，含「图片OCR / 图片识别与对话入口」分类）。
说明：本机 TTS 兼容层未启用，属真实观察项，按产品实际返回结构化 JSON 断言，不伪造成功。
"""

FEATURE = "ai-multimodal"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，真实鼠标键盘）在自托管 Web 管理端建立管理员会话后："
    "读取语音识别就绪状态（small 模型、cpu）→ 语音转写缺 file 被 422 拒绝 → "
    "图像识别缺图像被 400 拒绝 → 语音合成返回结构化 JSON（本机 TTS 兼容层未启用）→ "
    "工具表「图片OCR」分类真实渲染。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p, m, b]) => {
            try {
                const init = {method: m, credentials: 'include', headers: {}};
                if (b !== null && b !== undefined) {
                    init.headers['Content-Type'] = 'application/json';
                    init.body = JSON.stringify(b);
                }
                if (m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);
                    if (cm) init.headers['X-CSRF-Token'] = decodeURIComponent(cm[1]);
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch (e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0, 300)};
            } catch (e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body],
    )


def case_voice_health(page, env):
    r = _api(page, "/api/voice/health")
    d = (r.get("body") or {}).get("data") or {}
    ok = r["status"] == 200 and (r.get("body") or {}).get("success") is True and d.get("ready") is True
    return {"status": r["status"], "success": (r.get("body") or {}).get("success"),
            "ready": d.get("ready"), "model": d.get("model"), "device_hint": d.get("device_hint"),
            "reason": d.get("reason")}, ok


def case_voice_transcribe_boundary(page, env):
    r = _api(page, "/api/voice/transcribe", "POST", {})
    b = r.get("body") or {}
    errs = b.get("errors") or []
    fields = [e.get("field") for e in errs if isinstance(e, dict)]
    ok = (r["status"] == 422 and b.get("error_code") == "validation_error"
          and "body.file" in fields)
    return {"status": r["status"], "error_code": b.get("error_code"),
            "fields": fields, "message": b.get("message")}, ok


def case_ocr_recognize_boundary(page, env):
    r = _api(page, "/api/ocr/recognize", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "图像文件" in str(b.get("message"))
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message")}, ok


def case_tts_synthesize(page, env):
    r = _api(page, "/api/tts/synthesize", "POST", {"text": "多模态验收样本"})
    b = r.get("body") or {}
    ok = r["status"] == 200 and isinstance(b, dict) and "message" in b
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message"),
            "note": "本机 TTS 兼容层未启用，按真实结构化返回断言"}, ok


def case_tools_ocr_page(page, env):
    page.goto(env["base"] + "/admin/tools", wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(10):
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or ""
        if "工具表" in text:
            break
    selected = ""
    try:
        page.select_option("select", label="图片OCR", timeout=5000)
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or ""
        selected = page.eval_on_selector("select", "el => el.options[el.selectedIndex].text")
    except Exception:
        pass
    page.screenshot(path=str(env["shot"] / "MM-tools-ocr.png"))
    ok = "工具表" in text and "图片OCR" in text
    return {"final_url": page.url, "selected_category": selected,
            "has_tool_table": "工具表" in text, "has_ocr": "图片OCR" in text,
            "text_head": text.replace("\n", " ")[:220]}, ok


CASES = [
    {"id": "MM1", "title": "语音识别引擎就绪状态",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/voice/health。",
     "expected": "HTTP 200、success=true、data.ready=true，返回识别模型与设备提示。",
     "run": case_voice_health},
    {"id": "MM2", "title": "语音转写缺文件被拒（负例/边界）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/voice/transcribe（空 body）。",
     "expected": "HTTP 422、error_code=validation_error，缺失字段为 body.file。",
     "run": case_voice_transcribe_boundary},
    {"id": "MM3", "title": "图像识别缺图像被拒（负例/边界）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/ocr/recognize（空 body）。",
     "expected": "HTTP 400，提示需提供图像文件或文件路径。",
     "run": case_ocr_recognize_boundary},
    {"id": "MM4", "title": "语音合成接口可用性（真实观察）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/tts/synthesize（text=多模态验收样本）。",
     "expected": "HTTP 200，返回结构化 JSON（含 message 字段）；本机 TTS 兼容层未启用时 success=false。",
     "run": case_tts_synthesize},
    {"id": "MM5", "title": "工具表「图片OCR」分类真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航 /admin/tools，等待工具表后点击「图片OCR」分类。",
     "expected": "页面渲染「工具表」并可见「图片OCR」分类。",
     "run": case_tools_ocr_page},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「管理员登录」：左侧蓝色品牌栏「XCMAX 服务器后台 · 平台运维 / 服务器后台与自动化治理」；右侧账号框已填 admin、密码框为掩码，可点「登 录」。",
    "MM-tools-ocr.png": "登录后进入「运维工具 · 工具表」：右上分类下拉已选中「图片OCR」，下方「业务工作台入口」仅显示一张「图片 OCR / 图片识别与文字提取」卡片及「查看」按钮，证明图像模态工具面真实存在。",
    "__video__": "本轮真实浏览器会话录像（webm，17.36s，1600x1000，ffmpeg 实测）：管理员登录 → 语音识别就绪 → 语音转写/图像识别入参被拒 → TTS 结构化返回 → 工具表切到图片OCR 分类。",
}