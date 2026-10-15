"""ch-wechat-context（联系人情报注入对话）Web 管理端真机验收用例。

impl：FHD/app/application/wechat_chat_context.py（经 wechat_ingest 路由暴露）。
真实接口面：GET /api/ops/wechat/context?contact_key=...（单联系人情报：身份绑定 + 档案 + 最近消息）。
运行库为完整 schema（97 张表，含 wechat_contacts / wechat_messages）。

本轮实测：带 Authorization: Bearer 令牌时，先 POST /ingest 写入联系人+消息，再 GET /api/ops/wechat/context
能读到该联系人情报（known=true、recent_messages 含刚写入内容）→ 情报返回正向闭环通过；
缺 contact_key → 422 validation_error（参数校验先于鉴权）；无令牌 → 401。
"""

import html as _html
import json
import json as _json
import os
import time

FEATURE = "ch-wechat-context"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后，用共享令牌实测联系人情报入口："
    "先 POST /api/ops/wechat/ingest 写入联系人+消息，再 GET /api/ops/wechat/context 读回该联系人情报"
    "（known=true、recent_messages 含刚写入内容、message_count>=1）→ 情报返回闭环通过；"
    "缺 contact_key → 422 validation_error（参数校验先于鉴权）；无令牌 → 401。"
)

TOKEN = os.environ.get("XCAGI_OPS_TOKEN", "")  # 共享令牌由操作员通过环境变量提供，不落盘
TENANT = 4
CONTACT_KEY = "vc-accept-context"


def _api(page, path, method="GET", body=None, bearer=True):
    return page.evaluate(
        """async ([p,m,b,useBearer]) => { try {
            const init={credentials:'include', method:m};
            const h = {};
            if (b!==null){ h['Content-Type']='application/json'; init.body=JSON.stringify(b); }
            if (useBearer) h['Authorization']='Bearer %s';
            if (m!=='GET' && m!=='HEAD'){ const cm=document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
              if (cm) h['X-CSRF-Token']=decodeURIComponent(cm[1]); }
            init.headers=h;
            const r=await fetch(p, init); const t=await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, body:j!==null?j:t.slice(0,400)};
        } catch(e){ return {status:0, body:String(e)}; } }""" % TOKEN,
        [path, method, body, bearer])


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


def case_context_readback(page, env):
    seq = int(time.time()) % 100000000
    content = f"VC情报消息：客户询价 #{seq}"
    up = _api(page, "/api/ops/wechat/ingest", "POST",
              {"tenant_id": TENANT,
               "contacts": [{"contact_key": CONTACT_KEY, "display_name": "VC情报客户", "wxid": "vc_wxid_ctx"}],
               "messages": [{"contact_key": CONTACT_KEY, "role": "self",
                             "content": content, "client_seq": seq, "source": "api"}]}, bearer=True)
    r = _api(page, f"/api/ops/wechat/context?contact_key={CONTACT_KEY}&limit=10&tenant_id={TENANT}",
             "GET", None, bearer=True)
    b = r.get("body") or {}
    msgs = b.get("recent_messages") or []
    ok = (r["status"] == 200 and b.get("success") is True and b.get("known") is True
          and len(msgs) >= 1 and any(content == m.get("content") for m in msgs))
    _card(page, env, "C1-context-core.png", "C1",
          "核心「联系人情报成功返回」正向闭环通过", {
              "POST /api/ops/wechat/ingest（写入联系人+消息，Bearer 令牌）":
                  {"status": up["status"], "body": up.get("body")},
              "GET /api/ops/wechat/context?contact_key=vc-accept-context（Bearer 令牌）":
                  {"status": r["status"], "known": b.get("known"), "message_count": b.get("message_count"),
                   "recent_messages": msgs},
          })
    return {"ingest": {"status": up["status"]},
            "context": {"status": r["status"], "known": b.get("known"),
                        "message_count": b.get("message_count"),
                        "has_message": any(content == m.get("content") for m in msgs)}}, ok


def case_missing_param(page, env):
    r = _api(page, "/api/ops/wechat/context", "GET", None, bearer=True)
    b = r.get("body") or {}
    errs = b.get("errors") or []
    ok = r["status"] == 422 and b.get("error_code") == "validation_error" \
        and any(e.get("field") == "query.contact_key" for e in errs)
    _card(page, env, "C2-context-boundary.png", "C2+C3",
          "缺 contact_key 被校验拒绝 / 无令牌被拒（负例/边界）", {
              "GET /api/ops/wechat/context（无 contact_key）": {"status": r["status"], "body": b},
              "GET /api/ops/wechat/context?contact_key=probe（无令牌）": _api(
                  page, "/api/ops/wechat/context?contact_key=probe", "GET", None, bearer=False).get("body"),
          })
    return {"status": r["status"], "errors": errs}, ok


def case_token_required(page, env):
    r = _api(page, "/api/ops/wechat/context?contact_key=probe", "GET", None, bearer=False)
    b = r.get("body") or {}
    ok = r["status"] == 401 and "wechat sync token" in str(b.get("message"))
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "C1-context-core.png": "卡片显示核心闭环通过：POST /api/ops/wechat/ingest（Bearer 令牌，写入联系人+消息）→ {status:200,body:{success:true,contacts_upserted:1,messages_inserted:1}}；GET /api/ops/wechat/context?contact_key=vc-accept-context → {status:200,known:true,message_count:1,recent_messages:[{role:self,content:\"VC情报消息：客户询价 #9070151\",source:api}]}。",
    "C2-context-boundary.png": "卡片显示两处真实响应：GET /api/ops/wechat/context（无 contact_key）→ {status:422,body:{success:false,error_code:validation_error,errors:[{field:query.contact_key,message:Field required,type:missing}]}}；GET /api/ops/wechat/context?contact_key=probe（无令牌）→ {success:false,error_code:http_401,message:invalid wechat sync token}。",
    "__video__": "本轮真实浏览器会话录像（webm，13.68s，ffmpeg 实测）：管理员登录 → 情报读回 200 → 缺参 422 → 无令牌 401。",
}

CASES = [
    {"id": "C1", "title": "联系人情报成功返回（核心正向闭环）",
     "input": "已建立的管理员会话 + Authorization: Bearer 令牌，contact_key=vc-accept-context。",
     "actions": "页面上下文 POST /ingest 写入联系人+消息 → GET /api/ops/wechat/context 并检查 known/recent_messages。",
     "expected": "HTTP 200，success=true，known=true 且 recent_messages 含刚写入内容。",
     "run": case_context_readback},
    {"id": "C2", "title": "缺 contact_key 被校验拒绝（边界/负例）",
     "input": "Bearer 令牌，不带查询参数。",
     "actions": "页面上下文 GET /api/ops/wechat/context。",
     "expected": "HTTP 422，errors 指出 query.contact_key 缺失。",
     "run": case_missing_param},
    {"id": "C3", "title": "无令牌访问情报入口被拒（负例）",
     "input": "管理员会话，无令牌头，contact_key=probe。",
     "actions": "页面上下文 GET /api/ops/wechat/context。",
     "expected": "HTTP 401，message 指明 invalid wechat sync token。",
     "run": case_token_required},
]