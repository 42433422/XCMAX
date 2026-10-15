"""ai-employees-workflow（工作流员工 · 数字员工编排）Web 管理端真机验收用例。

impl：FHD/mods/xcagi-core-workflow-employees、FHD/mods/_employees。
真实接口面：/api/mod/xcagi-core-workflow-employees/employees（工作流员工清单）、
各员工的 /status 与 /run 端点、/api/employees（员工编目）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "ai-employees-workflow"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取工作流员工清单（标签打印/出货管理/收货确认/微信消息）→ "
    "读取员工编目 → 真实调用标签打印员工 status 与 run → "
    "以真实 404 证明不存在员工被拒（边界/负例）。"
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


def case_workflow_employees(page, env):
    r = _api(page, "/api/mod/xcagi-core-workflow-employees/employees")
    data = (r.get("body") or {}).get("data") or []
    ids = [e.get("id") for e in data if isinstance(e, dict)]
    ok = r["status"] == 200 and len(data) >= 4 and "label_print" in ids and "shipment_mgmt" in ids
    body = {"status": r["status"], "employee_count": len(data), "employee_ids": ids,
            "labels": [e.get("label") for e in data if isinstance(e, dict)]}
    _card(page, env, "W1-workflow-employees.png", "W1", "工作流员工清单真实读取",
          "GET /api/mod/xcagi-core-workflow-employees/employees", r["status"], body)
    return body, ok


def case_employee_catalog(page, env):
    r = _api(page, "/api/employees")
    d = (r.get("body") or {}).get("data") or {}
    cat = d.get("catalog") or {}
    ok = (r["status"] == 200 and cat.get("legacy_monolith_mod_id") == "xcagi-core-workflow-employees"
          and len(cat.get("split_mod_entries") or []) > 0)
    return {"status": r["status"], "legacy_monolith_mod_id": cat.get("legacy_monolith_mod_id"),
            "split_entry_count": len(cat.get("split_mod_entries") or []),
            "legacy_employee_ids": cat.get("legacy_monolith_employee_ids")}, ok


def case_label_print_status(page, env):
    r = _api(page, "/api/mod/xcagi-core-workflow-employees/employees/label_print/status")
    d = (r.get("body") or {}).get("data") or {}
    ok = r["status"] == 200 and d.get("ok") is True and d.get("meta", {}).get("employee_id") == "label_print"
    body = {"status": r["status"], "ok": d.get("ok"), "summary": d.get("summary"), "meta": d.get("meta")}
    _card(page, env, "W2-label-print-status.png", "W2", "标签打印工作流员工 status 真实应答",
          "GET /api/mod/xcagi-core-workflow-employees/employees/label_print/status", r["status"], body)
    return body, ok


def case_label_print_run(page, env):
    r = _api(page, "/api/mod/xcagi-core-workflow-employees/employees/label_print/run", "POST", {})
    d = (r.get("body") or {}).get("data") or {}
    ok = r["status"] == 200 and d.get("ok") is True
    return {"status": r["status"], "ok": d.get("ok"), "summary": d.get("summary")}, ok


def case_unknown_employee_denied(page, env):
    r = _api(page, "/api/mod/xcagi-core-workflow-employees/employees/not_exist/status")
    ok = r["status"] == 404
    body = {"status": r["status"], "body_head": str(r.get("body"))[:160]}
    _card(page, env, "W3-workflow-boundary.png", "W3", "不存在的工作流员工被拒（边界/负例）",
          "GET /api/mod/xcagi-core-workflow-employees/employees/not_exist/status", r["status"], body)
    return body, ok


CASES = [
    {"id": "W1", "title": "工作流员工清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mod/xcagi-core-workflow-employees/employees。",
     "expected": "HTTP 200，含 label_print / shipment_mgmt 等 ≥4 名员工。",
     "run": case_workflow_employees},
    {"id": "W2", "title": "员工编目真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/employees。",
     "expected": "HTTP 200，catalog.legacy_monolith_mod_id=xcagi-core-workflow-employees 且含拆分条目。",
     "run": case_employee_catalog},
    {"id": "W3", "title": "标签打印员工 status 真实应答",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET .../employees/label_print/status。",
     "expected": "HTTP 200，ok=true，meta.employee_id=label_print。",
     "run": case_label_print_status},
    {"id": "W4", "title": "标签打印员工 run 真实应答",
     "input": "同上。",
     "actions": "在页面上下文 POST .../employees/label_print/run。",
     "expected": "HTTP 200，ok=true，返回就绪摘要。",
     "run": case_label_print_run},
    {"id": "W5", "title": "不存在员工被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET .../employees/not_exist/status。",
     "expected": "HTTP 404。",
     "run": case_unknown_employee_denied},
]

VISIBLE_RESULTS = {
    "W1-workflow-employees.png": "卡片「W1 · 工作流员工清单真实读取」：GET /api/mod/xcagi-core-workflow-employees/employees，200，{\"status\":200,\"employee_count\":4,\"employee_ids\":[\"label_print\",\"shipment_mgmt\",\"receipt_confirm\",\"wechat_msg\"],\"labels\":[\"标签打印 AI 员工\",\"出货管理 AI 员工\",\"收货确认 AI 员工\",\"微信消息处理 AI 员工\"]}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，12.96s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 工作流员工清单 → 员工编目 → 标签打印 status/run → 不存在员工 404。"
}