"""ai-run-monitor（运行监测与任务历史）Web 管理端真机验收用例。

impl 参考：FHD/app/services/task_context_service.py（任务上下文/运行态维护）。
真实验证面：任务运行历史（/api/agent/runs）、运行详情回执（/api/agent/runs/{run_id}）、
运行事件流（/api/agent/runs/{run_id}/events，run.created）、任务队列（/api/agent/tasks）。
管理端 UI：/admin/workspaces/{run_id}（独立对话工作区，展示该次运行的执行状态与尝试次数）。
"""

FEATURE = "ai-run-monitor"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，真实鼠标键盘）在自托管 Web 管理端建立管理员会话后："
    "读取任务运行历史 → 真实提交一次运行（202 queued）→ 按 run_id 读取运行回执与事件流"
    "（run.created）→ 读取任务队列 → 无会话访问运行历史被 401 拒绝；"
    "并导航到独立工作区页查看该次运行的状态。"
)

_RUN = {}


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


def case_runs_history(page, env):
    r = _api(page, "/api/agent/runs")
    b = r.get("body") or {}
    data = b.get("data")
    ok = r["status"] == 200 and b.get("success") is True and isinstance(data, list)
    return {"status": r["status"], "success": b.get("success"),
            "count": b.get("count"), "items": len(data or [])}, ok


def case_create_run(page, env):
    r = _api(page, "/api/agent/runs", "POST", {"message": "运行监测验收样本"})
    d = (r.get("body") or {}).get("data") or {}
    ok = (r["status"] == 202 and (r.get("body") or {}).get("success") is True
          and bool(d.get("run_id")) and d.get("status") == "queued")
    _RUN["id"] = d.get("run_id")
    return {"status": r["status"], "run_id": d.get("run_id"), "run_status": d.get("status"),
            "plan_id": d.get("plan_id")}, ok


def case_run_receipt_and_events(page, env):
    rid = _RUN.get("id")
    if not rid:
        return {"error": "no run_id captured"}, False
    detail = _api(page, f"/api/agent/runs/{rid}")
    events = _api(page, f"/api/agent/runs/{rid}/events")
    d = (detail.get("body") or {}).get("data") or {}
    evs = (events.get("body") or {}).get("data") or []
    types = [e.get("event_type") for e in evs if isinstance(e, dict)]
    ok = (detail["status"] == 200 and d.get("run_id") == rid
          and events["status"] == 200 and "run.created" in types)
    # 真实界面：导航到该运行的独立工作区
    page.goto(env["base"] + "/admin/workspaces/" + str(rid), wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(8):
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or ""
        if "工作区" in text:
            break
    page.screenshot(path=str(env["shot"] / "RM-workspace-run.png"))
    return {"run_detail_status": detail["status"], "run_detail_id": d.get("run_id"),
            "run_status": d.get("status"), "events_status": events["status"],
            "event_types": types,
            "workspace_url": page.url, "workspace_text_head": text.replace("\n", " ")[:200]}, ok


def case_tasks_queue(page, env):
    r = _api(page, "/api/agent/tasks")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(b.get("data"), list)
    return {"status": r["status"], "success": b.get("success"), "count": b.get("count"),
            "items": len(b.get("data") or [])}, ok


def case_unauth_runs_denied(page, env):
    ctx2 = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1500)
    r = pg2.evaluate(
        "async () => { try { const r = await fetch('/api/agent/runs', {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){}"
        " return {status: r.status, body: j !== null ? j : t.slice(0,200)}; }"
        " catch(e) { return {status:0, body:String(e)}; } }"
    )
    ctx2.close()
    ok = r["status"] in (401, 403)
    return {"status": r["status"], "body": r.get("body")}, ok


CASES = [
    {"id": "RM1", "title": "任务运行历史列表",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/agent/runs。",
     "expected": "HTTP 200、success=true，data 为运行历史列表。",
     "run": case_runs_history},
    {"id": "RM2", "title": "真实提交一次运行",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/agent/runs（message=运行监测验收样本）。",
     "expected": "HTTP 202、success=true，返回 run_id 且 status=queued。",
     "run": case_create_run},
    {"id": "RM3", "title": "运行回执与事件流 + 独立工作区界面",
     "input": "上一步返回的真实 run_id。",
     "actions": "fetch GET /api/agent/runs/{run_id} 与 /events；再导航到 /admin/workspaces/{run_id}。",
     "expected": "详情 200 且 run_id 一致，事件流含 run.created；工作区页渲染该运行状态。",
     "run": case_run_receipt_and_events},
    {"id": "RM4", "title": "任务队列历史",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/agent/tasks。",
     "expected": "HTTP 200、success=true，data 为任务列表。",
     "run": case_tasks_queue},
    {"id": "RM5", "title": "无会话访问运行历史被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 的上下文中 fetch GET /api/agent/runs。",
     "expected": "被拒绝（401/403），不返回运行历史。",
     "run": case_unauth_runs_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「管理员登录」：左侧蓝色品牌栏「XCMAX 服务器后台 · 平台运维 / 服务器后台与自动化治理」；右侧账号框已填 admin、密码框为掩码，可点「登 录」。",
    "RM-workspace-run.png": "登录后进入该次运行的「独立对话工作区」：标题显示运行消息「运行监测验收样本」与执行状态「等待审批 / 第 1 次尝试 · 1 次运行」及进度百分比，提供运维总览/自动化方针/功能模块/员工图谱快捷入口；底部输入条含新对话/审批/上传附件/解析办公文件、主动意识启用、语音播报与「按住说话」。",
    "__video__": "本轮真实浏览器会话录像（webm，17.40s，1600x1000，ffmpeg 实测）：管理员登录 → 运行历史 → 提交运行 → 运行回执/事件流 → 独立工作区页 → 无会话被拒。",
}