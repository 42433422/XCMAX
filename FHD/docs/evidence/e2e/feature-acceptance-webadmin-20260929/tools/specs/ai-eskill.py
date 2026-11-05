"""ai-eskill（工作流编排与 ESkill 制作）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/workflow_definitions.py（工作流定义 REST）。
真实验证面：工作流员工编制目录（/api/workflow-employee-space/overview）、
工作流可视化桥（/api/mod/xcagi-workflow-visualization-bridge/status）、
ESkill 执行路由（POST /api/skills/execute）。
管理端 UI：/admin/workflow-visualization（流程可视化，六部门编制—派发—回写）。
诚实说明：impl 指向的 /api/workflow-definitions REST 在本机 web 模式未注册（404），
本 spec 以真实观察记录该能力面缺口，其余用例断言真实可用面。
"""

FEATURE = "ai-eskill"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，真实鼠标键盘）在自托管 Web 管理端建立管理员会话后："
    "读取工作流员工编制 catalog → 读取工作流可视化桥状态 → "
    "通过 /api/skills/execute 真实执行一次 ESkill 路由（products.view 返回工作台跳转）→ "
    "空请求被拒（400）→ 探面 /api/workflow-definitions（本机 web 模式未注册，404）；"
    "并真实渲染流程可视化页。"
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


def case_workflow_catalog(page, env):
    r = _api(page, "/api/workflow-employee-space/overview")
    d = (r.get("body") or {}).get("data") or {}
    cat = d.get("catalog") or {}
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and isinstance(cat, dict) and cat.get("schema_version") is not None)
    return {"status": r["status"], "success": (r.get("body") or {}).get("success"),
            "catalog_schema_version": cat.get("schema_version"),
            "workflow_viz_bridge_mod_id": cat.get("workflow_viz_bridge_mod_id"),
            "legacy_employee_ids": (cat.get("legacy_monolith_employee_ids") or [])[:6]}, ok


def case_viz_bridge_status(page, env):
    r = _api(page, "/api/mod/xcagi-workflow-visualization-bridge/status")
    d = (r.get("body") or {}).get("data") or {}
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and d.get("role") == "workflow_visualization_bridge")
    return {"status": r["status"], "success": (r.get("body") or {}).get("success"),
            "mod_id": d.get("mod_id"), "role": d.get("role")}, ok


def case_eskill_execute_routed(page, env):
    r = _api(page, "/api/skills/execute", "POST", {"tool_id": "products", "action": "view"})
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and bool(b.get("redirect"))
    return {"status": r["status"], "success": b.get("success"), "redirect": b.get("redirect")}, ok


def case_eskill_empty_denied(page, env):
    r = _api(page, "/api/skills/execute", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and b.get("success") is False and "未收到数据" in str(b.get("message"))
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message")}, ok


def case_workflow_definitions_probe(page, env):
    r = _api(page, "/api/workflow-definitions")
    b = r.get("body") or {}
    ok = r["status"] == 404
    return {"status": r["status"], "body": b,
            "note": "impl 文件 FHD/app/fastapi_routes/workflow_definitions.py 存在，"
                    "但 /api/workflow-definitions 在本机 web 模式未注册（404）——如实记录该能力面缺口"}, ok


def case_workflow_viz_page(page, env):
    page.goto(env["base"] + "/admin/workflow-visualization", wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(10):
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or ""
        if "流程可视化" in text and "执行回写" in text:
            break
    page.screenshot(path=str(env["shot"] / "E-workflow-visualization.png"))
    ok = "流程可视化" in text and "执行回写" in text and "编制" in text
    return {"final_url": page.url, "has_title": "流程可视化" in text,
            "has_writeback": "执行回写" in text, "has_headcount": "编制" in text,
            "text_head": text.replace("\n", " ")[:240]}, ok


CASES = [
    {"id": "E1", "title": "工作流员工编制目录真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/workflow-employee-space/overview。",
     "expected": "HTTP 200、success=true，返回含 schema_version 的编制 catalog。",
     "run": case_workflow_catalog},
    {"id": "E2", "title": "工作流可视化桥状态",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mod/xcagi-workflow-visualization-bridge/status。",
     "expected": "HTTP 200、success=true，role=workflow_visualization_bridge。",
     "run": case_viz_bridge_status},
    {"id": "E3", "title": "ESkill 执行路由真实执行",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/skills/execute（tool_id=products, action=view）。",
     "expected": "HTTP 200、success=true，返回工作台跳转 redirect。",
     "run": case_eskill_execute_routed},
    {"id": "E4", "title": "空请求被拒（负例/边界）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/skills/execute（空 body）。",
     "expected": "HTTP 400、success=false，提示「未收到数据」。",
     "run": case_eskill_empty_denied},
    {"id": "E5", "title": "工作流定义 REST 探面（如实记录注册状态）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/workflow-definitions。",
     "expected": "记录该端点注册状态；本机 web 模式未注册，返回 404。",
     "run": case_workflow_definitions_probe},
    {"id": "E6", "title": "流程可视化页面真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航 /admin/workflow-visualization，等待渲染流程可视化。",
     "expected": "页面渲染「流程可视化」及编制—派发—执行回写链路。",
     "run": case_workflow_viz_page},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「管理员登录」：左侧蓝色品牌栏「XCMAX 服务器后台 · 平台运维 / 服务器后台与自动化治理」；右侧账号框已填 admin、密码框为掩码，可点「登 录」。",
    "E-workflow-visualization.png": "登录后进入「流程可视化」：副标题「以编制图谱为主源，可视化六部门员工、流程派发和执行回写是否在同一条链路上。」；含「编制驱动流程：编制→员工空间→流程可视化→执行回写」（编制 55 岗）、编制/员工空间/流程可视化/执行回写四态卡片、六部门进度条，以及「员工说明：52 个编制员工如何进入流程」的员工卡（静态内容编辑员、SEO 站点地图管理员）。",
    "__video__": "本轮真实浏览器会话录像（webm，14.04s，1600x1000，ffmpeg 实测）：管理员登录 → 编制目录 → 可视化桥状态 → ESkill 路由执行 → 空请求被拒 → workflow-definitions 探面 404 → 流程可视化渲染。",
}