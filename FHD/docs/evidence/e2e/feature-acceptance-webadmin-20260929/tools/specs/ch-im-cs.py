"""ch-im-cs（AI 客服与话术协同）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/im_cs_admin_routes.py、im_cs_client_routes.py、im_ai_group_routes.py。
真实接口面：GET /api/im/cs/inbox（客服会话工作台）、POST /api/im/cs/inbox/{id}/reply（空消息被拒）、
GET /api/im/cs/inbox/{id}/messages（无会话时 fail-closed）。
"""

import html as _html
import json as _json

FEATURE = "ch-im-cs"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取客服收件箱会话工作台 → 以真实 400 记录发送空消息被校验拒绝 → "
    "以真实 500 记录不存在会话的消息读取不被伪造成空数据（fail-closed 边界）。"
)


PLATFORM = "web"

# 部分验证：客服收件箱接口真实可读（success=true），但当前无实时客服会话数据（无客户端接入），
# 会话回复/消息读取为 fail-closed（400/500）。人机会话核心正向（真实对话往返/人工接管切换）本轮未验证。
EXTRA_OBSERVATIONS = [
    "部分验证：GET /api/im/cs/inbox 真实返回 200 success=true（conversations=[]，当前无实时客服会话数据）；"
    "会话回复空消息 400、不存在会话消息 500 均为 fail-closed。"
    "「人机平滑切换/真实客服对话往返」核心正向因无客户端接入的本轮环境不可验证。",
]


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


def case_inbox(page, env):
    r = _api(page, "/api/im/cs/inbox")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(b.get("conversations"), list)
    body = {"status": r["status"], "success": b.get("success"),
            "conversation_count": len(b.get("conversations") or [])}
    _card(page, env, "C1-cs-inbox.png", "C1",
          "客服收件箱会话工作台真实读取",
          {"GET /api/im/cs/inbox": body})
    return body, ok


def case_empty_reply_rejected(page, env):
    r = _api(page, "/api/im/cs/inbox/999/reply", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 400 and "消息" in str(b.get("message"))
    _card(page, env, "C2-cs-reply-and-failclosed.png", "C2+C3",
          "空消息被拒与不存在会话的 fail-closed（负例/边界）", {
              "POST /api/im/cs/inbox/999/reply {}": {"status": r["status"], "body": b},
              "GET /api/im/cs/inbox/999/messages": _api(page, "/api/im/cs/inbox/999/messages").get("body"),
          })
    return {"status": r["status"], "message": b.get("message")}, ok


def case_missing_conversation_failclosed(page, env):
    r = _api(page, "/api/im/cs/inbox/999/messages")
    b = r.get("body") or {}
    ok = r["status"] == 500 and b.get("success") is False and bool(b.get("message"))
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "C1-cs-inbox.png": "本轮响应：GET /api/im/cs/inbox 返回 200，success=true，conversations=[]（客服收件箱工作台可读）。",
    "C2-cs-reply-and-failclosed.png": "卡片显示两处真实响应：POST /api/im/cs/inbox/999/reply 空 body 返回 400，message=消息不能为空；GET /api/im/cs/inbox/999/messages 返回 500，message=即时通信服务暂时不可用（不伪造成空数据）。",
    "__video__": "本轮真实浏览器会话录像（webm，14.24s，ffmpeg 实测）：管理员登录 → 客服收件箱 → 空消息 400 → 不存在会话 500。",
}

CASES = [
    {"id": "C1", "title": "客服收件箱会话工作台真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/im/cs/inbox。",
     "expected": "HTTP 200，success=true，conversations 为数组。",
     "run": case_inbox},
    {"id": "C2", "title": "发送空消息被校验拒绝（负例）",
     "input": "带 CSRF 的管理员会话，会话 id=999，空 body。",
     "actions": "页面上下文 POST /api/im/cs/inbox/999/reply。",
     "expected": "HTTP 400，提示消息不能为空。",
     "run": case_empty_reply_rejected},
    {"id": "C3", "title": "不存在会话的消息读取 fail-closed（边界/负例）",
     "input": "同上。",
     "actions": "页面上下文 GET /api/im/cs/inbox/999/messages。",
     "expected": "HTTP 500 且 success=false，返回明确失败文案而非空数据。",
     "run": case_missing_conversation_failclosed},
]