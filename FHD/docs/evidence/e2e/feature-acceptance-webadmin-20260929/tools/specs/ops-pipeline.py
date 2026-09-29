"""ops-pipeline（时间轨 / 事件轨 / 运营线编排）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/production_line_routes.py
（/api/admin/production-line/time-rail/status、/time-rail/graph、/event-rail/status）、
FHD/app/fastapi_routes/operations_line_routes.py（/api/operations-line/health、
/api/operations-line/contracts/scan-expiry）。
管理端 UI：/admin/duty-time-architecture（同时完成时间架构）、
/admin/duty-roster-graph（员工图谱）、/admin/xcmax-admin（服务器后台总览）、
/admin/server-functions（服务器功能模块）。
"""

import html as _html
import json as _json

FEATURE = "ops-pipeline"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取时间轨运行状态（/api/admin/production-line/time-rail/status，节点覆盖）→ "
    "读取时间轨编排图（/api/admin/production-line/time-rail/graph，P 相节点）→ "
    "读取事件轨路由状态与运营线 O1–O10 步骤健康 → "
    "非法查询参数被参数校验拒绝（422）。"
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


def _render(page, env, route, name=None, wait_for=None, tries=10):
    page.goto(env["base"] + route, wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(tries):
        page.wait_for_timeout(2000)
        text = page.inner_text("body") or ""
        if wait_for is None or wait_for in text:
            break
    if name:
        page.screenshot(path=str(env["shot"] / name))
    return text


def case_time_rail_status(page, env):
    text = _render(page, env, "/admin/duty-time-architecture",
                   name="P1-time-rail.png", wait_for="同时完成时间架构")
    r = _api(page, "/api/admin/production-line/time-rail/status")
    d = r.get("body") or {}
    inner = d.get("data") if isinstance(d.get("data"), dict) else d
    cov = inner.get("coverage") or {}
    total = cov.get("total_nodes", inner.get("total_nodes"))
    ok = (r["status"] == 200
          and str(inner.get("contract_version") or "").startswith("time_rail_runtime_status/")
          and int(total or 0) > 0)
    return {"status": r["status"], "contract_version": inner.get("contract_version"),
            "graph_schema": inner.get("graph_schema"), "total_nodes": total,
            "status_nodes": cov.get("status_nodes", inner.get("status_nodes")),
            "status_coverage_pct": cov.get("status_coverage_pct", inner.get("status_coverage_pct")),
            "ui_has_time_arch": "同时完成时间架构" in text,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_time_rail_graph(page, env):
    text = _render(page, env, "/admin/duty-roster-graph",
                   name="P2-time-rail-graph.png", wait_for="员工图谱")
    r = _api(page, "/api/admin/production-line/time-rail/graph")
    d = r.get("body") or {}
    inner = d.get("data") if isinstance(d.get("data"), dict) else d
    nodes = inner.get("nodes") or []
    phase = [n.get("id") for n in nodes if str(n.get("id") or "").startswith("P")]
    ok = (r["status"] == 200 and inner.get("ok") is True and len(phase) >= 3
          and bool(inner.get("phase_colors")))
    return {"status": r["status"], "ok": inner.get("ok"),
            "schema": inner.get("schema"), "center_id": inner.get("center_id"),
            "node_count": inner.get("node_count", len(nodes)),
            "phase_nodes_sample": phase[:8],
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_event_rail_status(page, env):
    text = _render(page, env, "/admin/xcmax-admin",
                   name="P3-event-rail.png", wait_for="服务器后台总览")
    er = _api(page, "/api/admin/production-line/event-rail/status")
    oh = _api(page, "/api/operations-line/health")
    ed = er.get("body") or {}
    od = oh.get("body") or {}
    step_ids = sorted((od.get("steps") or {}).keys()) if isinstance(od.get("steps"), dict) else []
    ok = (er["status"] == 200 and oh["status"] == 200
          and int(ed.get("operations_routes") or 0) > 0
          and {"O1", "O10"} <= set(step_ids))
    return {"event_rail_status": er["status"],
            "operations_routes": ed.get("operations_routes"),
            "cross_line_routes": ed.get("cross_line_routes"),
            "ops_line_status": oh["status"], "pipeline_count": od.get("pipeline_count"),
            "step_ids": step_ids,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_invalid_param_denied(page, env):
    text = _render(page, env, "/admin/server-functions",
                   name="P4-invalid-param.png", wait_for="服务器功能模块")
    r = _api(page, "/api/operations-line/contracts/scan-expiry?days_ahead=abc", "POST", {})
    d = r.get("body") or {}
    errors = d.get("errors") or []
    fields = [e.get("field") for e in errors]
    ok = (r["status"] == 422 and d.get("error_code") == "validation_error"
          and "query.days_ahead" in fields)
    return {"status": r["status"], "error_code": d.get("error_code"),
            "message": d.get("message"), "errors": errors,
            "ui_head": text.replace("\n", " ")[:240]}, ok


CASES = [
    {"id": "P1", "title": "时间轨运行状态与节点覆盖真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/duty-time-architecture，随后 fetch GET /api/admin/production-line/time-rail/status。",
     "expected": "HTTP 200、success=true，contract_version=time_rail_runtime_status/*，coverage.total_nodes>0。",
     "run": case_time_rail_status},
    {"id": "P2", "title": "时间轨编排图（P 相节点）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/duty-roster-graph，随后 fetch GET /api/admin/production-line/time-rail/graph。",
     "expected": "HTTP 200、data.ok=true，含 ≥3 个 P 相节点与 phase_colors。",
     "run": case_time_rail_graph},
    {"id": "P3", "title": "事件轨路由与运营线 O1–O10 步骤健康真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/xcmax-admin，随后 fetch GET /api/admin/production-line/event-rail/status 与 GET /api/operations-line/health。",
     "expected": "均 HTTP 200；event-rail operations_routes>0；运营线 steps 覆盖 O1…O10。",
     "run": case_event_rail_status},
    {"id": "P4", "title": "非法查询参数被参数校验拒绝（负例）",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/server-functions，随后 POST /api/operations-line/contracts/scan-expiry?days_ahead=abc。",
     "expected": "HTTP 422、error_code=validation_error，指明 query.days_ahead 解析失败。",
     "run": case_invalid_param_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "P1-time-rail.png": "「同时完成时间架构」页真实渲染：副标题「日更时间壳 · Mermaid 全景（XCAGI-Full-Pipeline 嵌入）」，首屏显示正在加载。",
    "P2-time-rail-graph.png": "「员工图谱」页真实渲染：顶部「在岗员工节点图 编制 55 岗」，含中心图/六部门/物理分区/客户端车间/自进化 Loop 视图切换。",
    "P3-event-rail.png": "「服务器后台总览」页真实渲染：本地节点「异常」、本地地址 127.0.0.1:42423、远端服务器「离线」、自治健康「不可达」、模块注册表异步显示 0 个模块。",
    "P4-invalid-param.png": "「服务器功能模块」页真实渲染：服务器功能注册表 90 个模块列表。",
    "__video__": "本轮真实浏览器会话录像（webm，36.96s，1600x1000 25fps，ffmpeg 实测）：管理员登录 → 时间架构 → 员工图谱 → 总览 → 服务器功能模块，并 fetch 复核时间轨/事件轨/运营线接口与 422 参数校验。",
}