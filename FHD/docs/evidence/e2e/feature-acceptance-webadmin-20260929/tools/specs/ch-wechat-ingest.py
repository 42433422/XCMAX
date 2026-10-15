"""ch-wechat-ingest（微信消息接入）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/wechat_ingest.py → app/application/wechat_ingest_service.py。
真实接口面：POST /api/ops/wechat/ingest（X-Wechat-Token 或 Authorization: Bearer <token>）。
本轮环境：AUTONOMY_WEBHOOK_TOKEN=<操作员提供的共享令牌>；运行库为完整 schema
（/Users/Shared/xcmax-webadmin-vc-full/data/xcagi.db，97 张表，含 wechat_contacts / wechat_messages）。

本轮实测（关键）：
  * CSRF 中间件仅在带 `Authorization: Bearer` 时豁免 /api/ops/wechat；仅带 X-Wechat-Token 的 POST 会先被
    403 CSRF token missing 拦下 → 真实可用令牌形态是 Bearer。
  * POST /api/ops/wechat/ingest 未向 _auth 传 request，故无 admin 会话旁路：缺令牌 → 401。
  * 带正确 Bearer 的真实报文：联系人 + 消息幂等入库（contacts_upserted>=1、messages_inserted>=1），
    响应内 context 直接回流行；随后 GET /api/ops/wechat/contacts 与 GET /api/ops/wechat/context
    均能读回刚写入的联系人与消息 → 「真实上行入库 → 读回」正向闭环通过。
"""

import html as _html
import json
import json as _json
import os
import time

FEATURE = "ch-wechat-ingest"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后，用共享令牌实测微信消息接入入口："
    "以 Authorization: Bearer <token> 发送真实报文（联系人+消息）→ 200 且 contacts_upserted>=1、messages_inserted>=1；"
    "随后 GET /api/ops/wechat/contacts、GET /api/ops/wechat/context 读回刚写入的联系人与消息，"
    "「真实上行入库 → 读回」闭环打通；空心跳 200；缺令牌 401；缺 CSRF 403。"
)

TOKEN = os.environ.get("XCAGI_OPS_TOKEN", "")  # 共享令牌由操作员通过环境变量提供，不落盘
TENANT = 4
CONTACT_KEY = "vc-accept-contact"


def _api(page, path, method="GET", body=None, bearer=False, with_csrf=True):
    return page.evaluate(
        """async ([p,m,b,useBearer,useCsrf]) => { try {
            const init={credentials:'include', method:m};
            const h = {};
            if (b!==null){ h['Content-Type']='application/json'; init.body=JSON.stringify(b); }
            if (useBearer) h['Authorization']='Bearer %s';
            if (useCsrf && m!=='GET' && m!=='HEAD'){ const cm=document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
              if (cm) h['X-CSRF-Token']=decodeURIComponent(cm[1]); }
            init.headers=h;
            const r=await fetch(p, init); const t=await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, body:j!==null?j:t.slice(0,400)};
        } catch(e){ return {status:0, body:String(e)}; } }""" % TOKEN,
        [path, method, body, bearer, with_csrf])


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


def case_heartbeat_bearer(page, env):
    r = _api(page, "/api/ops/wechat/ingest", "POST", {}, bearer=True)
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and b.get("contacts_upserted") == 0
    _card(page, env, "I1-ingest-auth.png", "I1+I3+I4",
          "共享令牌鉴权/协议面真实可用（Bearer），缺令牌与缺 CSRF 被拒", {
              "POST 空心跳（Bearer 令牌）": {"status": r["status"], "body": b},
              "POST（无令牌，仅会话+CSRF）": _api(page, "/api/ops/wechat/ingest", "POST", {}, bearer=False).get("body"),
              "POST（无 CSRF 头）": _api(page, "/api/ops/wechat/ingest", "POST", {}, bearer=False, with_csrf=False).get("body"),
          })
    return {"status": r["status"], "body": b}, ok


def case_ingest_real_payload(page, env):
    seq = int(time.time()) % 100000000
    content = f"VC验收消息：你好，这是真机上行 #{seq}"
    payload = {"tenant_id": TENANT,
               "contacts": [{"contact_key": CONTACT_KEY, "display_name": "VC验收客户", "wxid": "vc_wxid_1"}],
               "messages": [{"contact_key": CONTACT_KEY, "role": "other",
                             "content": content, "client_seq": seq, "source": "api"}]}
    r = _api(page, "/api/ops/wechat/ingest", "POST", payload, bearer=True)
    b = r.get("body") or {}
    listed = _api(page, f"/api/ops/wechat/contacts?tenant_id={TENANT}", "GET", None, bearer=True)
    items = (listed.get("body") or {}).get("items") or []
    read_back = _api(page, f"/api/ops/wechat/context?contact_key={CONTACT_KEY}&tenant_id={TENANT}",
                     "GET", None, bearer=True)
    rb = read_back.get("body") or {}
    msgs = rb.get("recent_messages") or []
    ok = (r["status"] == 200 and b.get("contacts_upserted", 0) >= 1 and b.get("messages_inserted", 0) >= 1
          and any(x.get("contact_key") == CONTACT_KEY for x in items)
          and rb.get("known") is True and any(content == m.get("content") for m in msgs))
    _card(page, env, "I2-ingest-core.png", "I2",
          "核心「真实上行入库 → 读回联系人 / 上下文」正向闭环通过", {
              "POST /api/ops/wechat/ingest（真实联系人+消息，Bearer 令牌）": {"status": r["status"], "body": b},
              "GET /api/ops/wechat/contacts（读回联系人）": {"status": listed["status"],
                                                            "hit": any(x.get("contact_key") == CONTACT_KEY for x in items),
                                                            "count": (listed.get("body") or {}).get("count")},
              "GET /api/ops/wechat/context（读回上下文）": {"status": read_back["status"], "known": rb.get("known"),
                                                           "message_count": rb.get("message_count"),
                                                           "recent_messages": msgs},
          })
    return {"ingest": {"status": r["status"], "body": b},
            "contacts": {"status": listed["status"], "hit": any(x.get("contact_key") == CONTACT_KEY for x in items)},
            "context": {"status": read_back["status"], "known": rb.get("known"),
                        "message_count": rb.get("message_count"),
                        "has_message": any(content == m.get("content") for m in msgs)}}, ok


def case_token_required(page, env):
    r = _api(page, "/api/ops/wechat/ingest", "POST", {}, bearer=False)
    b = r.get("body") or {}
    ok = r["status"] == 401 and "wechat sync token" in str(b.get("message"))
    return {"status": r["status"], "message": b.get("message")}, ok


def case_csrf_required(page, env):
    r = _api(page, "/api/ops/wechat/ingest", "POST", {}, bearer=False, with_csrf=False)
    b = r.get("body") or {}
    ok = r["status"] == 403 and "CSRF" in str(b.get("message"))
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "I1-ingest-auth.png": "卡片汇总三处真实响应：POST /api/ops/wechat/ingest 空心跳（Authorization: Bearer 令牌）→ {status:200,body:{success:true,contacts_upserted:0,messages_inserted:0,messages_skipped:0,context:{}}}；POST 无令牌 → {success:false,error_code:http_401,message:invalid wechat sync token,path:/api/ops/wechat/ingest}；POST 无 CSRF 头 → {success:false,message:CSRF token missing}。",
    "I2-ingest-core.png": "卡片显示核心闭环通过：POST /api/ops/wechat/ingest（Bearer 令牌，真实联系人+消息）→ {status:200,body:{success:true,contacts_upserted:1,messages_inserted:1,messages_skipped:0}}；GET /api/ops/wechat/contacts → {status:200,hit:true,count:1}；GET /api/ops/wechat/context → {status:200,known:true,message_count:1,recent_messages:[{role:other,content:\"VC验收消息：你好，这是真机上行 #9070114\",source:api}]}。",
    "__video__": "本轮真实浏览器会话录像（webm，18.92s，ffmpeg 实测）：管理员登录 → 心跳鉴权 200 → 真实上行入库+读回闭环 → 无令牌 401 → 缺 CSRF 403。",
}

CASES = [
    {"id": "I1", "title": "共享令牌鉴权/协议面真实可用（Bearer 心跳 200）",
     "input": "已建立的管理员会话 + Authorization: Bearer <操作员提供的共享令牌>。",
     "actions": "页面上下文 POST /api/ops/wechat/ingest（空心跳载荷）。",
     "expected": "HTTP 200，success=true，contacts_upserted=0。",
     "run": case_heartbeat_bearer},
    {"id": "I2", "title": "真实上行入库→读回联系人/上下文（核心正向闭环）",
     "input": "Bearer 令牌 + 真实联系人/消息报文（tenant_id=4）。",
     "actions": "页面上下文 POST /api/ops/wechat/ingest → GET /api/ops/wechat/contacts → GET /api/ops/wechat/context。",
     "expected": "200 且 contacts_upserted>=1、messages_inserted>=1；联系人列表命中；上下文 known=true 且含该消息。",
     "run": case_ingest_real_payload},
    {"id": "I3", "title": "无令牌被拒（负例）",
     "input": "已建立的管理员会话，无 Authorization/令牌头。",
     "actions": "页面上下文 POST /api/ops/wechat/ingest。",
     "expected": "HTTP 401，message 指明 invalid wechat sync token。",
     "run": case_token_required},
    {"id": "I4", "title": "缺 CSRF 双提交被拒（负例/边界）",
     "input": "管理员会话，POST 无 X-CSRF-Token。",
     "actions": "页面上下文 POST /api/ops/wechat/ingest。",
     "expected": "HTTP 403，message=CSRF token missing。",
     "run": case_csrf_required},
]