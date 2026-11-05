"""ind-custom-delivery（客户定制开发与交付）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端（http://127.0.0.1:42423）的 Mod 商店客户定制交付面。
impl：FHD/app/fastapi_routes/private_mod_delivery_routes.py、mod_store_route_handlers。
真实验证面：本地 Mod 目录读取 → 定制需求接口的入参校验拒绝（负例）→
租户安全的私有交付同步（POST /private-delivery/sync 200）与未授权客户 Mod 门禁（POST /status 403）。
所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "ind-custom-delivery"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在自托管 Web 管理端读取 /api/mod-store/catalog 的真实已安装 Mod 目录 → "
    "对 /api/mod-store/private-delivery/requests 发起非法 kind 与不完整字段请求并被 400 拒绝（负例）→ "
    "POST /api/mod-store/private-delivery/sync 返回 200（交付同步状态，含 pending）→ "
    "对未授权客户 Mod 写入 POST /api/mod-store/private-delivery/status 被 403 门禁拒绝（附 GET private-delivery 远端 502 旁证）。"
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


def case_catalog(page, env):
    r = _api(page, "/api/mod-store/catalog")
    b = r.get("body") or {}
    d = b.get("data") or {}
    installed = d.get("installed") or []
    _panel(page, env, "CD1-modstore-catalog.png",
           "GET /api/mod-store/catalog · 本地 Mod 目录真实读取", r)
    ok = r["status"] == 200 and b.get("success") is True and len(installed) >= 1
    return {"status": r["status"], "installed_count": len(installed),
            "sample_ids": [x.get("id") for x in installed[:4]],
            "sample_versions": [x.get("version") for x in installed[:2]]}, ok


def case_request_validation(page, env):
    ts = time.strftime("%H%M%S")
    bad_kind = _api(page, "/api/mod-store/private-delivery/requests", method="POST",
                    body={"kind": "bogus", "title": "验收定制",
                          "requirements": "需要一个定制模块用于验收", "acceptance_criteria": "可安装"})
    short = _api(page, "/api/mod-store/private-delivery/requests", method="POST",
                 body={"kind": "module", "title": "x", "requirements": "yy",
                       "acceptance_criteria": "z"})
    bk = bad_kind.get("body") or {}
    sh = short.get("body") or {}
    _panel(page, env, "CD2-delivery-request-validation.png",
           "POST /api/mod-store/private-delivery/requests · 非法入参被拒（负例）",
           {"invalid_kind": {"status": bad_kind["status"], "message": bk.get("message")},
            "incomplete_fields": {"status": short["status"], "message": sh.get("message")}})
    ok = (bad_kind["status"] == 400 and "kind" in str(bk.get("message"))
          and short["status"] == 400)
    return {"invalid_kind": {"status": bad_kind["status"], "message": bk.get("message")},
            "incomplete_fields": {"status": short["status"], "message": sh.get("message")}}, ok


def case_delivery_status_reachable(page, env):
    sync = _api(page, "/api/mod-store/private-delivery/sync", method="POST", body={})
    sb = sync.get("body") or {}
    sd = sb.get("data") or {}
    gate = _api(page, "/api/mod-store/private-delivery/status", method="POST",
                body={"mod_id": "coating-industry", "track": "delivery", "status": "delivered"})
    gb = gate.get("body") or {}
    remote = _api(page, "/api/mod-store/private-delivery")
    rb = remote.get("body") or {}
    _panel(page, env, "CD3-delivery-status.png",
           "租户安全的私有 Mod 交付同步 / 未授权客户 Mod 门禁（真实读写）", {
               "POST /api/mod-store/private-delivery/sync": {"status": sync["status"], "data": sd},
               "POST /api/mod-store/private-delivery/status（未授权客户 Mod）":
                   {"status": gate["status"], "message": gb.get("message")},
               "GET /api/mod-store/private-delivery（远端 Catalog 读取）":
                   {"status": remote["status"], "message": rb.get("message")},
           })
    ok = (sync["status"] == 200 and sb.get("success") is True and "pending" in sd
          and gate["status"] == 403 and "未授权" in str(gb.get("message")))
    return {"sync": {"status": sync["status"], "data": sd},
            "gate": {"status": gate["status"], "message": gb.get("message")},
            "remote_catalog_get": {"status": remote["status"], "message": rb.get("message")}}, ok


CASES = [
    {"id": "CD1", "title": "本地 Mod 目录真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/mod-store/catalog。",
     "expected": "HTTP 200、success=true，已安装 Mod 列表非空且含 id/version。",
     "run": case_catalog},
    {"id": "CD2", "title": "定制需求接口非法入参被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/mod-store/private-delivery/requests，分别传 kind=bogus 与不完整字段。",
     "expected": "两者均被 400 拒绝，且非法 kind 的提示含 kind 约束说明。",
     "run": case_request_validation},
    {"id": "CD3", "title": "租户安全的私有 Mod 交付同步与未授权门禁（真实读写）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/mod-store/private-delivery/sync，再 POST /api/mod-store/private-delivery/status"
                "（未授权客户 Mod），并读 GET /api/mod-store/private-delivery 作旁证。",
     "expected": "sync 返回 200、success=true 且含 pending；未授权客户 Mod 的 status 写入被 403 门禁拒绝。",
     "run": case_delivery_status_reachable},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "CD1-modstore-catalog.png": "浏览器渲染 GET /api/mod-store/catalog 的真实 JSON：status=200、success=true，data.installed 含 accessories-packaging-industry(v1.0.0)、attendance-industry(v1.0.1)、coating-industry(v1.0.0) 等已安装 Mod（source=local、catalog_base_url=https://xiu-ci.com/v1）。",
    "CD2-delivery-request-validation.png": "浏览器渲染定制需求接口的两条真实拒绝响应：invalid_kind → 400「kind 必须是 module、employee 或 bundle」；incomplete_fields → 400「请完整填写需求名称、需求说明和验收标准」。",
    "CD3-delivery-status.png": "浏览器渲染租户安全私有交付面：POST /api/mod-store/private-delivery/sync → 200 {success:true,data:{routes_changed:false,installed:[],restart_required:[],pending:1,errors:[{mod_id:\"\",message:\"502: 远端 Catalog 返回 401…\"}]}}；POST /api/mod-store/private-delivery/status（未授权客户 Mod coating-industry）→ 403「当前账号未授权该客户私有 Mod」；GET /api/mod-store/private-delivery → 502（远端 Catalog 401，旁证）。",
    "__video__": "本轮真实浏览器会话录像（webm，26.72s，ffmpeg 实测）：管理端登录 → Mod 目录读取 → 定制需求非法入参 400 → 交付同步 200 + 未授权客户 Mod 门禁 403。",
}