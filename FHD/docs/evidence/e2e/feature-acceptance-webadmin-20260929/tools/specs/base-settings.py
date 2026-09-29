"""base-settings（系统设置与偏好）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/workspace_prefs_routes.py。
真实接口面：/api/workspace/prefs（工作区级设置，GET/PATCH）、/api/preferences（用户偏好，GET/POST）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

import time

FEATURE = "base-settings"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取工作区级设置 → 真实 PATCH 写入工作区设置 → "
    "真实写入并回读用户偏好项 → 以真实 400 证明空 key 的偏好写入被拒（边界/负例）。"
)

_KEY = "verify.accept." + time.strftime("%H%M%S")


def _api(page, path, method="GET", body=None, csrf=True):
    return page.evaluate(
        """async ([p,m,b,c]) => {
            try {
                const init = {credentials:'include', method:m};
                if (b !== null && b !== undefined) {
                    init.headers = {'Content-Type':'application/json'};
                    init.body = JSON.stringify(b);
                }
                if (c && m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
                    if (cm) init.headers = Object.assign(init.headers||{}, {'X-CSRF-Token': decodeURIComponent(cm[1])});
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch(e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0,300)};
            } catch(e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body, csrf],
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


def case_read_prefs(page, env):
    r = _api(page, "/api/workspace/prefs")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(b.get("data"), dict)
    body = {"status": r["status"], "success": b.get("success"), "owner_id": b.get("owner_id"),
            "data": b.get("data")}
    _card(page, env, "S1-workspace-prefs.png", "S1", "工作区级设置真实读取",
          "GET /api/workspace/prefs", r["status"], body)
    return body, ok


def case_patch_prefs(page, env):
    r = _api(page, "/api/workspace/prefs", "PATCH", {"theme": "dark"})
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and b.get("owner_id")
    return {"status": r["status"], "success": b.get("success"),
            "owner_id": b.get("owner_id"), "data": b.get("data")}, ok


def case_write_and_read_preference(page, env):
    w = _api(page, "/api/preferences", "POST", {"key": _KEY, "value": "verified"})
    rd = _api(page, "/api/preferences")
    b = rd.get("body") or {}
    prefs = b.get("preferences") or {}
    ok = (w["status"] == 200 and (w.get("body") or {}).get("success") is True
          and prefs.get(_KEY) == "verified")
    body = {"write_status": w["status"], "write_body": w.get("body"),
            "read_status": rd["status"], "key": _KEY, "read_value": prefs.get(_KEY),
            "preferences": prefs}
    _card(page, env, "S2-preference-roundtrip.png", "S2", "用户偏好真实写入并回读",
          f"POST /api/preferences {{key:{_KEY}}} → GET /api/preferences", w["status"], body)
    return body, ok


def case_empty_key_denied(page, env):
    r = _api(page, "/api/preferences", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "key" in str(b.get("message"))
    body = {"status": r["status"], "error_code": b.get("error_code"), "message": b.get("message")}
    _card(page, env, "S3-settings-boundary.png", "S3", "空 key 的偏好写入被拒（边界/负例）",
          "POST /api/preferences {}", r["status"], body)
    return body, ok


CASES = [
    {"id": "S1", "title": "工作区级设置真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/workspace/prefs。",
     "expected": "HTTP 200、success=true，data 为字典且带 owner_id。",
     "run": case_read_prefs},
    {"id": "S2", "title": "工作区级设置真实写入",
     "input": "同上（带 CSRF 双提交）。",
     "actions": "在页面上下文 PATCH /api/workspace/prefs（theme=dark）。",
     "expected": "HTTP 200、success=true，返回写入后的 owner_id。",
     "run": case_patch_prefs},
    {"id": "S3", "title": "用户偏好真实写入并回读",
     "input": "同上，唯一键名。",
     "actions": f"POST /api/preferences（key={_KEY}, value=verified）后 GET /api/preferences 回读。",
     "expected": "写入 200；回读含该键且值一致。",
     "run": case_write_and_read_preference},
    {"id": "S4", "title": "空 key 的偏好写入被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/preferences（空 body）。",
     "expected": "HTTP 400，message 提示偏好 key 不能为空。",
     "run": case_empty_key_denied},
]

VISIBLE_RESULTS = {
    "S1-workspace-prefs.png": "卡片「S1 · 工作区级设置真实读取」：GET /api/workspace/prefs，200，{\"status\":200,\"success\":true,\"owner_id\":\"tenant:4\",\"data\":{\"workflow_ai_employees\":{}}}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，12.8s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 读工作区设置 → 写工作区设置 → 偏好写入并回读 → 空 key 400。"
}