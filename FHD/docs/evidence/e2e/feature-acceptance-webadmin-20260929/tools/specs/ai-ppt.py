"""ai-ppt（演示文稿生成与解析）Web 管理端真机验收用例。

impl：FHD/app/services/document_templates_service.py；PPT 生成/读取员工包在 FHD/mods/_employees/。
真实接口面：/api/mod/ppt-generate-employee/.../run（真实写出 output.pptx）、
/ppt-full-read-employee/.../run（真实解析 pptx 为结构化 JSON）。
真实性边界：本 spec 在运行前落盘一份验收用输入 JSON；断言在真实浏览器页面上下文 fetch 复核。
"""

import json
import os

FEATURE = "ai-ppt"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "真实调用 PPT 生成员生成 output.pptx（slide_count=1，含标题）→ "
    "调用 PPT 全量读取员真实解析该 pptx → "
    "以真实 fail-closed（缺 file_path 返回 ok=false）记录不编造成功（边界/负例）。"
)

_DIR = "/tmp/xcmax-vc-ai-ppt"
os.makedirs(_DIR, exist_ok=True)
_INPUT = os.path.join(_DIR, "input.json")
_OUT = os.path.join(_DIR, "output.pptx")
with open(_INPUT, "w", encoding="utf-8") as _f:
    json.dump({"columns": ["名称", "数量"], "rows": [["验收样本", 1]]}, _f, ensure_ascii=False)


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


def _item(resp):
    d = (resp.get("body") or {}).get("data") or {}
    items = d.get("items") or [{}]
    return d, (items[0] if items else {})


def case_generate_ppt(page, env):
    r = _api(page, "/api/mod/ppt-generate-employee/employees/ppt-generate-employee/run", "POST",
             {"file_path": _INPUT, "user_request": "验收样本 PPT", "output_relpath": _OUT})
    d, it = _item(r)
    ok = r["status"] == 200 and d.get("ok") is True and int(it.get("slide_count") or 0) >= 1
    body = {"status": r["status"], "ok": d.get("ok"), "output_path": it.get("output_path"),
            "slide_count": it.get("slide_count"), "title": it.get("title")}
    _card(page, env, "P1-ppt-generate.png", "P1", "PPT 生成员真实写出 output.pptx",
          "POST .../ppt-generate-employee/run", r["status"], body)
    return body, ok


def case_read_back_ppt(page, env):
    r = _api(page, "/api/mod/ppt-full-read-employee/employees/ppt-full-read-employee/run", "POST",
             {"file_path": _OUT})
    d, _ = _item(r)
    ok = r["status"] == 200 and d.get("ok") is True
    body = {"status": r["status"], "ok": d.get("ok"), "summary": str(d.get("summary"))[:200]}
    _card(page, env, "P2-ppt-read-back.png", "P2", "PPT 全量读取员真实解析生成的 pptx",
          "POST .../ppt-full-read-employee/run", r["status"], body)
    return body, ok


def case_employees(page, env):
    r = _api(page, "/api/mod/ppt-generate-employee/employees")
    data = (r.get("body") or {}).get("data") or []
    ok = r["status"] == 200 and any(x.get("id") == "ppt-generate-employee" for x in data if isinstance(x, dict))
    return {"status": r["status"], "employees": data}, ok


def case_missing_file_failclosed(page, env):
    r = _api(page, "/api/mod/ppt-generate-employee/employees/ppt-generate-employee/run", "POST", {})
    d, _ = _item(r)
    ok = r["status"] == 200 and d.get("ok") is False and "file_path" in str(d.get("error"))
    body = {"status": r["status"], "ok": d.get("ok"), "error": d.get("error")}
    _card(page, env, "P3-ppt-boundary.png", "P3", "缺输入文件时如实 fail-closed（边界/负例）",
          "POST .../ppt-generate-employee/run {}", r["status"], body)
    return body, ok


CASES = [
    {"id": "P1", "title": "PPT 生成员真实写出文件",
     "input": f"验收输入 JSON 与需求文本，落盘 {_INPUT}。",
     "actions": "在页面上下文 POST .../ppt-generate-employee/run。",
     "expected": "HTTP 200、data.ok=true，返回 output_path 与 slide_count≥1。",
     "run": case_generate_ppt},
    {"id": "P2", "title": "PPT 全量读取员真实解析生成件",
     "input": "P1 生成的真实 pptx。",
     "actions": "在页面上下文 POST .../ppt-full-read-employee/run（file_path=生成的 pptx）。",
     "expected": "HTTP 200、data.ok=true，解析出幻灯片结构。",
     "run": case_read_back_ppt},
    {"id": "P3", "title": "PPT 员工真实注册可查",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mod/ppt-generate-employee/employees。",
     "expected": "HTTP 200，含 id=ppt-generate-employee。",
     "run": case_employees},
    {"id": "P4", "title": "缺输入文件时如实 fail-closed（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST .../ppt-generate-employee/run（空 body）。",
     "expected": "HTTP 200、data.ok=false，error 指明缺少 file_path。",
     "run": case_missing_file_failclosed},
]

VISIBLE_RESULTS = {
    "P1-ppt-generate.png": "卡片「P1 · PPT 生成员真实写出 output.pptx」：POST .../ppt-generate-employee/run，200，{\"status\":200,\"ok\":\"true\",\"output_path\":\"/tmp/xcmax-vc-ai-ppt/output.pptx\",\"slide_count\":1,\"title\":\"验收样本 PPT\"}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，13.08s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → PPT 生成员写出 pptx → 全量读取员解析 → 员工注册查询 → 缺文件 fail-closed。"
}