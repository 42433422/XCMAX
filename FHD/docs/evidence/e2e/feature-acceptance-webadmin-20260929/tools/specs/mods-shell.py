"""mods-shell（平台壳与 edition 包）Web 管理端真机验收用例。

impl：FHD/app/mod_sdk/platform_shell.py、FHD/app/fastapi_routes/platform_shell_routes.py。
真实接口面：GET /api/platform-shell/capabilities（edition 裁剪与受保护 Mod）、
/api/platform-shell/decoupling-progress（壳化解耦里程碑）、/api/platform-shell/deliverable-status（交付状态）、
POST /api/platform-shell/office/confirm（缺 intent 被校验拒绝）。
"""

import html as _html
import json as _json

FEATURE = "mods-shell"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取平台能力清单（edition=full、受保护客户端 Mod、核心工作流 Mod）→ 读取壳化解耦里程碑 → "
    "读取交付就绪状态 → 以真实 422 记录缺 intent 的办公确认被校验拒绝（边界/负例）。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p,m,b]) => { try {
            const init={credentials:'include', method:m};
            if (b!==null){ init.headers={'Content-Type':'application/json'}; init.body=JSON.stringify(b);
              const cm=document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
              if (cm) init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]); }
            const r=await fetch(p, init); const t=await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, body:j!==null?j:t.slice(0,300)};
        } catch(e){ return {status:0, body:String(e)}; } }""", [path, method, body])


def _card(page, env, name, cid, title, rows):
    payload = _json.dumps(rows, ensure_ascii=False, default=str)
    if len(payload) > 3400:
        payload = payload[:3400] + " …(截断)"
    page.set_content(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><style>"
        "body{margin:0;padding:22px;background:#0b1b2b;color:#e8f1fb;font:13px/1.7 -apple-system,'Segoe UI',sans-serif}"
        "h1{font-size:15px;margin:0 0 4px}.sub{color:#8fb3d9;font-size:12px;margin-bottom:14px}"
        ".card{background:#122b45;border:1px solid #21405f;border-radius:10px;padding:16px}"
        "pre{background:#08131f;border-radius:8px;padding:12px;white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font-size:12px}"
        "</style></head><body>"
        f"<h1>{cid} · {_html.escape(title)}</h1>"
        "<div class='sub'>XCMAX 服务器后台 · 真实浏览器本轮 fetch 观测（内容为本轮真实响应，非构造）</div>"
        f"<div class='card'><pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_capabilities(page, env):
    r = _api(page, "/api/platform-shell/capabilities")
    d = (r.get("body") or {}).get("data") or {}
    ok = (r["status"] == 200 and d.get("edition") == "full"
          and len(d.get("protected_client_mod_ids") or []) > 0 and bool(d.get("core_workflow_mod_id")))
    body = {"status": r["status"], "edition": d.get("edition"),
            "core_workflow_mod_id": d.get("core_workflow_mod_id"),
            "protected_client_mod_ids": d.get("protected_client_mod_ids"),
            "schema_version": d.get("schema_version")}
    _card(page, env, "S1-shell-capabilities.png", "S1+S2+S3",
          "平台壳能力 / 解耦里程碑 / 交付状态真实读取", {
              "GET /api/platform-shell/capabilities": body,
              "GET /api/platform-shell/decoupling-progress": _api(page, "/api/platform-shell/decoupling-progress").get("body", {}).get("data"),
              "GET /api/platform-shell/deliverable-status": _api(page, "/api/platform-shell/deliverable-status").get("body", {}).get("data"),
          })
    return body, ok


def case_decoupling(page, env):
    r = _api(page, "/api/platform-shell/decoupling-progress")
    d = (r.get("body") or {}).get("data") or {}
    ms = d.get("milestones") or []
    ok = r["status"] == 200 and len(ms) > 0 and all(m.get("id") and m.get("status") for m in ms)
    return {"status": r["status"], "milestone_count": len(ms), "sample": ms[:4]}, ok


def case_deliverable(page, env):
    r = _api(page, "/api/platform-shell/deliverable-status")
    d = (r.get("body") or {}).get("data") or {}
    ok = (r["status"] == 200 and d.get("deliverable") is True
          and d.get("host_foundation_bridges_ready") is True)
    return {"status": r["status"], "deliverable": d.get("deliverable"),
            "bridges_ready": d.get("host_foundation_bridges_ready")}, ok


def case_office_confirm_validation(page, env):
    r = _api(page, "/api/platform-shell/office/confirm", "POST", {})
    b = r.get("body") or {}
    errs = b.get("errors") or []
    ok = r["status"] == 422 and b.get("error_code") == "validation_error" \
        and any(e.get("field") == "body.intent" for e in errs)
    _card(page, env, "S4-office-confirm-rejected.png", "S4",
          "缺 intent 的办公确认被校验拒绝（边界/负例）",
          {"POST /api/platform-shell/office/confirm {}": {"status": r["status"], "body": b}})
    return {"status": r["status"], "error_code": b.get("error_code"), "errors": errs}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "S1-shell-capabilities.png": "卡片汇总三处真实响应：capabilities 200（edition=full、core_workflow_mod_id=xcagi-workflow-visualization-bridge、protected_client_mod_ids 含 attendance-industry/coating-industry 等）；decoupling-progress 200 返回前端壳化/Planner 工具 Mod/ERP 等里程碑；deliverable-status 200 deliverable=true、host_foundation_bridges_ready=true。",
    "S4-office-confirm-rejected.png": "本轮响应：POST /api/platform-shell/office/confirm 空 body 返回 422，error_code=validation_error，errors 指名 body.intent 缺失。",
    "__video__": "本轮真实浏览器会话录像（webm，20.08s，ffmpeg 实测）：管理员登录 → 平台壳能力 → 解耦里程碑 → 交付状态 → 缺 intent 422。",
}

CASES = [
    {"id": "S1", "title": "平台壳能力清单（edition 裁剪）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/platform-shell/capabilities。",
     "expected": "HTTP 200，edition=full，受保护客户端 Mod 非空，含核心工作流 Mod。",
     "run": case_capabilities},
    {"id": "S2", "title": "壳化解耦里程碑真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/platform-shell/decoupling-progress。",
     "expected": "HTTP 200，milestones 非空且每项含 id/status。",
     "run": case_decoupling},
    {"id": "S3", "title": "交付就绪状态真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/platform-shell/deliverable-status。",
     "expected": "HTTP 200，deliverable=true，桥接就绪。",
     "run": case_deliverable},
    {"id": "S4", "title": "缺 intent 的办公确认被校验拒绝（负例/边界）",
     "input": "带 CSRF 的管理员会话，空 body。",
     "actions": "页面上下文 POST /api/platform-shell/office/confirm。",
     "expected": "HTTP 422，error_code=validation_error，errors 指出 body.intent 缺失。",
     "run": case_office_confirm_validation},
]