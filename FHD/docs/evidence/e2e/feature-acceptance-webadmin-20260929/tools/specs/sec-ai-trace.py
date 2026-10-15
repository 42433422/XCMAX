"""sec-ai-trace（AI 调用追溯）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/admin_genai_routes.py（/api/admin/genai/traces）、
FHD/app/fastapi_routes/agent_routes.py（/api/agent/runs）。
"""

import html as _html
import json as _json

FEATURE = "sec-ai-trace"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文核验 AI 调用追溯："
    "GET /api/admin/genai/traces 返回追溯分页（items/total）→ "
    "GET /api/agent/runs 返回真实 agent 运行记录 → 无会话访问被拒（401）。"
)


def _api(page, path, method="GET", body=None, csrf=True):
    return page.evaluate(
        """async ([p, m, b, useCsrf]) => {
            try {
                const init = {method: m, credentials: 'include', headers: {}};
                if (b !== null && b !== undefined) {
                    init.headers['Content-Type'] = 'application/json';
                    init.body = JSON.stringify(b);
                }
                if (useCsrf && m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);
                    if (cm) init.headers['X-CSRF-Token'] = decodeURIComponent(cm[1]);
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch (e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0, 400)};
            } catch (e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body, csrf],
    )


def _card(page, env, name, cid, title, req, status, body):
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


def _unauth(page, env, path, method="GET", body=None, csrf=True):
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(1200)
    r = _api(pg, path, method, body, csrf)
    ctx.close()
    return r


def case_genai_traces(page, env):
    r = _api(page, "/api/admin/genai/traces")
    d = r.get("body") or {}
    data = d.get("data") or {}
    items = data.get("items")
    ok = (r["status"] == 200 and d.get("success") is True
          and isinstance(items, list) and "total" in data)
    _card(page, env, "AI1-genai-traces.png", "AI1", "GenAI 追溯接口真实应答",
          "GET /api/admin/genai/traces", r["status"],
          {"status": r["status"], "success": d.get("success"),
           "total": data.get("total"), "items": len(items) if isinstance(items, list) else None})
    return {"status": r["status"], "success": d.get("success"),
            "total": data.get("total"),
            "items": len(items) if isinstance(items, list) else None}, ok


def case_agent_runs(page, env):
    r = _api(page, "/api/agent/runs")
    d = r.get("body") or {}
    data = d.get("data") or {}
    runs = data.get("runs") if isinstance(data, dict) else None
    if runs is None and isinstance(data, list):
        runs = data
    ok = r["status"] == 200 and len(runs or []) > 0
    _card(page, env, "AI2-agent-runs.png", "AI2", "真实 agent 运行记录可追溯",
          "GET /api/agent/runs", r["status"],
          {"status": r["status"], "count": len(runs or []), "sample": (runs or [])[:2]})
    return {"status": r["status"], "count": len(runs or []),
            "sample": (runs or [])[:2]}, ok


def case_unauth_traces_denied(page, env):
    r = _unauth(page, env, "/api/admin/genai/traces")
    b = r.get("body") or {}
    ok = r["status"] in (401, 403)
    _card(page, env, "AI3-unauth-traces-denied.png", "AI3", "未登录会话访问追溯接口被拒",
          "GET /api/admin/genai/traces (no session)", r["status"], b)
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "AI1", "title": "GenAI 追溯接口真实应答",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/admin/genai/traces。",
     "expected": "200、success=true、data 含 items/total。",
     "run": case_genai_traces},
    {"id": "AI2", "title": "真实 agent 运行记录可追溯",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/agent/runs。",
     "expected": "200 且返回非空运行列表。",
     "run": case_agent_runs},
    {"id": "AI3", "title": "未登录会话访问追溯接口被拒",
     "input": "全新无会话浏览器上下文。",
     "actions": "无 cookie/token 上下文 GET /api/admin/genai/traces。",
     "expected": "被拒绝（401/403）。",
     "run": case_unauth_traces_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "AI1-genai-traces.png": "GET /api/admin/genai/traces 200 success=true data.items=[]、total=0（当前无真实 LLM 调用记录，LLM_RUNTIME_UNAVAILABLE）。",
    "AI2-agent-runs.png": "GET /api/agent/runs 200 success=true count=4，样本 run_925c… status=waiting_user、message=运行监测验收样本、含 steps/tool_calls/llm_calls/retrieval_calls。",
    "AI3-unauth-traces-denied.png": "无会话 GET genai/traces → 401 UNAUTHORIZED 请先登录。",
    "__video__": "录像（webm，11.44s）：GenAI 追溯 → agent 运行记录 → 无会话拒绝。",
}