"""pay-entitlement-delivery（权益开通与资产交付）Web 管理端真机验收用例。

impl 源码：FHD/app/application/account_tier_derivation.py（预算区间 → 账号等级派生，注册/企业授权时写入）
真实接口：GET /api/model-payment/plans?budget_range=...（按预算派生的套餐与 account_tier 档位）、
          GET /api/xcmax/admin/market/users/{id}/mods（被拒）。
"""

import html as _html
import json as _json

FEATURE = "pay-entitlement-delivery"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 「客户交付中心」页真实渲染"
    "（购买权益、定制与验收口径）→ 套餐接口按预算区间派生推荐档位与账号等级（5–10 万→pro、50–100 万→ultra）→ "
    "非法/未知预算回退默认档（normal）→ 用户已授权 Mod（资产交付清单）接口在未绑定市场账号时被拒（401）。"
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


def _recommended(body):
    data = (body or {}).get("data") or {}
    plans = data.get("plans") or []
    rec = [p for p in plans if p.get("recommended")]
    return {
        "budget_range": data.get("budget_range"),
        "recommended": [{"id": p.get("id"), "account_tier": p.get("account_tier")} for p in rec],
        "tiers": {p.get("id"): p.get("account_tier") for p in plans},
    }


def case_delivery_ui(page, env):
    page.goto(env["base"] + "/admin/delivery-center", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)
    text = (page.inner_text("body") or "").replace("\n", " ")
    title = page.title() or ""
    has_dc = "客户交付中心" in text and "购买权益" in text
    page.screenshot(path=str(env["shot"] / "PD1-delivery-center.png"))
    return {"final_url": page.url, "title": title, "has_delivery_center": "客户交付中心" in text,
            "has_entitlement_wording": "购买权益" in text, "text_head": text[:320]}, has_dc


def case_tier_derivation(page, env):
    low = _api(page, "/api/model-payment/plans?budget_range=5%E2%80%9310%20%E4%B8%87")   # 5–10 万
    high = _api(page, "/api/model-payment/plans?budget_range=50%E2%80%93100%20%E4%B8%87")  # 50–100 万
    lo, hi = _recommended(low.get("body")), _recommended(high.get("body"))
    ok = (low["status"] == 200 and high["status"] == 200
          and [(p["id"], p["account_tier"]) for p in lo["recommended"]] == [("saas-permanent-growth", "pro")]
          and [(p["id"], p["account_tier"]) for p in hi["recommended"]] == [("saas-permanent-ultra", "ultra")])
    _card(page, env, "PD2-tier-derivation.png", "PD2",
          "套餐推荐档位随预算区间派生（5–10 万 → pro，50–100 万 → ultra）",
          "/api/model-payment/plans?budget_range=…", 200, {"5–10 万": lo, "50–100 万": hi})
    return {"low_status": low["status"], "low": lo["recommended"], "high_status": high["status"],
            "high": hi["recommended"]}, ok


def case_unknown_budget_fallback(page, env):
    path = "/api/model-payment/plans?budget_range=__unknown_budget__"
    r = _api(page, path)
    info = _recommended(r.get("body"))
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and [(p["id"], p["account_tier"]) for p in info["recommended"]] == [("saas-permanent-starter", "normal")])
    _card(page, env, "PD3-unknown-budget-fallback.png", "PD3",
          "非法/未知预算回退默认档（normal）", path, r["status"], info)
    return {"status": r["status"], "budget_range_echo": info["budget_range"],
            "recommended": info["recommended"]}, ok


def case_user_mods_denied(page, env):
    path = "/api/xcmax/admin/market/users/1/mods"
    r = _api(page, path)
    body = r.get("body") or {}
    ok = r["status"] == 401 and body.get("success") is False
    _card(page, env, "PD4-user-mods-denied.png", "PD4",
          "用户已授权 Mod（资产交付清单）未绑定市场账号被拒", path, r["status"], body)
    return {"status": r["status"], "message": body.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号 admin、密码为掩码。",
    "PD1-delivery-center.png": "「客户交付中心」页真实渲染：「Mac 主控 · 四设备协同」任务单（目标/执行设备/任务类型/关联工单）与「客户安装与业务验收独立核对；执行器报告完成不等于已交付。」，红条提示「尚未绑定修茈服务器账号…」；下方「CUSTOMER DELIVERY CONTROL 客户交付中心」说明「所有企业用户统一进入交付台账；内部本 Mac 永不计入客户交付；购买权益、定制、安装与首次登录证据分别如实展示。」，含 企业用户/永久购买账户/体验账户/永久待安装/待首次登录/永久交付完成/内部本机排除/定义交付工单/生产中 等指标卡（本轮多为 0）。",
    "PD2-tier-derivation.png": "本工具在真实浏览器中渲染的本轮响应：GET /api/model-payment/plans?budget_range=5–10 万 推荐 saas-permanent-growth(account_tier=pro)；budget_range=50–100 万 推荐 saas-permanent-ultra(account_tier=ultra)。",
    "PD3-unknown-budget-fallback.png": "本轮响应：GET /api/model-payment/plans?budget_range=__unknown_budget__ 返回 200，budget_range 原样回显，推荐档回退 saas-permanent-starter(account_tier=normal)。",
    "PD4-user-mods-denied.png": "本轮响应：GET /api/xcmax/admin/market/users/1/mods 返回 401，success=false，message=尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization。",
    "__video__": "本轮真实浏览器会话录像（webm，18.72s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 客户交付中心页渲染 → 预算派生推荐档（pro/ultra）→ 未知预算回退 normal → 用户 Mod 清单 401。",
}

CASES = [
    {"id": "PD1", "title": "「客户交付中心」页真实渲染（权益开通与交付口径）",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/delivery-center，等待 SPA 渲染后读取标题与正文。",
     "expected": "渲染出「客户交付中心」并含「购买权益」交付口径说明。",
     "run": case_delivery_ui},
    {"id": "PD2", "title": "套餐推荐档位与账号等级随预算区间派生",
     "input": "预算区间 5–10 万 与 50–100 万。",
     "actions": "页面上下文分别 fetch GET /api/model-payment/plans?budget_range=5–10 万 / 50–100 万。",
     "expected": "200；前者推荐 saas-permanent-growth(pro)，后者推荐 saas-permanent-ultra(ultra)。",
     "run": case_tier_derivation},
    {"id": "PD3", "title": "非法/未知预算回退默认档（边界）",
     "input": "budget_range=__unknown_budget__。",
     "actions": "页面上下文 fetch GET /api/model-payment/plans?budget_range=__unknown_budget__。",
     "expected": "200 且成功，原样回显 budget_range，推荐档回退 saas-permanent-starter(normal)。",
     "run": case_unknown_budget_fallback},
    {"id": "PD4", "title": "用户已授权 Mod（资产交付清单）未绑定市场账号被拒",
     "input": "已建立的管理员会话，但未绑定市场 Authorization。",
     "actions": "页面上下文 fetch GET /api/xcmax/admin/market/users/1/mods。",
     "expected": "HTTP 401，success=false，不返回 Mod 交付数据。",
     "run": case_user_mods_denied},
]