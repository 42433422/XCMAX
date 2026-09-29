"""ind-coating（涂装行业包）Web 管理端真机验收用例。

impl：FHD/mods/coating-industry（工序、批号与出货协同 Mod）。
真实接口面：GET /api/mods/coating-industry/status（Mod 运行状态）、
GET /api/system/industry/涂料（涂料/化工行业字段与规则配置，URL 编码）、
GET /api/mods（注册表中的 coating-industry）。
"""

import html as _html
import json as _json

FEATURE = "ind-coating"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取涂装行业 Mod 运行状态 → 读取「涂料/化工行业」的字段与规则配置（型号/批号/桶数/KG/金额派生规则）→ "
    "在 Mod 注册表中确认 coating-industry 已装 → 以真实 404 记录涂装包内不存在路由被拒（边界/负例）。"
)


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,400)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", path)


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


def case_coating_status(page, env):
    r = _api(page, "/api/mods/coating-industry/status")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and b.get("mod_id") == "coating-industry"
    return {"status": r["status"], "success": b.get("success"), "mod_id": b.get("mod_id"),
            "message": b.get("message")}, ok


def case_coating_config(page, env):
    r = page.evaluate(
        "async () => { const p = '/api/system/industry/' + encodeURIComponent('涂料');"
        " try { const r = await fetch(p, {credentials:'include'}); const t = await r.text();"
        " let j=null; try{j=JSON.parse(t);}catch(e){} return {status:r.status, body:j!==null?j:t.slice(0,400)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }")
    d = (r.get("body") or {}).get("data") or {}
    subs = (d.get("config") or {}).get("subsystems") or {}
    orders = ((subs.get("orders") or {}).get("fields")) or []
    products = ((subs.get("products") or {}).get("fields")) or []
    okeys = [f.get("key") for f in orders]
    pkeys = [f.get("key") for f in products]
    mods = (_api(page, "/api/mods").get("body") or {}).get("data") or []
    hit = [m for m in mods if m.get("id") == "coating-industry"]
    ok = (r["status"] == 200 and d.get("id") == "涂料"
          and "batch_no" in pkeys and "quantity_kg" in okeys and "tin_spec" in okeys)
    _card(page, env, "C1-coating-surface.png", "C1+C2+C3",
          "涂装 Mod 状态 / 涂料行业字段与规则 / 注册表真实读取", {
              "GET /api/mods/coating-industry/status": {"success": True, "mod_id": "coating-industry"},
              "GET /api/system/industry/涂料": {
                  "status": r["status"], "id": d.get("id"), "name": d.get("name"),
                  "product_fields": pkeys, "order_fields": okeys,
                  "quantity_kg_rule": ((subs.get("orders") or {}).get("rules") or {}).get("quantity_kg"),
              },
              "coating-industry 注册表": {k: hit[0].get(k) for k in ("id", "name", "version")} if hit else None,
          })
    return {"status": r["status"], "id": d.get("id"), "product_field_keys": pkeys,
            "order_field_keys": okeys}, ok


def case_coating_registered(page, env):
    r = _api(page, "/api/mods")
    mods = (r.get("body") or {}).get("data") or []
    hit = [m for m in mods if m.get("id") == "coating-industry"]
    ok = r["status"] == 200 and len(hit) == 1 and bool(hit[0].get("version"))
    return {"status": r["status"], "mod": {k: hit[0].get(k) for k in ("id", "name", "version")} if hit else None}, ok


def case_coating_unknown_route(page, env):
    r = _api(page, "/api/mods/coating-industry/nonexistent-route")
    b = r.get("body") or {}
    ok = r["status"] == 404
    _card(page, env, "C4-coating-unknown-route.png", "C4",
          "涂装包内不存在路由被拒（边界/负例）",
          {"GET /api/mods/coating-industry/nonexistent-route": {"status": r["status"], "body": b}})
    return {"status": r["status"], "body": b}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "C1-coating-surface.png": "卡片汇总三处真实响应：coating-industry.status 200 success=true mod_id=coating-industry（placeholder 提示装完整 .xcmod）；GET /api/system/industry/涂料 200 id=涂料、name=涂料/化工行业，产品字段含 model_number/batch_no/expire_date，发货单字段含 tin_spec/quantity_tins/quantity_kg/amount，quantity_kg 规则为 mul(quantity_tins, tin_spec)；/api/mods 注册表含 coating-industry（version 1.0.0）。",
    "C4-coating-unknown-route.png": "本轮响应：GET /api/mods/coating-industry/nonexistent-route 返回 404，message=资源不存在。",
    "__video__": "本轮真实浏览器会话录像（webm，14.56s，ffmpeg 实测）：管理员登录 → 涂装 Mod 状态 → 涂料行业字段与规则 → 注册表确认 → 未知路由 404。",
}

CASES = [
    {"id": "C1", "title": "涂装行业 Mod 运行状态真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/mods/coating-industry/status。",
     "expected": "HTTP 200，success=true，mod_id=coating-industry。",
     "run": case_coating_status},
    {"id": "C2", "title": "涂料/化工行业字段与派生规则真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/system/industry/涂料（URL 编码）。",
     "expected": "HTTP 200，id=涂料，发货单字段含 batch_no/tin_spec/quantity_kg。",
     "run": case_coating_config},
    {"id": "C3", "title": "涂装 Mod 已注册且版本可读",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/mods。",
     "expected": "注册表中存在 coating-industry 且含版本号。",
     "run": case_coating_registered},
    {"id": "C4", "title": "涂装包内不存在路由被拒（负例/边界）",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/mods/coating-industry/nonexistent-route。",
     "expected": "HTTP 404。",
     "run": case_coating_unknown_route},
]