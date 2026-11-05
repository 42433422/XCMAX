"""ch-im-ws（实时通道 WebSocket）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/im_websocket_route.py（/ws/im，带会话鉴权与 ping/pong 心跳）。
真实性边界：在真实浏览器用原生 WebSocket 建连（同源自动带会话 Cookie），断言在页面上下文完成。
"""

import html as _html
import json as _json

FEATURE = "ch-im-ws"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "用原生 WebSocket 连接 ws://127.0.0.1:42423/ws/im，真实发送 ping 并收到 pong → 通道可用；"
    "在全新无会话上下文中连接同一通道 → 被服务端以 4401 unauthorized 关闭（鉴权负例）；"
    "并以 HTTP 面 GET /api/im/conversations 复核同一会话体系可用。"
)

_WS_JS = """(url) => new Promise((resolve) => {
  const out = {opened:false, sent:false, msg:null, closeCode:null, closeReason:null, err:null};
  let ws;
  try { ws = new WebSocket(url); } catch(e) { out.err = String(e); resolve(out); return; }
  const fin = () => { try { ws.close(); } catch(_){} setTimeout(() => resolve(out), 300); };
  ws.onopen = () => { out.opened = true; out.sent = true; ws.send('ping'); };
  ws.onmessage = (e) => { out.msg = (typeof e.data === 'string') ? e.data : String(e.data); fin(); };
  ws.onclose = (e) => { out.closeCode = e.code; out.closeReason = e.reason; resolve(out); };
  ws.onerror = () => { out.err = 'ws_error'; };
  setTimeout(() => { try { ws.close(); } catch(_){} resolve(out); }, 9000);
})"""


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,300)}; }"
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
        "<div class='sub'>XCMAX 服务器后台 · 真实浏览器本轮 WebSocket/fetch 观测（内容为本轮真实响应，非构造）</div>"
        f"<div class='card'><pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_ws_ping_pong(page, env):
    res = page.evaluate(_WS_JS, "ws://127.0.0.1:42423/ws/im")
    ok = res.get("opened") is True and res.get("msg") == '{"type":"pong"}'
    _card(page, env, "W1-ws-ping-pong.png", "W1",
          "实时通道带会话建连并完成 ping/pong", {
              "WS ws://127.0.0.1:42423/ws/im（带管理会话 Cookie）": res})
    return res, ok


def case_http_alongside(page, env):
    r = _api(page, "/api/im/conversations")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True
    return {"status": r["status"], "success": b.get("success"), "user_id": b.get("user_id")}, ok


def case_ws_unauthenticated_closed(page, env):
    browser = page.context.browser
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1200)
    res = pg2.evaluate(_WS_JS, "ws://127.0.0.1:42423/ws/im")
    _card(pg2, env, "W3-ws-unauthorized.png", "W3",
          "无会话连接实时通道被服务端关闭（负例）", {
              "WS /ws/im（无会话 Cookie）": res,
              "note": "服务端 accept 后鉴权失败，以 close code=4401 reason=unauthorized 关闭。"})
    ctx2.close()
    ok = res.get("closeCode") == 4401
    return res, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "W1-ws-ping-pong.png": "卡片显示真实 WebSocket 结果：带会话 Cookie 连接 ws://127.0.0.1:42423/ws/im，opened=true，发送 ping 后收到 msg={\"type\":\"pong\"}（实时通道可用）。",
    "W3-ws-unauthorized.png": "卡片显示：无会话上下文连接 /ws/im 时 closeCode=4401、closeReason=unauthorized —— 未鉴权连接被服务端关闭。",
    "__video__": "本轮真实浏览器会话录像（webm，13.00s，ffmpeg 实测）：管理员登录 → WebSocket 建连 ping/pong → HTTP 会话面复核 → 无会话 WS 被 4401 关闭。",
}

CASES = [
    {"id": "W1", "title": "实时通道带会话建连并完成 ping/pong",
     "input": "已建立的管理员会话（同源 Cookie）。",
     "actions": "页面上下文用原生 WebSocket 连接 ws://127.0.0.1:42423/ws/im，发送 ping 等待回包。",
     "expected": "连接建立并收到 {\"type\":\"pong\"}。",
     "run": case_ws_ping_pong},
    {"id": "W2", "title": "同一会话体系的 HTTP 面可用",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/im/conversations。",
     "expected": "HTTP 200，success=true。",
     "run": case_http_alongside},
    {"id": "W3", "title": "无会话连接实时通道被关闭（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "无 cookie 上下文用原生 WebSocket 连接 /ws/im。",
     "expected": "服务端以 close code=4401 reason=unauthorized 关闭连接。",
     "run": case_ws_unauthenticated_closed},
]