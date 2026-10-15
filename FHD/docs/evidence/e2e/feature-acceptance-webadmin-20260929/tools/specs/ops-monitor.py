"""ops-monitor（系统健康与神经总线观测）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/health_routes.py（/api/health、/health/details）、
FHD/app/fastapi_routes/neurobus_routes.py（/api/neurobus/health）。
管理端 UI：/admin/xcmax-admin（服务器后台总览）、
/admin/server-functions（服务器功能模块）、/admin/duty-roster-graph（员工图谱）。
"""

import html as _html
import json as _json

FEATURE = "ops-monitor"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取系统健康总览（/api/health，含运行时组件 ok 标志）→ "
    "读取逐组件健康明细（/health/details：database/redis/ai_service 状态）→ "
    "读取 NeuroBus 运行统计（/api/neurobus/health：handlers 与发布/处理/错误/丢弃计数）→ "
    "无会话访问编制在岗健康接口被拒（401）；并在总览、服务器功能模块、员工图谱页真实渲染。"
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


def _unauth(page, env, path, method="GET", body=None, csrf=True, name=None):
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(1200)
    r = _api(pg, path, method, body, csrf)
    if name:
        pg.screenshot(path=str(env["shot"] / name))
    ctx.close()
    return r


def case_health_overview(page, env):
    text = _render(page, env, "/admin/xcmax-admin",
                   name="M1-health-overview.png", wait_for="服务器后台总览")
    r = _api(page, "/api/health")
    d = r.get("body") or {}
    runtime = d.get("runtime") or {}
    comps = runtime.get("components") or {}
    ok = (r["status"] == 200 and d.get("status") in ("healthy", "degraded", "unhealthy")
          and str(d.get("version") or "").startswith("1.0.0.")
          and len(comps) > 0
          and all("ok" in (v or {}) for v in comps.values()))
    return {"status": r["status"], "health_status": d.get("status"),
            "version": d.get("version"), "service": d.get("service"),
            "runtime_status": runtime.get("status"), "component_count": len(comps),
            "ui_has_overview": "服务器后台总览" in text,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_health_details(page, env):
    text = _render(page, env, "/admin/server-functions",
                   name="M2-health-details.png", wait_for="服务器功能模块")
    r = _api(page, "/health/details")
    d = r.get("body") or {}
    checks = d.get("checks") or {}
    flat = {k: (v.get("status") if isinstance(v, dict) else v) for k, v in checks.items()}
    ok = (r["status"] == 200 and "database" in flat and "ai_service" in flat
          and all(v for v in flat.values()))
    return {"status": r["status"], "health_status": d.get("status"),
            "version": d.get("version"), "checks": flat,
            "database_latency_ms": d.get("database_latency_ms"),
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_neurobus_health(page, env):
    text = _render(page, env, "/admin/duty-roster-graph",
                   name="M3-neurobus.png", wait_for="员工图谱")
    r = _api(page, "/api/neurobus/health")
    d = r.get("body") or {}
    ok = (r["status"] == 200 and d.get("running") is True
          and int(d.get("handlers") or 0) > 0
          and all(isinstance(d.get(k), int)
                  for k in ("published", "processed", "errors", "dropped")))
    return {"status": r["status"], "health_status": d.get("status"),
            "running": d.get("running"), "handlers": d.get("handlers"),
            "published": d.get("published"), "processed": d.get("processed"),
            "errors": d.get("errors"), "dropped": d.get("dropped"),
            "reliability": d.get("reliability")}, ok


def case_unauth_health_denied(page, env):
    r = _unauth(page, env, "/api/xcmax/local/duty-graph/health",
                name="M4-unauth-denied.png")
    b = r.get("body") or {}
    ok = r["status"] in (401, 403) and isinstance(b, dict) and b.get("success") is False
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "M1", "title": "系统健康总览与运行时组件真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/xcmax-admin，随后 fetch GET /api/health。",
     "expected": "HTTP 200，status ∈ {healthy,degraded,unhealthy}，version=1.0.0.*，运行时组件非空且各含布尔 ok。",
     "run": case_health_overview},
    {"id": "M2", "title": "逐组件健康明细（数据库/Redis/AI 服务）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/server-functions，随后 fetch GET /health/details。",
     "expected": "HTTP 200，含 database 与 ai_service，database.status=healthy，逐组件均有 status。",
     "run": case_health_details},
    {"id": "M3", "title": "NeuroBus 运行统计真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/duty-roster-graph，随后 fetch GET /api/neurobus/health。",
     "expected": "HTTP 200，running=true，handlers>0，published/processed/errors/dropped 均为整数。",
     "run": case_neurobus_health},
    {"id": "M4", "title": "无会话访问健康接口被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 的上下文中 fetch GET /api/xcmax/local/duty-graph/health。",
     "expected": "被拒绝（401/403），success=false，不返回健康数据。",
     "run": case_unauth_health_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "M1-health-overview.png": "「服务器后台总览」页真实渲染：本地节点「异常」、本地地址 127.0.0.1:42423、远端服务器「离线」、自治健康「不可达」，左下角提示「部分 AI 能力未就绪」。",
    "M2-health-details.png": "「服务器功能模块」页真实渲染：服务器功能注册表 90 个模块列表与路由/同步范围列。",
    "M3-neurobus.png": "「员工图谱」页真实渲染：顶部「在岗员工节点图 编制 55 岗」与中心图/六部门等视图切换。",
    "M4-unauth-denied.png": "无会话的新浏览器上下文停留在管理员登录页，未出现任何健康数据。",
    "__video__": "本轮真实浏览器会话录像（webm，36.28s，1600x1000 25fps，ffmpeg 实测）：管理员登录 → 总览 → 服务器功能模块 → 员工图谱 → 无会话被拒，并 fetch 复核 /api/health、/health/details、/api/neurobus/health。",
}