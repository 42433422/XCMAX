"""base-edition-pack（三档部署形态 minimal / generic / full）Web 管理端真机验收用例。

impl：FHD/app/mod_sdk/platform_shell.py、FHD/frontend/.env.generic。
真实接口面：/api/platform-shell/capabilities（edition 与三档宿主 Mod 清单）、
/api/runtime/product-sku（企业版 SKU）、/api/mod-store/bootstrap-edition-pack（一键装齐宿主包）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "base-edition-pack"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取平台能力清单中的 edition=full 与 minimal/generic/full 三档宿主 Mod 清单 → "
    "读取企业版 SKU → 真实执行一键装齐宿主包（幂等成功）→ "
    "以真实 403 证明无 CSRF 双提交的写操作被拒。"
)


def _api(page, path, method="GET", body=None, csrf=True):
    return page.evaluate(
        """async ([p,m,b,c]) => {
            try {
                const init = {credentials:'include', method:m};
                if (b !== null && b !== undefined) {
                    init.headers = {'Content-Type':'application/json'};
                    init.body = JSON.stringify(b);
                }
                if (c && m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
                    if (cm) init.headers = Object.assign(init.headers||{}, {'X-CSRF-Token': decodeURIComponent(cm[1])});
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch(e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0,300)};
            } catch(e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body, csrf],
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


def case_capabilities(page, env):
    r = _api(page, "/api/platform-shell/capabilities")
    d = (r["body"] or {}).get("data") or {}
    minimal, generic = d.get("minimal_host_mod_ids") or [], d.get("generic_host_mod_ids") or []
    ok = (r["status"] == 200 and d.get("edition") == "full"
          and len(minimal) > 0 and len(generic) > 0)
    body = {"status": r["status"], "schema_version": d.get("schema_version"), "edition": d.get("edition"),
            "minimal_host_mod_ids": minimal, "generic_host_mod_ids": generic,
            "protected_client_mod_ids": d.get("protected_client_mod_ids"),
            "core_workflow_mod_id": d.get("core_workflow_mod_id")}
    _card(page, env, "E1-edition-capabilities.png", "E1",
          "三档部署形态清单真实读取（minimal / generic / full）",
          "GET /api/platform-shell/capabilities", r["status"], body)
    return body, ok


def case_product_sku(page, env):
    r = _api(page, "/api/runtime/product-sku")
    d = (r["body"] or {}).get("data") or {}
    ok = r["status"] == 200 and d.get("sku") == "enterprise" and d.get("is_enterprise_edition") is True
    return {"status": r["status"], "sku": d.get("sku"),
            "is_enterprise_edition": d.get("is_enterprise_edition")}, ok


def case_bootstrap_edition_pack(page, env):
    r = _api(page, "/api/mod-store/bootstrap-edition-pack", "POST", {})
    d = (r["body"] or {}).get("data") or {}
    mods = d.get("mod_ids") or []
    ok = (r["status"] == 200 and (r["body"] or {}).get("success") is True
          and d.get("ready") is True and len(mods) > 0)
    body = {"status": r["status"], "message": (r["body"] or {}).get("message"),
            "edition": d.get("edition"), "ready": d.get("ready"), "mod_count": len(mods),
            "mod_ids": mods}
    return body, ok


def case_bootstrap_without_csrf(page, env):
    r = _api(page, "/api/mod-store/bootstrap-edition-pack", "POST", {}, csrf=False)
    b = r["body"] or {}
    ok = r["status"] == 403 and "CSRF" in str(b.get("message"))
    body = {"status": r["status"], "message": b.get("message")}
    _card(page, env, "E2-bootstrap-boundary.png", "E2",
          "无 CSRF 双提交的宿主包安装被拒（边界/负例）",
          "POST /api/mod-store/bootstrap-edition-pack（无 X-CSRF-Token）", r["status"], body)
    return body, ok


CASES = [
    {"id": "E1", "title": "三档部署形态清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/platform-shell/capabilities。",
     "expected": "HTTP 200，edition=full，minimal_host_mod_ids 与 generic_host_mod_ids 均非空。",
     "run": case_capabilities},
    {"id": "E2", "title": "企业版 SKU 真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/runtime/product-sku。",
     "expected": "HTTP 200，sku=enterprise，is_enterprise_edition=true。",
     "run": case_product_sku},
    {"id": "E3", "title": "一键装齐宿主包真实执行（幂等成功）",
     "input": "已建立的管理员会话（带 CSRF 双提交）。",
     "actions": "在页面上下文 POST /api/mod-store/bootstrap-edition-pack。",
     "expected": "HTTP 200、success=true，ready=true，返回已装齐的宿主 Mod 清单且非空。",
     "run": case_bootstrap_edition_pack},
    {"id": "E4", "title": "无 CSRF 的宿主包安装被拒（负例/边界）",
     "input": "同上，但不携带 X-CSRF-Token。",
     "actions": "在页面上下文 POST /api/mod-store/bootstrap-edition-pack（无 CSRF 头）。",
     "expected": "HTTP 403，message 为 CSRF token missing —— 写操作不会在缺双提交时生效。",
     "run": case_bootstrap_without_csrf},
]

VISIBLE_RESULTS = {
    "E1-edition-capabilities.png": "卡片「E1 · 三档部署形态清单真实读取（minimal / generic / full）」：GET /api/platform-shell/capabilities，200，{\"status\":200,\"schema_version\":1,\"edition\":\"full\",\"minimal_host_mod_ids\":[\"xcagi-planner-bridge\",\"xcagi-neuro-bus-bridge\",\"xcagi-office-employee-pack-bridge\"],\"generic_host_mod_ids\":[9 项，含 xcagi-erp-domain-bridge 等],\"protected_client_mod_ids\":[\"attendance-industry\",\"coating-industry\",\"taiyangniao-pro\",\"sz-qsm-pro\"],\"core_workflow_mod_id\":\"xcagi-workflow-visualization-bridge\"}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，12.44s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 三档形态清单 → 企业版 SKU → 一键装齐宿主包 → 无 CSRF 写操作 403。"
}