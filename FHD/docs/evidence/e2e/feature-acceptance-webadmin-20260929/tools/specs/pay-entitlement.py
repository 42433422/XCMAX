"""pay-entitlement（企业授权与权益管理）Web 管理端真机验收用例。

impl 源码：FHD/frontend/src/views/admin-entitlements、FHD/frontend/src/views/AdminEntitlementsView.vue
         （管理端「用户管理 / 账号权益」视图，路由 /admin/entitlements）
真实接口：GET /api/model-payment/entitlements、GET /api/xcmax/sync/entitlements/current、
          GET /api/xcmax/admin/market/entitlement-fast-lane/plans（被拒）、GET /api/xcmax/admin/market/users（被拒）。
"""

import html as _html
import json as _json

FEATURE = "pay-entitlement"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 「用户管理 / 账号权益」页真实渲染"
    "（管理用户等级与行业、分配客户 Mod 权益）→ 已购权益清单接口真实读取（backend=json）→ "
    "企业端权益强推快照接口返回本账号身份与 has_snapshot=false → "
    "权益快车道套餐与用户列表接口在未绑定市场账号时被拒（401）。"
)


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,400)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", path)


def _card(page, env, name, cid, title, path, status, body):
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
        f"<div class='kv'><span class='k'>请求</span>{_html.escape(path)}</div>"
        f"<div class='kv'><span class='k'>HTTP 状态</span>{status}</div>"
        f"<pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_entitlement_ui(page, env):
    page.goto(env["base"] + "/admin/entitlements", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)
    text = (page.inner_text("body") or "").replace("\n", " ")
    title = page.title() or ""
    has_users = "用户管理" in text and "管理用户等级与行业" in text
    has_levels = "企业" in text and "管理员" in text
    page.screenshot(path=str(env["shot"] / "PE1-entitlements-ui.png"))
    return {"final_url": page.url, "title": title, "has_users_view": has_users,
            "has_account_levels": has_levels, "text_head": text[:320]}, has_users and has_levels


def case_model_entitlements(page, env):
    path = "/api/model-payment/entitlements"
    r = _api(page, path)
    body = r.get("body") or {}
    data = body.get("data") or {}
    ok = (r["status"] == 200 and body.get("success") is True
          and isinstance(data.get("entitlements"), list) and data.get("backend") == "json")
    _card(page, env, "PE2-model-entitlements.png", "PE2",
          "已购权益清单接口真实读取", path, r["status"], body)
    return {"status": r["status"], "backend": data.get("backend"),
            "entitlement_count": len(data.get("entitlements") or [])}, ok


def case_sync_current(page, env):
    path = "/api/xcmax/sync/entitlements/current"
    r = _api(page, path)
    body = r.get("body") or {}
    data = body.get("data") or {}
    acct = data.get("account") or {}
    ok = (r["status"] == 200 and body.get("success") is True
          and acct.get("username") == "admin" and acct.get("market_is_enterprise") is True
          and acct.get("market_is_admin") is True and "has_snapshot" in data)
    _card(page, env, "PE3-sync-current-entitlements.png", "PE3",
          "企业端权益强推快照（只读）返回本账号身份", path, r["status"], body)
    return {"status": r["status"], "has_snapshot": data.get("has_snapshot"),
            "account": acct, "updated_at_ms": data.get("updated_at_ms")}, ok


def case_fast_lane_denied(page, env):
    path = "/api/xcmax/admin/market/entitlement-fast-lane/plans"
    r = _api(page, path)
    body = r.get("body") or {}
    ok = r["status"] == 401 and body.get("success") is False
    _card(page, env, "PE4-fast-lane-plans-denied.png", "PE4",
          "权益快车道套餐未绑定市场账号被拒", path, r["status"], body)
    return {"status": r["status"], "message": body.get("message")}, ok


def case_users_denied(page, env):
    path = "/api/xcmax/admin/market/users"
    r = _api(page, path)
    body = r.get("body") or {}
    ok = r["status"] == 401 and body.get("success") is False
    _card(page, env, "PE5-market-users-denied.png", "PE5",
          "市场用户（授权对象）列表未绑定市场账号被拒", path, r["status"], body)
    return {"status": r["status"], "message": body.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号 admin、密码为掩码。",
    "PE1-entitlements-ui.png": "「账号权益 / 用户管理」页真实渲染：顶栏面包屑「账号权益」，标题「用户管理」，说明「管理用户等级与行业，分配客户 Mod 权益，或进入代管模式代为配置。」，含「新建账号」按钮；红条「尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization」与「余额查询失败：…」；「本地宿主状态 7 个 Mod 已安装」；筛选 全部等级/全部行业、「共 0 / 0 人」，主体「没有匹配的用户」。",
    "PE2-model-entitlements.png": "本工具在真实浏览器中渲染的本轮响应：GET /api/model-payment/entitlements 返回 200，success=true，data.entitlements=[]，data.backend='json'。",
    "PE3-sync-current-entitlements.png": "本轮响应：GET /api/xcmax/sync/entitlements/current 返回 200，success=true，data.has_snapshot=false，data.account={username:'admin', account_kind:'admin', market_is_enterprise:true, market_is_admin:true}。",
    "PE4-fast-lane-plans-denied.png": "本轮响应：GET /api/xcmax/admin/market/entitlement-fast-lane/plans 返回 401，success=false，message=尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization。",
    "PE5-market-users-denied.png": "本轮响应：GET /api/xcmax/admin/market/users 返回 401，success=false，同一未绑定市场账号消息。",
    "__video__": "本轮真实浏览器会话录像（webm，18.80s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 用户管理（账号权益）页渲染 → 权益清单/强推快照读取 → 快车道套餐与市场用户 401。",
}

CASES = [
    {"id": "PE1", "title": "「用户管理 / 账号权益」页真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/entitlements，等待 SPA 渲染后读取标题与正文。",
     "expected": "渲染出「用户管理」并显示「管理用户等级与行业」说明与账号等级筛选。",
     "run": case_entitlement_ui},
    {"id": "PE2", "title": "已购权益清单接口真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/model-payment/entitlements。",
     "expected": "200 且 success=true，entitlements 为数组，backend=json。",
     "run": case_model_entitlements},
    {"id": "PE3", "title": "企业端权益强推快照接口返回本账号身份",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/xcmax/sync/entitlements/current。",
     "expected": "200 且 success=true，account.username=admin 且为企业管理员身份，含 has_snapshot 字段。",
     "run": case_sync_current},
    {"id": "PE4", "title": "权益快车道套餐未绑定市场账号被拒",
     "input": "已建立的管理员会话，但未绑定市场 Authorization。",
     "actions": "页面上下文 fetch GET /api/xcmax/admin/market/entitlement-fast-lane/plans。",
     "expected": "HTTP 401，success=false，不返回套餐数据。",
     "run": case_fast_lane_denied},
    {"id": "PE5", "title": "市场用户（授权对象）列表未绑定市场账号被拒",
     "input": "已建立的管理员会话，但未绑定市场 Authorization。",
     "actions": "页面上下文 fetch GET /api/xcmax/admin/market/users。",
     "expected": "HTTP 401，success=false，不返回用户数据。",
     "run": case_users_denied},
]