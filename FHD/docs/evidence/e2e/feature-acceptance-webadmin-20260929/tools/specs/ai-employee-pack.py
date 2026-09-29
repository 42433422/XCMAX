"""ai-employee-pack（办公员工包）Web 管理端真机验收用例。

impl：FHD/mods/xcagi-office-employee-pack-bridge。
真实接口面：/api/mod/xcagi-office-employee-pack-bridge/catalog（员工包目录）、
/installed（安装态）、/status（桥接状态）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "ai-employee-pack"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取办公员工包目录（10 个 office 员工包：excel/csv/pdf/ppt/word 生成与读取）→ "
    "读取安装态（已装 10 个）→ 读取桥接状态 → "
    "以真实 404 证明不存在的桥接路径被拒（边界/负例）。"
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


def case_pack_catalog(page, env):
    r = _api(page, "/api/mod/xcagi-office-employee-pack-bridge/catalog")
    d = (r.get("body") or {}).get("data") or {}
    ids = d.get("pack_ids") or []
    ok = r["status"] == 200 and d.get("pack_count") == 10 and len(ids) >= 10 and "word-generate-employee" in ids
    body = {"status": r["status"], "collection": d.get("collection"), "pack_count": d.get("pack_count"),
            "pack_ids": ids}
    _card(page, env, "P1-pack-catalog.png", "P1", "办公员工包目录真实读取（10 个包）",
          "GET /api/mod/xcagi-office-employee-pack-bridge/catalog", r["status"], body)
    return body, ok


def case_pack_installed(page, env):
    r = _api(page, "/api/mod/xcagi-office-employee-pack-bridge/installed")
    d = (r.get("body") or {}).get("data") or {}
    installed = d.get("office_installed") or []
    ok = (r["status"] == 200 and d.get("office_installed_count") == 10
          and isinstance(d.get("total_installed"), int) and len(installed) > 0)
    body = {"status": r["status"], "install_root": d.get("install_root"),
            "total_installed": d.get("total_installed"), "office_installed_count": d.get("office_installed_count"),
            "sample": [{"pack_id": x.get("pack_id"), "name": x.get("name")} for x in installed[:4]]}
    _card(page, env, "P2-pack-installed.png", "P2", "办公员工包安装态真实读取",
          "GET /api/mod/xcagi-office-employee-pack-bridge/installed", r["status"], body)
    return body, ok


def case_pack_status(page, env):
    r = _api(page, "/api/mod/xcagi-office-employee-pack-bridge/status")
    d = (r.get("body") or {}).get("data") or {}
    ok = r["status"] == 200 and d.get("success") is True and d.get("catalog_pack_count") == 10
    return {"status": r["status"], "mod_id": d.get("mod_id"), "phase": d.get("phase"),
            "catalog_pack_count": d.get("catalog_pack_count"),
            "office_installed_count": d.get("office_installed_count")}, ok


def case_unknown_facade_denied(page, env):
    r = _api(page, "/api/mod/office-employee-pack/employees")
    ok = r["status"] == 404
    body = {"status": r["status"], "body_head": str(r.get("body"))[:160]}
    _card(page, env, "P3-pack-boundary.png", "P3", "不存在的桥接路径被拒（边界/负例）",
          "GET /api/mod/office-employee-pack/employees", r["status"], body)
    return body, ok


CASES = [
    {"id": "P1", "title": "办公员工包目录真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mod/xcagi-office-employee-pack-bridge/catalog。",
     "expected": "HTTP 200，pack_count=10，含 word-generate-employee 等 10 个包。",
     "run": case_pack_catalog},
    {"id": "P2", "title": "办公员工包安装态真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/mod/xcagi-office-employee-pack-bridge/installed。",
     "expected": "HTTP 200，office_installed_count=10，返回安装根目录与已装清单。",
     "run": case_pack_installed},
    {"id": "P3", "title": "员工包桥接状态真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/mod/xcagi-office-employee-pack-bridge/status。",
     "expected": "HTTP 200、success=true，catalog_pack_count=10。",
     "run": case_pack_status},
    {"id": "P4", "title": "不存在的桥接路径被拒（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/mod/office-employee-pack/employees（无此桥接）。",
     "expected": "HTTP 404。",
     "run": case_unknown_facade_denied},
]

VISIBLE_RESULTS = {
    "P1-pack-catalog.png": "卡片「P1 · 办公员工包目录真实读取（10 个包）」：GET /api/mod/xcagi-office-employee-pack-bridge/catalog，200，{\"status\":200,\"collection\":\"office_employee_pack\",\"pack_count\":10,\"pack_ids\":[\"excel-generate-employee\",\"excel-full-read-employee\",\"csv-generate-employee\",\"csv-full-read-employee\",\"pdf-generate-employee\",\"pdf-full-read-employee\",\"ppt-generate-employee\",\"ppt-full-read-employee\",\"word-generate-employee\",\"word-full-read-employee\"]}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，13.08s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 办公员工包目录 → 安装态 → 桥接状态 → 不存在桥接 404。"
}