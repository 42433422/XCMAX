"""mods-aiopen-support（开放 API 支撑与能力探询）Web 管理端真机验收用例。

被测对象：以 web 模式运行的自托管管理端后端（http://127.0.0.1:42423）。
实现面：FHD/app/fastapi_routes/aiopen_route_support.py —— AIOPEN 开放接口的协议与 tracing
支撑（MCP JSON-RPC 握手、tools/list、tools/call、REST invoke 能力探询与路由支撑）。

真实性边界：所有断言都在真实浏览器里用页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "mods-aiopen-support"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 系统设置页真实渲染 → "
    "AIOPEN MCP 能力清单（manifest）真实读取 → MCP initialize 协议版本协商 → "
    "REST invoke 探询 api_catalog 得到可调用路由清单 → 未知 MCP 方法被 JSON-RPC 真实拒绝（-32601）。"
)


def _api(page, path, method="GET", body=None, headers=None):
    return page.evaluate(
        "async ([p, m, b, h]) => { try {"
        " const init = {credentials:'include', method: m};"
        " if (b !== null) { init.headers = Object.assign({'Content-Type':'application/json'}, h||{}); init.body = JSON.stringify(b); }"
        " else if (h) { init.headers = h; }"
        " const r = await fetch(p, init); const t = await r.text();"
        " let j=null; try { j = JSON.parse(t); } catch(e) {}"
        " return {status: r.status, body: j !== null ? j : t.slice(0,300)};"
        " } catch(e) { return {status:0, body:String(e)}; } }",
        [path, method, body, headers],
    )


def _shot(page, env, url, name, wait=3500):
    page.goto(env["base"] + url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(wait)
    page.screenshot(path=str(env["shot"] / name))
    return (page.inner_text("body") or "")


def case_manifest(page, env):
    text = _shot(page, env, "/admin/settings", "O1-settings.png")
    r = _api(page, "/api/aiopen/manifest")
    b = r.get("body") or {}
    tools = b.get("tools") or []
    ok = (r["status"] == 200 and b.get("success") is True and b.get("name") == "AIOPEN"
          and bool(b.get("version")) and isinstance(tools, list) and len(tools) > 0)
    return {"status": r["status"], "name": b.get("name"), "version": b.get("version"),
            "tool_count": len(tools), "sample": [t.get("name") for t in tools[:5]],
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_mcp_initialize(page, env):
    text = _shot(page, env, "/admin/", "O2-overview.png")
    r = _api(page, "/api/aiopen/mcp", "POST",
             {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    b = r.get("body") or {}
    result = b.get("result") or {}
    si = result.get("serverInfo") or {}
    ok = (r["status"] == 200 and b.get("jsonrpc") == "2.0" and result.get("protocolVersion")
          and si.get("name") == "AIOPEN" and isinstance(result.get("capabilities"), dict))
    return {"status": r["status"], "protocolVersion": result.get("protocolVersion"),
            "server_name": si.get("name"), "server_version": si.get("version"),
            "ui_head": text.replace("\n", " ")[:120]}, ok


def case_rest_invoke_catalog(page, env):
    text = _shot(page, env, "/admin/tools", "O3-tools.png")
    r = _api(page, "/api/aiopen/invoke", "POST", {"tool": "api_catalog", "arguments": {}})
    b = r.get("body") or {}
    routes = b.get("routes") or []
    ok = (r["status"] == 200 and b.get("success") is True
          and isinstance(routes, list) and len(routes) > 0
          and all(x.get("path") for x in routes))
    return {"status": r["status"], "tool": b.get("tool"), "route_count": len(routes),
            "sample": routes[:3], "ui_head": text.replace("\n", " ")[:120]}, ok


def case_unknown_mcp_method(page, env):
    text = _shot(page, env, "/admin/server-functions", "O4-server-functions.png")
    r = _api(page, "/api/aiopen/mcp", "POST",
             {"jsonrpc": "2.0", "id": 9, "method": "no/such/method", "params": {}})
    b = r.get("body") or {}
    err = b.get("error") or {}
    ok = r["status"] == 200 and err.get("code") == -32601
    return {"status": r["status"], "error": err,
            "ui_head": text.replace("\n", " ")[:120]}, ok


CASES = [
    {"id": "O1", "title": "AIOPEN MCP 能力清单（manifest）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/settings，随后 fetch GET /api/aiopen/manifest。",
     "expected": "HTTP 200、success=true，name=AIOPEN、含版本且 tools 非空。",
     "run": case_manifest},
    {"id": "O2", "title": "MCP initialize 协议版本协商",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开管理端总览页，随后 POST /api/aiopen/mcp（initialize）。",
     "expected": "HTTP 200，JSON-RPC result 含 protocolVersion 与 serverInfo.name=AIOPEN。",
     "run": case_mcp_initialize},
    {"id": "O3", "title": "REST invoke 能力探询（api_catalog 路由清单）",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/tools，随后 POST /api/aiopen/invoke（tool=api_catalog）。",
     "expected": "HTTP 200、success=true，routes 非空且每项含 path。",
     "run": case_rest_invoke_catalog},
    {"id": "O4", "title": "未知 MCP 方法被 JSON-RPC 拒绝（负例）",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/server-functions，随后 POST /api/aiopen/mcp（method=no/such/method）。",
     "expected": "HTTP 200，JSON-RPC error.code = -32601（method not found）。",
     "run": case_unknown_mcp_method},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码，可点蓝色「登 录」。",
    "O1-settings.png": "「系统设置」页真实渲染：个人主页 管理员 / admin / admin@local，模型服务卡片显示尚未绑定修茈市场账号。",
    "O2-overview.png": "「服务器后台总览」页真实渲染：本地节点 127.0.0.1:42423、远程服务器「离线」、模块注册表 0 个模块。",
    "O3-tools.png": "「运维工具」页真实渲染：工具表区域显示「加载中…」，本轮尚未刷新出工具列表。",
    "O4-server-functions.png": "管理端整体加载占位页「XCMAX 管理中心 正在加载管理页面，请稍候…」（该步 SPA 尚未完成渲染）。",
    "__video__": "本轮真实浏览器会话录像（webm，37.48s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 系统设置 → 总览 → 运维工具 → 加载中占位，并 fetch 复核 /api/aiopen/manifest、mcp initialize、invoke api_catalog 与未知方法 -32601。",
}