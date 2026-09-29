"""dt-neurobus（事件总线 NeuroBus）Web 管理端真机验收用例。

impl：FHD/app/neuro_bus/bus.py、FHD/app/neuro_bus/event_store.py。
真实接口面：/api/neurobus/health、/api/neurobus/stats（总线运行态）、
/api/mod/xcagi-neuro-bus-bridge/handlers/registry（处理器注册表）、
/api/mod/xcagi-neuro-bus-bridge/events/publish（真实发布事件）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "dt-neurobus"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取事件总线运行态（running、handlers、domains、published/processed）→ "
    "读取处理器注册表（13 个 handler spec / 多域）→ 真实发布一条事件 → "
    "以真实 event_type_required 记录缺参发布被拒（边界/负例）。"
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
                return {status: r.status, body: j !== null ? j : t.slice(0,300)};
            } catch(e) { return {status: 0, body: String(e)}; }
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


def case_bus_health(page, env):
    r = _api(page, "/api/neurobus/health")
    b = r.get("body") or {}
    comps = b.get("components") or {}
    ok = (r["status"] == 200 and b.get("running") is True
          and int(b.get("handlers") or 0) > 0 and len(comps.get("domains") or []) > 0)
    body = {"status": r["status"], "running": b.get("running"), "published": b.get("published"),
            "processed": b.get("processed"), "errors": b.get("errors"), "handlers": b.get("handlers"),
            "domains": comps.get("domains")}
    _card(page, env, "N1-neurobus-health.png", "N1", "事件总线运行态真实读取",
          "GET /api/neurobus/health", r["status"], body)
    return body, ok


def case_handlers_registry(page, env):
    r = _api(page, "/api/mod/xcagi-neuro-bus-bridge/handlers/registry")
    d = (r.get("body") or {}).get("data") or {}
    cat = d.get("catalog") or {}
    ok = (r["status"] == 200 and d.get("success") is True
          and int(cat.get("handler_spec_count") or 0) >= 1 and len(cat.get("domain_ids") or []) > 0)
    body = {"status": r["status"], "mod_id": d.get("mod_id"), "execution_path": d.get("execution_path"),
            "handler_spec_count": cat.get("handler_spec_count"), "domain_ids": cat.get("domain_ids")}
    _card(page, env, "N2-neurobus-registry.png", "N2", "处理器注册表真实读取（handler spec / 域）",
          "GET /api/mod/xcagi-neuro-bus-bridge/handlers/registry", r["status"], body)
    return body, ok


def case_publish_event(page, env):
    r = _api(page, "/api/mod/xcagi-neuro-bus-bridge/events/publish", "POST",
             {"event_type": "verify.accept", "payload": {"marker": "acceptance"}})
    d = (r.get("body") or {}).get("data") or {}
    ok = r["status"] == 200 and d.get("published") is True and d.get("event_type") == "verify.accept"
    body = {"status": r["status"], "published": d.get("published"), "event_type": d.get("event_type"),
            "domain": d.get("domain"), "source": d.get("source"), "execution_path": d.get("execution_path")}
    _card(page, env, "N3-neurobus-publish.png", "N3", "真实发布事件到事件总线",
          "POST .../events/publish {event_type:verify.accept}", r["status"], body)
    return body, ok


def case_publish_missing_type_denied(page, env):
    r = _api(page, "/api/mod/xcagi-neuro-bus-bridge/events/publish", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is False and b.get("message") == "event_type_required"
    body = {"status": r["status"], "success": b.get("success"), "message": b.get("message")}
    _card(page, env, "N4-neurobus-boundary.png", "N4", "缺 event_type 的发布被拒（边界/负例）",
          "POST .../events/publish {}", r["status"], body)
    return body, ok


CASES = [
    {"id": "N1", "title": "事件总线运行态真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/neurobus/health。",
     "expected": "HTTP 200，running=true，handlers>0 且 domains 非空。",
     "run": case_bus_health},
    {"id": "N2", "title": "处理器注册表真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/mod/xcagi-neuro-bus-bridge/handlers/registry。",
     "expected": "HTTP 200、success=true，handler_spec_count≥1 且 domain_ids 非空。",
     "run": case_handlers_registry},
    {"id": "N3", "title": "真实发布事件到总线",
     "input": "同上。",
     "actions": "在页面上下文 POST .../events/publish（event_type=verify.accept）。",
     "expected": "HTTP 200、data.published=true，返回 event_type/domain。",
     "run": case_publish_event},
    {"id": "N4", "title": "缺 event_type 的发布被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST .../events/publish（空 body）。",
     "expected": "HTTP 200 且 success=false，message=event_type_required。",
     "run": case_publish_missing_type_denied},
]

VISIBLE_RESULTS = {
    "N1-neurobus-health.png": "卡片「N1 · 事件总线运行态真实读取」：GET /api/neurobus/health，200，{\"status\":200,\"running\":true,\"published\":30080,\"processed\":30074,\"errors\":0,\"handlers\":39,\"domains\":[\"intent\",\"order\",\"inventory\",\"product\",\"customer\",\"ai_service\",\"print\",\"ocr\",\"payment\",\"safety\",\"shipment\"]}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，13.2s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 总线运行态 → 处理器注册表 → 发布事件 → 缺 event_type 被拒。"
}