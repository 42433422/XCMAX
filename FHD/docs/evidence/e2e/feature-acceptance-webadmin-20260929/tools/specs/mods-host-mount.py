"""mods-host-mount（宿主能力接入与路由挂载）Web 管理端真机验收用例。

impl：FHD/app/infrastructure/mods/mod_auth.py（Mod 身份校验、路由与菜单挂载）。
真实接口面：GET /api/mods（已装 Mod 注册表）、GET /api/mods/routes（前端路由挂载清单）、
GET /api/mods/loading-status（加载根与状态）、GET /api/mods/runtime/{mod_id}（运行时挂载，未签名扩展被拒）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

import html as _html
import json as _json

FEATURE = "mods-host-mount"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取宿主已装 Mod 注册表 → 读取后端声明的前端路由挂载清单 → 读取 Mod 加载根与状态 → "
    "以真实 409 记录「扩展包未完成签名与安装验证」时运行时挂载被拒（边界/负例）。"
)


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,300)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", path)


def _card(page, env, name, cid, title, rows):
    payload = _json.dumps(rows, ensure_ascii=False, default=str)
    if len(payload) > 3200:
        payload = payload[:3200] + " …(截断)"
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


def case_mods_registry(page, env):
    r = _api(page, "/api/mods")
    mods = (r.get("body") or {}).get("data") or []
    ids = [m.get("id") for m in mods]
    ok = r["status"] == 200 and len(mods) > 0 and "coating-industry" in ids and "attendance-industry" in ids
    body = {"status": r["status"], "count": len(mods),
            "ids": ids[:8],
            "sample": [{k: m.get(k) for k in ("id", "name", "version", "primary")} for m in mods[:4]]}
    _card(page, env, "H1-mods-registry.png", "H1+H2+H3",
          "宿主 Mod 注册表 / 路由挂载 / 加载状态真实读取", {
              "GET /api/mods": body,
              "GET /api/mods/routes": _api(page, "/api/mods/routes").get("body"),
              "GET /api/mods/loading-status": _api(page, "/api/mods/loading-status").get("body"),
          })
    return body, ok


def case_mods_routes(page, env):
    r = _api(page, "/api/mods/routes")
    routes = (r.get("body") or {}).get("data") or []
    ok = (r["status"] == 200 and len(routes) > 0
          and all(x.get("mod_id") and x.get("routes_path") for x in routes))
    return {"status": r["status"], "route_count": len(routes), "sample": routes[:4]}, ok


def case_loading_status(page, env):
    r = _api(page, "/api/mods/loading-status")
    d = (r.get("body") or {}).get("data") or {}
    roots = d.get("mods_search_roots") or []
    ok = r["status"] == 200 and bool(d.get("mods_root")) and len(roots) > 0
    return {"status": r["status"], "mods_root": d.get("mods_root"),
            "search_root_count": len(roots)}, ok


def case_unsigned_runtime_blocked(page, env):
    r = _api(page, "/api/mods/runtime/coating-industry")
    b = r.get("body") or {}
    ok = r["status"] == 409 and b.get("success") is False and "签名" in str(b.get("message"))
    _card(page, env, "H4-runtime-blocked.png", "H4",
          "未签名扩展包的运行时挂载被拒（边界/负例）",
          {"GET /api/mods/runtime/coating-industry": {"status": r["status"], "body": b,
           "note": "运行时挂载要求扩展包完成签名与安装验证；未签名时 fail-closed 拒绝。"}})
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "H1-mods-registry.png": "卡片汇总三处真实响应：GET /api/mods 200 返回已装 Mod 注册表（含 coating-industry、attendance-industry 等）；GET /api/mods/routes 200 返回前端路由挂载清单；GET /api/mods/loading-status 200 返回 mods_root=/private/tmp/xcmax-verifycenter-main/FHD/mods 与搜索根列表。",
    "H4-runtime-blocked.png": "本轮响应：GET /api/mods/runtime/coating-industry 返回 409，success=false，message=扩展包尚未完成签名与安装验证 —— 未签名扩展不挂载运行时。",
    "__video__": "本轮真实浏览器会话录像（webm，20.16s，ffmpeg 实测）：管理员登录 → Mod 注册表 → 路由挂载 → 加载状态 → 未签名运行时 409。",
}

CASES = [
    {"id": "H1", "title": "宿主已装 Mod 注册表真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/mods。",
     "expected": "HTTP 200，data 非空且含 coating-industry、attendance-industry。",
     "run": case_mods_registry},
    {"id": "H2", "title": "后端声明的路由挂载清单真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/mods/routes。",
     "expected": "HTTP 200，非空且每项含 mod_id 与 routes_path。",
     "run": case_mods_routes},
    {"id": "H3", "title": "Mod 加载根与状态真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/mods/loading-status。",
     "expected": "HTTP 200，含 mods_root 与非空搜索根列表。",
     "run": case_loading_status},
    {"id": "H4", "title": "未签名扩展的运行时挂载被拒（负例/边界）",
     "input": "同上，coating-industry 扩展包未完成签名。",
     "actions": "页面上下文 fetch GET /api/mods/runtime/coating-industry。",
     "expected": "HTTP 409，success=false，提示扩展包尚未完成签名与安装验证。",
     "run": case_unsigned_runtime_blocked},
]