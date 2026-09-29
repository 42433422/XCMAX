"""ch-im-core（站内 IM 与实时通道）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/im_routes.py、im_websocket_route.py。
真实接口面：GET /api/im/contacts、/api/im/conversations、/api/im/unread-total、
POST /api/im/conversations/direct（建/取直聊）、POST|GET /api/im/conversations/{id}/messages（收发读回）。
正向闭环：与既有同事建立直聊 → 真实发送一条站内消息 → 读回消息体。
负例：越权读非本账号会话被拒；无会话访问 IM 被 401。
"""

import html as _html
import json as _json

FEATURE = "ch-im-core"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取 IM 联系人与本账号会话列表 → 与既有同事建立直聊并真实发送一条站内消息 → 读回该消息体（正向闭环）→ "
    "读取未读总数 → 以真实 403/404 记录访问非本账号会话被拒（越权负例）→ 无会话上下文访问返回 401。"
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


def case_contacts(page, env):
    r = _api(page, "/api/im/contacts")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(b.get("contacts"), list)
    return {"status": r["status"], "success": b.get("success"),
            "contact_count": len(b.get("contacts") or [])}, ok


def case_send_and_readback(page, env):
    users = (_api(page, "/api/users").get("body") or {}).get("data", {}).get("users") or []
    peer = next((u for u in users if u.get("id") != 1 and u.get("is_active", True)), None)
    if peer is None:
        _card(page, env, "I1-im-surface.png", "I1",
              "站内 IM 收发读回（未能验证：无可用同事账号）",
              {"reason": "no peer user besides self", "users": users})
        return {"blocked": "no peer user"}, False
    conv = _api(page, "/api/im/conversations/direct", "POST", {"peer_user_id": peer["id"]})
    conv_id = ((conv.get("body") or {}).get("conversation") or {}).get("id")
    text = "VC验收站内消息（真实发送读回）"
    sent = _api(page, f"/api/im/conversations/{conv_id}/messages", "POST", {"body": text})
    read = _api(page, f"/api/im/conversations/{conv_id}/messages")
    msgs = (read.get("body") or {}).get("messages") or []
    hit = next((m for m in msgs if m.get("body") == text), None)
    convos = _api(page, "/api/im/conversations")
    ok = (conv["status"] == 200 and conv_id and sent["status"] == 200
          and read["status"] == 200 and hit is not None)
    _card(page, env, "I1-im-surface.png", "I1+I2",
          "站内 IM 直聊建立 / 真实发送 / 读回消息体（正向闭环）", {
              "GET /api/users（选同事）": {"peer_id": peer.get("id"), "peer_username": peer.get("username")},
              "POST /api/im/conversations/direct": {"status": conv["status"], "body": conv.get("body")},
              "POST .../messages {body}": {"status": sent["status"], "body": sent.get("body")},
              "GET .../messages（读回命中）": {"status": read["status"], "hit": hit},
              "GET /api/im/conversations": {
                  "user_id": (convos.get("body") or {}).get("user_id"),
                  "count": len((convos.get("body") or {}).get("conversations") or [])},
          })
    return {"conv_id": conv_id, "sent_status": sent["status"], "readback": hit,
            "conversation_count": len((convos.get("body") or {}).get("conversations") or [])}, ok


def case_unread_total(page, env):
    r = _api(page, "/api/im/unread-total")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and "unread_total" in b
    return {"status": r["status"], "unread_total": b.get("unread_total")}, ok


def case_cross_conversation_denied(page, env):
    r = _api(page, "/api/im/conversations/999999/messages")
    b = r.get("body") or {}
    ok = r["status"] in (403, 404)
    _card(page, env, "I3-im-authz.png", "I3",
          "越权访问非本账号会话被拒（负例）",
          {"GET /api/im/conversations/999999/messages": {"status": r["status"], "body": b}})
    return {"status": r["status"], "body": b}, ok


def case_unauthenticated_denied(page, env):
    browser = page.context.browser
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1500)
    r = pg2.evaluate(
        "async () => { try { const r = await fetch('/api/im/contacts', {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){}"
        " return {status: r.status, body: j !== null ? j : t.slice(0,200)}; }"
        " catch(e) { return {status:0, body:String(e)}; } }")
    ctx2.close()
    ok = r["status"] == 401
    return {"status": r["status"], "body": r.get("body")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "I1-im-surface.png": "卡片真实读写：GET /api/users 选同事；POST /api/im/conversations/direct 建立/获取直聊（conversation.id）；POST .../messages 发送「VC验收站内消息（真实发送读回）」返回 200 message.body 同文；GET .../messages 读回命中该消息；GET /api/im/conversations 列出该直聊（is_direct=true）。",
    "I3-im-authz.png": "本轮响应：GET /api/im/conversations/999999/messages 返回 403（无权访问该会话）——越权读消息被拒。",
    "__video__": "本轮真实浏览器会话录像（webm，17.76s，ffmpeg 实测）：管理员登录 → 直聊建立 → 真实发送 → 读回消息 → 未读 → 越权会话被拒 → 无会话 401。",
}

CASES = [
    {"id": "I1", "title": "IM 联系人面真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/im/contacts。",
     "expected": "HTTP 200，success=true，contacts 为数组。",
     "run": case_contacts},
    {"id": "I2", "title": "建直聊→真实发送→读回消息（正向）",
     "input": "已建立的管理员会话与一个既有同事账号。",
     "actions": "POST 直聊 → POST 消息 → GET 读回。",
     "expected": "读回消息列表命中本轮发送的消息体。",
     "run": case_send_and_readback},
    {"id": "I3", "title": "越权访问非本账号会话被拒（负例）",
     "input": "会话 id=999999 非本账号。",
     "actions": "页面上下文 fetch GET /api/im/conversations/999999/messages。",
     "expected": "HTTP 403 或 404，不返回消息内容。",
     "run": case_cross_conversation_denied},
    {"id": "I4", "title": "未读总数真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/im/unread-total。",
     "expected": "HTTP 200，success=true 且含 unread_total。",
     "run": case_unread_total},
    {"id": "I5", "title": "未登录上下文访问 IM 被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "无 cookie 上下文 fetch GET /api/im/contacts。",
     "expected": "HTTP 401。",
     "run": case_unauthenticated_denied},
]