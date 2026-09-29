"""ai-employee-runtime（员工空间与执行调度）Web 管理端真机验收用例。

impl 参考：FHD/app/application/agent_runtime（Agent 运行管线与调度）。
真实验证面：调度运行态（/api/agent/task-runtime，worker 池与进度）、
员工空间编制与工位目录（/api/workflow-employee-space/overview）、
通过 /api/agent/runs 真实提交一次执行任务进入调度队列。
管理端 UI：/admin/workflow-employee-space（员工空间，编制驱动流程与工位实况）。
"""

FEATURE = "ai-employee-runtime"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，真实鼠标键盘）在自托管 Web 管理端建立管理员会话后："
    "读取 Agent 调度运行态（running、worker 池、进度）→ 读取员工空间编制目录 → "
    "POST /api/agent/runs 真实提交任务并进入 queued 调度队列 → "
    "无会话上下文访问调度被 401 拒绝；并真实渲染员工空间（55 岗编制/工位）。"
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


def case_task_runtime(page, env):
    r = _api(page, "/api/agent/task-runtime")
    d = (r.get("body") or {}).get("data") or {}
    pr = d.get("progress") or {}
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and d.get("running") is True and int(d.get("max_workers") or 0) >= 1)
    return {"status": r["status"], "success": (r.get("body") or {}).get("success"),
            "running": d.get("running"), "max_workers": d.get("max_workers"),
            "active_count": d.get("active_count"), "progress": pr}, ok


def case_employee_space_catalog(page, env):
    r = _api(page, "/api/workflow-employee-space/overview")
    d = (r.get("body") or {}).get("data") or {}
    cat = d.get("catalog") or {}
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and isinstance(cat, dict) and cat.get("schema_version") is not None)
    return {"status": r["status"], "success": (r.get("body") or {}).get("success"),
            "catalog_schema_version": cat.get("schema_version"),
            "workflow_viz_bridge_mod_id": cat.get("workflow_viz_bridge_mod_id"),
            "legacy_employee_ids": (cat.get("legacy_monolith_employee_ids") or [])[:6]}, ok


def case_submit_run(page, env):
    r = _api(page, "/api/agent/runs", "POST", {"message": "员工运行时验收样本"})
    d = (r.get("body") or {}).get("data") or {}
    ok = (r["status"] == 202 and (r.get("body") or {}).get("success") is True
          and bool(d.get("run_id")) and d.get("status") == "queued")
    env["run_id"] = d.get("run_id")
    return {"status": r["status"], "success": (r.get("body") or {}).get("success"),
            "run_id": d.get("run_id"), "run_status": d.get("status"),
            "plan_id": d.get("plan_id"), "intent": d.get("intent")}, ok


def case_unauth_runtime_denied(page, env):
    ctx2 = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1500)
    r = pg2.evaluate(
        "async () => { try { const r = await fetch('/api/agent/task-runtime', {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){}"
        " return {status: r.status, body: j !== null ? j : t.slice(0,200)}; }"
        " catch(e) { return {status:0, body:String(e)}; } }"
    )
    ctx2.close()
    ok = r["status"] in (401, 403)
    return {"status": r["status"], "body": r.get("body")}, ok


def case_employee_space_page(page, env):
    page.goto(env["base"] + "/admin/workflow-employee-space", wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(10):
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or ""
        if "员工空间" in text and "编制" in text:
            break
    page.screenshot(path=str(env["shot"] / "R-employee-space.png"))
    ok = "员工空间" in text and "编制" in text and "员工包" in text
    return {"final_url": page.url, "has_employee_space": "员工空间" in text,
            "has_headcount": "编制" in text, "has_pack": "员工包" in text,
            "text_head": text.replace("\n", " ")[:240]}, ok


CASES = [
    {"id": "R1", "title": "Agent 调度运行态真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/agent/task-runtime。",
     "expected": "HTTP 200、success=true，running=true 且 worker 数 >= 1。",
     "run": case_task_runtime},
    {"id": "R2", "title": "员工空间编制与工位目录",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/workflow-employee-space/overview。",
     "expected": "HTTP 200、success=true，返回含 schema_version 的编制 catalog。",
     "run": case_employee_space_catalog},
    {"id": "R3", "title": "提交执行任务进入调度队列",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/agent/runs（message=员工运行时验收样本）。",
     "expected": "HTTP 202、success=true，返回 run_id 且 status=queued（已进入调度）。",
     "run": case_submit_run},
    {"id": "R4", "title": "无会话访问调度被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 的上下文中 fetch GET /api/agent/task-runtime。",
     "expected": "被拒绝（401/403），不返回调度数据。",
     "run": case_unauth_runtime_denied},
    {"id": "R5", "title": "员工空间页面真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航 /admin/workflow-employee-space，等待渲染员工空间与编制信息。",
     "expected": "页面渲染「员工空间」及编制/员工包信息。",
     "run": case_employee_space_page},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「管理员登录」：左侧蓝色品牌栏「XCMAX 服务器后台 · 平台运维 / 服务器后台与自动化治理」；右侧账号框已填 admin、密码框为掩码，可点「登 录」。",
    "R-employee-space.png": "登录后进入「员工空间」：顶部「管理端可视化 · 六部门」横幅（55 岗 AI 员工在编制图谱、流程派发、执行回写中的状态）与「编制驱动流程：编制→员工空间→流程可视化→执行回写」；含编制员工 55（编制主索引）、本机安装/Catalog 与员工包登记卡片（此帧读取中显示 0/55）、六部门进度条（获客部/伙伴部/网站部/Mod部/软件部/归核部）。",
    "__video__": "本轮真实浏览器会话录像（webm，15.84s，1600x1000，ffmpeg 实测）：管理员登录 → 调度运行态 → 编制目录 → 提交任务进入队列 → 无会话被拒 → 员工空间渲染。",
}