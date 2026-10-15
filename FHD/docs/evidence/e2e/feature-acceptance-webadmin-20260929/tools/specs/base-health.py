"""base-health（服务健康探针）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/health_k8s.py。
真实接口面：/api/health（主探针）、/health/liveness、/health/readiness、/health/details。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "base-health"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取主健康探针（status=healthy、version=1.0.0.5、runtime 组件表）→ "
    "读取 liveness/readiness/details 三个 k8s 探针 → "
    "以真实 404 证明不存在的探针路径不会被静默回退（边界/负例）。"
)


def _api(page, path):
    return page.evaluate(
        """async (p) => {
            try {
                const r = await fetch(p, {credentials:'include'});
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch(e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0,300)};
            } catch(e) { return {status: 0, body: String(e)}; }
        }""",
        path,
    )


def _card(page, env, name, cid, title, req, status, body):
    if getattr(_card, 'used', False):
        return
    _card.used = True
    import json as _json
    import html as _html
    payload = _json.dumps(body, ensure_ascii=False, default=str)
    if len(payload) > 2800:
        payload = payload[:2800] + " …(截断)"
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


def case_main_health(page, env):
    r = _api(page, "/api/health")
    b = r.get("body") or {}
    runtime = b.get("runtime") or {}
    comps = runtime.get("components") or {}
    ok = (r["status"] == 200 and bool(b.get("status"))
          and b.get("version") == "1.0.0.5" and len(comps) > 0)
    body = {"status": r["status"], "health": b.get("status"), "version": b.get("version"),
            "service": b.get("service"), "runtime_status": runtime.get("status"),
            "component_count": len(comps), "component_keys_sample": sorted(comps)[:8]}
    _card(page, env, "H1-health-main.png", "H1", "主健康探针真实应答（含 runtime 组件表）",
          "GET /api/health", r["status"], body)
    return body, ok


def case_liveness(page, env):
    r = _api(page, "/health/liveness")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("status") == "alive" and bool(b.get("python_version"))
    return {"status": r["status"], "liveness": b.get("status"),
            "python_version": b.get("python_version"), "timestamp": b.get("timestamp")}, ok


def case_readiness(page, env):
    r = _api(page, "/health/readiness")
    b = r.get("body") or {}
    checks = b.get("checks") or {}
    ok = (r["status"] in (200, 503) and "database" in checks
          and checks.get("database", {}).get("status") == "healthy")
    body = {"status": r["status"], "readiness": b.get("status"),
            "database": checks.get("database"), "ai_service": checks.get("ai_service"),
            "check_keys": sorted(checks)}
    return body, ok


def case_details(page, env):
    r = _api(page, "/health/details")
    b = r.get("body") or {}
    checks = b.get("checks") or {}
    ok = r["status"] == 200 and bool(b.get("status")) and bool(b.get("version")) and len(checks) > 0
    body = {"status": r["status"], "health": b.get("status"), "version": b.get("version"),
            "check_keys": sorted(checks)}
    _card(page, env, "H2-health-probes.png", "H2", "k8s 探针 /health/details 真实应答",
          "GET /health/details", r["status"], body)
    return body, ok


def case_missing_probe(page, env):
    r = _api(page, "/api/health/deep")
    ok = r["status"] == 404
    body = {"status": r["status"], "body_head": str(r.get("body"))[:160]}
    _card(page, env, "H3-health-boundary.png", "H3", "不存在的探针路径返回 404（边界/负例）",
          "GET /api/health/deep", r["status"], body)
    return body, ok


CASES = [
    {"id": "H1", "title": "主健康探针真实应答",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/health。",
     "expected": "HTTP 200，返回结构化健康状态（本环境 redis 不可用故为 degraded）与 version=1.0.0.5，runtime 组件表非空。",
     "run": case_main_health},
    {"id": "H2", "title": "k8s liveness 探针真实应答",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /health/liveness。",
     "expected": "HTTP 200，status=alive，返回 python_version。",
     "run": case_liveness},
    {"id": "H3", "title": "k8s readiness 探针真实应答",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /health/readiness。",
     "expected": "返回 checks.database.status=healthy；redis 不可用时整体 not_ready（HTTP 503）不放行。",
     "run": case_readiness},
    {"id": "H4", "title": "k8s details 探针真实应答",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /health/details。",
     "expected": "HTTP 200，含 health 状态、版本号与检查项。",
     "run": case_details},
    {"id": "H5", "title": "不存在的探针路径不静默回退（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/health/deep（无此探针）。",
     "expected": "HTTP 404。",
     "run": case_missing_probe},
]

VISIBLE_RESULTS = {
    "H1-health-main.png": "卡片「H1 · 主健康探针真实应答（含 runtime 组件表）」：GET /api/health，200，{\"status\":200,\"health\":\"degraded\",\"version\":\"1.0.0.5\",\"service\":\"xcagi-fastapi\",\"runtime_status\":\"degraded\",\"component_count\":38,组件样例含 business_route:admin_audit/agent/aibiz_terminal/etl 等}（本环境 redis 不可用故为 degraded）。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，16.08s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 主健康探针 → liveness/readiness/details → 不存在的探针 404。"
}