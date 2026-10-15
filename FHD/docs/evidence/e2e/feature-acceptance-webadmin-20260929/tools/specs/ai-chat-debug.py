"""ai-chat-debug（对话调试与工具路由）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/tools_execute.py（/api/tools/execute 与 /api/skills/execute 常驻路由）。
真实验证面：对话工具目录（/api/tools）、工具分类（/api/tool-categories）、
AI Planner 函数调用注册表（/api/mod/xcagi-planner-bridge/tools/registry）、
工具调用路由真实执行（POST /api/tools/execute）。
管理端 UI：/admin/chat-debug（对话调试工作台，普通版/专业版意图与流程分支调试）。
"""

FEATURE = "ai-chat-debug"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，真实鼠标键盘）在自托管 Web 管理端建立管理员会话后："
    "读取对话工具目录与分类 → 读取 AI Planner 函数调用注册表（93 个工具）→ "
    "通过 /api/tools/execute 真实路由一次工具调用（products.view 返回工作台跳转）→ "
    "空请求被拒（400 未收到数据）；并真实渲染对话调试工作台。"
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


def case_tool_catalog(page, env):
    t = _api(page, "/api/tools")
    c = _api(page, "/api/tool-categories")
    tools = (t.get("body") or {}).get("tools") or []
    cats = (c.get("body") or {}).get("categories") or []
    ok = (t["status"] == 200 and len(tools) > 0 and c["status"] == 200 and len(cats) > 0)
    return {"tools_status": t["status"], "tool_count": len(tools),
            "tool_sample": [x.get("id") for x in tools[:6]],
            "categories_status": c["status"],
            "category_keys": [x.get("category_key") for x in cats]}, ok


def case_planner_registry(page, env):
    r = _api(page, "/api/mod/xcagi-planner-bridge/tools/registry")
    d = (r.get("body") or {}).get("data") or {}
    names = d.get("tool_names") or []
    ok = r["status"] == 200 and d.get("success") is True and int(d.get("tool_count") or 0) >= 50
    return {"status": r["status"], "tool_count": d.get("tool_count"),
            "tool_name_sample": names[:8],
            "has_excel_analysis": "excel_analysis" in names}, ok


def case_tool_execute_routed(page, env):
    r = _api(page, "/api/tools/execute", "POST", {"tool_id": "products", "action": "view"})
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and bool(b.get("redirect"))
    return {"status": r["status"], "success": b.get("success"), "redirect": b.get("redirect")}, ok


def case_tool_execute_empty_denied(page, env):
    r = _api(page, "/api/tools/execute", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and b.get("success") is False and "未收到数据" in str(b.get("message"))
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message")}, ok


def case_unknown_tool_denied(page, env):
    r = _api(page, "/api/tools/execute", "POST", {"tool_id": "__verify_nope__", "action": "view"})
    b = r.get("body") or {}
    ok = r["status"] == 400 and b.get("success") is False and "未知工具" in str(b.get("message"))
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message")}, ok


def case_chat_debug_page(page, env):
    page.goto(env["base"] + "/admin/chat-debug", wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(10):
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or ""
        if "聊天调试工作台" in text:
            break
    page.screenshot(path=str(env["shot"] / "C-chat-debug-console.png"))
    ok = "聊天调试工作台" in text and ("普通版" in text) and ("测试输入" in text)
    return {"final_url": page.url, "has_title": "聊天调试工作台" in text,
            "has_modes": "普通版" in text and "专业版" in text,
            "text_head": text.replace("\n", " ")[:220]}, ok


CASES = [
    {"id": "C1", "title": "对话工具目录与分类真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/tools 与 GET /api/tool-categories。",
     "expected": "两者均 200 且工具清单、分类清单均非空。",
     "run": case_tool_catalog},
    {"id": "C2", "title": "AI Planner 函数调用注册表",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mod/xcagi-planner-bridge/tools/registry。",
     "expected": "HTTP 200、success=true，注册工具数 >= 50。",
     "run": case_planner_registry},
    {"id": "C3", "title": "工具调用路由真实执行",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/tools/execute（tool_id=products, action=view）。",
     "expected": "HTTP 200、success=true，返回工作台跳转 redirect。",
     "run": case_tool_execute_routed},
    {"id": "C4", "title": "空请求被拒（负例/边界）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/tools/execute（空 body）。",
     "expected": "HTTP 400、success=false，提示「未收到数据」。",
     "run": case_tool_execute_empty_denied},
    {"id": "C5", "title": "未知工具被拒（负例）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/tools/execute（tool_id=__verify_nope__）。",
     "expected": "HTTP 400、success=false，提示未知工具。",
     "run": case_unknown_tool_denied},
    {"id": "C6", "title": "对话调试工作台真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/chat-debug，等待渲染聊天调试工作台。",
     "expected": "页面渲染「聊天调试工作台」，含普通版/专业版模式与测试输入区。",
     "run": case_chat_debug_page},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「管理员登录」：左侧蓝色品牌栏「XCMAX 服务器后台 · 平台运维 / 服务器后台与自动化治理」；右侧账号框已填 admin、密码框为掩码，可点「登 录」。",
    "C-chat-debug-console.png": "登录后进入「对话调试」：「聊天调试工作台」副标题「测试普通版/专业版的意图和流程分支。此页只做本地模拟，不调用真实工具。」；含「输入与模式」（快速测试样例：产品查询/客户查询/开单需求/打印命令/复合任务、普通版/专业版切换、测试输入框）与「单模式模拟/双模式对比/加入测试包/清空」及意图测试包导出（JSON/TXT）。",
    "__video__": "本轮真实浏览器会话录像（webm，14.08s，1600x1000，ffmpeg 实测）：管理员登录 → 工具目录/分类读取 → Planner 注册表读取 → 工具路由执行 → 空请求与未知工具被拒 → 对话调试工作台渲染。",
}