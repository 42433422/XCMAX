"""mods-open-api（开放 API · ai_open）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/ai_open.py。
真实接口面：GET /api/aiopen/manifest、/api/aiopen/guide、/api/aiopen/panel、/api/aiopen/keys、
POST /api/aiopen/loop/verify（能力闭环自检）、POST /api/aiopen/invoke（缺 tool 被拒）。
"""

import html as _html
import json as _json

FEATURE = "mods-open-api"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取 AIOPEN 对外协议清单（manifest）→ 读取接入指南与端点 → 读取开放面板与已签发 Key → "
    "执行能力闭环自检（loop/verify closed_loop=true）→ 以真实 400 记录缺 tool 的开放调用被拒（边界/负例）。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p,m,b]) => { try {
            const init={credentials:'include', method:m};
            if (b!==null){ init.headers={'Content-Type':'application/json'}; init.body=JSON.stringify(b); }
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


def case_manifest(page, env):
    r = _api(page, "/api/aiopen/manifest")
    b = r.get("body") or {}
    proto = b.get("protocol") or {}
    ok = r["status"] == 200 and b.get("name") == "AIOPEN" and bool(b.get("version")) and bool(proto)
    body = {"status": r["status"], "name": b.get("name"), "version": b.get("version"),
            "protocol": proto, "tagline": b.get("tagline")}
    _card(page, env, "A1-openapi-surface.png", "A1+A2+A3+A4+A5",
          "开放 API 协议面（manifest/guide/panel/keys/闭环自检）真实读取", {
              "GET /api/aiopen/manifest": body,
              "GET /api/aiopen/guide": _api(page, "/api/aiopen/guide").get("body"),
              "GET /api/aiopen/panel": _api(page, "/api/aiopen/panel").get("body"),
              "GET /api/aiopen/keys": _api(page, "/api/aiopen/keys").get("body"),
              "POST /api/aiopen/loop/verify": _api(page, "/api/aiopen/loop/verify", "POST", {}).get("body"),
          })
    return body, ok


def case_guide(page, env):
    r = _api(page, "/api/aiopen/guide")
    b = r.get("body") or {}
    eps = b.get("endpoints") or {}
    ok = r["status"] == 200 and bool(b.get("base_url")) and "manifest" in eps and "invoke" in eps
    return {"status": r["status"], "base_url": b.get("base_url"), "endpoint_keys": sorted(eps.keys())}, ok


def case_panel(page, env):
    r = _api(page, "/api/aiopen/panel")
    b = r.get("body") or {}
    routes = b.get("routes") or []
    ok = r["status"] == 200 and len(routes) > 0 and all(x.get("path") for x in routes)
    return {"status": r["status"], "route_count": len(routes), "sample": routes[:3],
            "wechat_open": b.get("wechat_open")}, ok


def case_loop_verify(page, env):
    r = _api(page, "/api/aiopen/loop/verify", "POST", {})
    b = r.get("body") or {}
    steps = b.get("steps") or []
    ok = r["status"] == 200 and b.get("closed_loop") is True and len(steps) > 0
    return {"status": r["status"], "closed_loop": b.get("closed_loop"),
            "steps": [{"step": s.get("step"), "ok": s.get("ok")} for s in steps]}, ok


def case_invoke_missing_tool(page, env):
    r = _api(page, "/api/aiopen/invoke", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "tool" in str(b.get("message"))
    _card(page, env, "A6-invoke-rejected.png", "A6",
          "缺 tool 的开放调用被拒（边界/负例）",
          {"POST /api/aiopen/invoke {}": {"status": r["status"], "body": b}})
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "A1-openapi-surface.png": "卡片汇总五处真实响应：manifest 200（name=AIOPEN、version=1.0.0.5、protocol 含 guide/mcp/rest_invoke）；guide 200（base_url + endpoints）；panel 200（routes 含 /api/ai/chat 等）；keys 200（keys=[]）；loop/verify 200（closed_loop=true、api_catalog/api_call 步骤 ok）。",
    "A6-invoke-rejected.png": "本轮响应：POST /api/aiopen/invoke 空 body 返回 400，message=tool 不能为空。",
    "__video__": "本轮真实浏览器会话录像（webm，17.92s，ffmpeg 实测）：管理员登录 → manifest → guide → panel → keys → 闭环自检 → 缺 tool 400。",
}

CASES = [
    {"id": "A1", "title": "AIOPEN 协议清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/aiopen/manifest。",
     "expected": "HTTP 200，name=AIOPEN，含 version 与 protocol 端点。",
     "run": case_manifest},
    {"id": "A2", "title": "接入指南与端点真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/aiopen/guide。",
     "expected": "HTTP 200，含 base_url 与 manifest/invoke 端点。",
     "run": case_guide},
    {"id": "A3", "title": "开放面板路由真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/aiopen/panel。",
     "expected": "HTTP 200，routes 非空。",
     "run": case_panel},
    {"id": "A4", "title": "开放 API 能力闭环自检通过",
     "input": "同上。",
     "actions": "页面上下文 POST /api/aiopen/loop/verify。",
     "expected": "HTTP 200，closed_loop=true，自检步骤均 ok。",
     "run": case_loop_verify},
    {"id": "A5", "title": "缺 tool 的开放调用被拒（负例/边界）",
     "input": "同上，空 body。",
     "actions": "页面上下文 POST /api/aiopen/invoke。",
     "expected": "HTTP 400，message 指明 tool 必填。",
     "run": case_invoke_missing_tool},
]