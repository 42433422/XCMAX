"""ind-workflow-viz（工作流可视化桥接 Mod）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端中的工作流可视化面。
impl：FHD/mods/xcagi-workflow-visualization-bridge（/api/mod/xcagi-workflow-visualization-bridge/status）。
真实验证面：桥接状态与平台能力读取（core_workflow_mod_id）→ 工作流员工目录 →
生产时间轴工作流图（time_rail_workflow_graph/v1，真实节点）→ 工作流员工清单；
并含工作流运行缺参被拒（负例）。所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "ind-workflow-viz"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端读取工作流可视化桥接状态与平台能力（core_workflow_mod_id）→ "
    "GET /api/core-workflow/employees 读取工作流员工目录 → GET /api/admin/production-line/time-rail/graph "
    "读取真实工作流图（schema=time_rail_workflow_graph/v1，含真实节点）→ "
    "GET /api/mod/xcagi-core-workflow-employees/employees 读回 4 个员工；并含工作流运行缺参 422（负例）。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        "async ([p,m,b]) => { try { const init={credentials:'include',method:m,headers:{}};"
        " if(b!==null){init.headers['Content-Type']='application/json';init.body=JSON.stringify(b);}"
        " if(m!=='GET'&&m!=='HEAD'){const cm=document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);"
        "   if(cm)init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]);}"
        " const r=await fetch(p,init);const t=await r.text();let j=null;try{j=JSON.parse(t);}catch(e){}"
        " return {status:r.status, body:j!==null?j:t.slice(0,240)};"
        " } catch(e){ return {status:0, body:String(e)}; } }", [path, method, body])


def _panel(page, env, name, title, obj):
    page.evaluate(
        "([t,o]) => { document.documentElement.lang='zh-CN'; document.head.replaceChildren();"
        " document.body.replaceChildren(); document.body.style.cssText='margin:0;padding:22px;background:#0b1b2b;"
        " color:#e8f1fb;font:13px/1.7 -apple-system,sans-serif';"
        " const h=document.createElement('h2'); h.textContent=t; h.style.cssText='font-size:15px;margin:0 0 12px';"
        " const p=document.createElement('pre'); p.style.cssText='background:#08131f;border-radius:8px;padding:14px;"
        " white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font:12px/1.6 monospace';"
        " p.textContent=JSON.stringify(o,null,2); document.body.appendChild(h); document.body.appendChild(p); }",
        [title, obj])
    page.screenshot(path=str(env["shot"] / name))


def case_bridge_and_platform(page, env):
    st = _api(page, "/api/mod/xcagi-workflow-visualization-bridge/status")
    cap = _api(page, "/api/platform-shell/capabilities")
    sd = (st.get("body") or {}).get("data") or {}
    cd = (cap.get("body") or {}).get("data") or {}
    _panel(page, env, "WV1-bridge-status.png",
           "GET /bridge/status · /platform-shell/capabilities",
           {"bridge_http": st["status"], "mod_id": sd.get("mod_id"), "role": sd.get("role"),
            "caps_http": cap["status"], "core_workflow_mod_id": cd.get("core_workflow_mod_id"),
            "edition": cd.get("edition")})
    ok = (st["status"] == 200 and sd.get("mod_id") == "xcagi-workflow-visualization-bridge"
          and cap["status"] == 200
          and cd.get("core_workflow_mod_id") == "xcagi-workflow-visualization-bridge")
    return {"bridge_http": st["status"], "mod_id": sd.get("mod_id"), "role": sd.get("role"),
            "caps_http": cap["status"], "core_workflow_mod_id": cd.get("core_workflow_mod_id"),
            "edition": cd.get("edition")}, ok


def case_workflow_catalog(page, env):
    cw = _api(page, "/api/core-workflow/employees")
    mod = _api(page, "/api/mod/xcagi-core-workflow-employees/employees")
    cd = (cw.get("body") or {}).get("data") or {}
    catalog = cd.get("catalog") or {}
    entries = catalog.get("split_mod_entries") or []
    md = (mod.get("body") or {}).get("data") or []
    _panel(page, env, "WV2-workflow-catalog.png",
           "GET /api/core-workflow/employees · /mod/.../employees",
           {"core_http": cw["status"], "workflow_viz_bridge_mod_id": catalog.get("workflow_viz_bridge_mod_id"),
            "legacy_monolith_mod_id": catalog.get("legacy_monolith_mod_id"),
            "legacy_employee_ids": catalog.get("legacy_monolith_employee_ids"),
            "split_mod_entry_count": len(entries),
            "mod_http": mod["status"], "mod_employee_ids": [e.get("id") for e in md]})
    ok = (cw["status"] == 200
          and catalog.get("workflow_viz_bridge_mod_id") == "xcagi-workflow-visualization-bridge"
          and mod["status"] == 200 and len(md) >= 4)
    return {"core_http": cw["status"], "workflow_viz_bridge_mod_id": catalog.get("workflow_viz_bridge_mod_id"),
            "legacy_employee_ids": catalog.get("legacy_monolith_employee_ids"),
            "split_mod_entry_count": len(entries), "mod_http": mod["status"],
            "mod_employee_ids": [e.get("id") for e in md]}, ok


def case_time_rail_graph(page, env):
    r = _api(page, "/api/admin/production-line/time-rail/graph")
    b = r.get("body") or {}
    d = b.get("data") or {}
    nodes = d.get("nodes") or []
    _panel(page, env, "WV3-time-rail-graph.png",
           "GET /api/admin/production-line/time-rail/graph · 真实工作流图",
           {"status": r["status"], "ok": d.get("ok"), "schema": d.get("schema"),
            "version": d.get("version"), "center_id": d.get("center_id"),
            "node_count": len(nodes), "sample_nodes": [n.get("id") for n in nodes[:6]],
            "phase_colors": d.get("phase_colors")})
    ok = (r["status"] == 200 and d.get("schema") == "time_rail_workflow_graph/v1" and len(nodes) >= 1)
    return {"status": r["status"], "schema": d.get("schema"), "node_count": len(nodes),
            "center_id": d.get("center_id"), "sample_nodes": [n.get("id") for n in nodes[:6]]}, ok


def case_negative(page, env):
    r = _api(page, "/api/desktop/automation/workflow/run", method="POST", body={})
    b = r.get("body") or {}
    _panel(page, env, "WV4-run-negative.png",
           "工作流运行缺参被拒（负例）", r)
    ok = r["status"] == 422 and b.get("error_code") == "validation_error"
    return {"status": r["status"], "error_code": b.get("error_code"),
            "errors": [e.get("field") for e in (b.get("errors") or [])]}, ok


CASES = [
    {"id": "WV1", "title": "工作流可视化桥接与平台能力读取",
     "input": "已建立的管理员会话。",
     "actions": "fetch GET /api/mod/xcagi-workflow-visualization-bridge/status 与 GET /api/platform-shell/capabilities。",
     "expected": "状态 200 且 mod_id 正确；平台能力 core_workflow_mod_id 指向该可视化桥接。",
     "run": case_bridge_and_platform},
    {"id": "WV2", "title": "工作流员工目录真实读取",
     "input": "已建立的管理员会话。",
     "actions": "fetch GET /api/core-workflow/employees 与 GET /api/mod/xcagi-core-workflow-employees/employees。",
     "expected": "目录含 workflow_viz_bridge_mod_id 与拆分条目；员工清单≥4。",
     "run": case_workflow_catalog},
    {"id": "WV3", "title": "真实工作流图读取（time rail graph）",
     "input": "已建立的管理员会话。",
     "actions": "fetch GET /api/admin/production-line/time-rail/graph。",
     "expected": "HTTP 200，schema=time_rail_workflow_graph/v1，含真实节点与阶段配色。",
     "run": case_time_rail_graph},
    {"id": "WV4", "title": "工作流运行缺参被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/desktop/automation/workflow/run（空 body）。",
     "expected": "422 validation_error，缺 app_id / workflow。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "WV1-bridge-status.png": "浏览器渲染可视化桥接状态与平台能力真实 JSON：mod_id=xcagi-workflow-visualization-bridge、role、core_workflow_mod_id 与 edition。",
    "WV2-workflow-catalog.png": "浏览器渲染工作流员工目录：workflow_viz_bridge_mod_id、legacy 员工 ids（label_print 等）与 4 个员工清单。",
    "WV3-time-rail-graph.png": "浏览器渲染 time_rail_workflow_graph/v1 真实图：center_id、节点列表与 phase_colors。",
    "WV4-run-negative.png": "浏览器渲染工作流运行空 body 的 422 validation_error（缺 app_id / workflow）。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 桥接/平台能力 → 工作流员工目录 → 真实工作流图 → 负例。",
}