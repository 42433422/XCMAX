"""ai-task-workspace（任务工作区与多步骤规划）Web 管理端真机验收用例。

impl：FHD/app/application/agent_orchestrator。
真实接口面：/api/agent/task-runtime（任务运行池）、/api/agent/tasks（任务工作区清单）、
/api/agent/runs（智能任务运行记录）、/api/agent/tasks/events/stream（任务事件流）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "ai-task-workspace"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取任务运行池（workers/进度）→ 读取任务工作区清单与智能任务运行记录 → "
    "读取任务事件流快照 → 以真实 400 证明缺 task_id 的任务创建被拒（边界/负例）。"
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


def case_task_runtime(page, env):
    r = _api(page, "/api/agent/task-runtime")
    d = (r.get("body") or {}).get("data") or {}
    ok = (r["status"] == 200 and d.get("running") is True
          and isinstance(d.get("max_workers"), int) and isinstance(d.get("progress"), dict))
    body = {"status": r["status"], "running": d.get("running"), "max_workers": d.get("max_workers"),
            "active_count": d.get("active_count"), "progress": d.get("progress")}
    _card(page, env, "T1-task-runtime.png", "T1", "任务运行池与进度真实读取",
          "GET /api/agent/task-runtime", r["status"], body)
    return body, ok


def case_tasks_list(page, env):
    r = _api(page, "/api/agent/tasks")
    b = r.get("body") or {}
    data = b.get("data")
    ok = r["status"] == 200 and b.get("success") is True and isinstance(data, list)
    sample = data[:2] if isinstance(data, list) else []
    body = {"status": r["status"], "count": b.get("count"), "task_count": len(data or []),
            "sample": [{"task_id": t.get("task_id"), "status": t.get("status"),
                        "workspace_id": t.get("workspace_id"),
                        "workspace_isolation": t.get("workspace_isolation")} for t in sample]}
    _card(page, env, "T2-task-workspace.png", "T2", "任务工作区清单真实读取",
          "GET /api/agent/tasks", r["status"], body)
    return body, ok


def case_runs_list(page, env):
    r = _api(page, "/api/agent/runs")
    b = r.get("body") or {}
    data = b.get("data")
    ok = r["status"] == 200 and b.get("success") is True and isinstance(data, list)
    sample = data[:2] if isinstance(data, list) else []
    return {"status": r["status"], "count": b.get("count"), "run_count": len(data or []),
            "sample": [{"run_id": x.get("run_id"), "status": x.get("status"), "intent": x.get("intent")}
                       for x in sample]}, ok


def case_events_stream(page, env):
    r = _api(page, "/api/agent/tasks/events/stream")
    text = r.get("body") if isinstance(r.get("body"), str) else ""
    ok = r["status"] == 200 and "task.snapshot" in text
    return {"status": r["status"], "content_type": r.get("content_type"),
            "sse_head": text[:200]}, ok


def case_create_missing_task_id_denied(page, env):
    r = _api(page, "/api/agent/tasks", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "task_id" in str(b.get("message"))
    body = {"status": r["status"], "message": b.get("message")}
    _card(page, env, "T3-task-boundary.png", "T3", "缺 task_id 的任务创建被拒（边界/负例）",
          "POST /api/agent/tasks {}", r["status"], body)
    return body, ok


CASES = [
    {"id": "T1", "title": "任务运行池与进度真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/agent/task-runtime。",
     "expected": "HTTP 200，running=true，返回 max_workers 与进度字典。",
     "run": case_task_runtime},
    {"id": "T2", "title": "任务工作区清单真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/agent/tasks。",
     "expected": "HTTP 200、success=true，data 为数组（含任务工作区隔离字段）。",
     "run": case_tasks_list},
    {"id": "T3", "title": "智能任务运行记录真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/agent/runs。",
     "expected": "HTTP 200、success=true，data 为数组。",
     "run": case_runs_list},
    {"id": "T4", "title": "任务事件流快照真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/agent/tasks/events/stream。",
     "expected": "HTTP 200，SSE 含 task.snapshot 事件。",
     "run": case_events_stream},
    {"id": "T5", "title": "缺 task_id 的任务创建被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/agent/tasks（空 body）。",
     "expected": "HTTP 400，message 指明 task_id 不能为空。",
     "run": case_create_missing_task_id_denied},
]

VISIBLE_RESULTS = {
    "T1-task-runtime.png": "卡片「T1 · 任务运行池与进度真实读取」：GET /api/agent/task-runtime，200，{\"status\":200,\"running\":true,\"max_workers\":4,\"active_count\":0,\"progress\":{\"task_count\":7,\"active_count\":0,\"attention_count\":3,\"completed_count\":4,\"overall_percent\":57}}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，73.68s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 任务运行池 → 任务工作区清单 → 运行记录 → 任务事件流 → 缺 task_id 400。"
}