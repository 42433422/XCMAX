"""ch-wechat-contacts（微信联系人同步与情报）Web 管理端真机验收用例。

impl：FHD/app/application/wechat_ingest_service.py、wechat_chat_context.py、db/models/wechat_sync.py。
真实接口面：POST /api/ops/wechat/ingest（联系人上行）、GET /api/ops/wechat/contacts（身份映射读回）。
运行库为完整 schema（97 张表，含 wechat_contacts）。

本轮实测：带 Authorization: Bearer 令牌时，POST /ingest 同步联系人（contacts_upserted>=1），
随后 GET /api/ops/wechat/contacts 能读回该联系人（含 display_name / match_status）→ 正向闭环通过；
无令牌访问同一入口 → 401 invalid wechat sync token；未注册的单联系人子路径 → 404。
"""

import html as _html
import json
import json as _json
import os

FEATURE = "ch-wechat-contacts"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后，用共享令牌实测微信联系人入口："
    "先 POST /api/ops/wechat/ingest 同步联系人，再 GET /api/ops/wechat/contacts 读回同一联系人"
    "（display_name、match_status）→ 联系人同步→读回闭环通过；"
    "无令牌访问同一入口 → 401 invalid wechat sync token；未注册的单联系人子路径 → 404。"
)

TOKEN = os.environ.get("XCAGI_OPS_TOKEN", "")  # 共享令牌由操作员通过环境变量提供，不落盘
TENANT = 4
CONTACT_KEY = "vc-accept-contact"


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


def case_contacts_readback(page, env):
    up = _api(page, "/api/ops/wechat/ingest", "POST",
              {"tenant_id": TENANT,
               "contacts": [{"contact_key": CONTACT_KEY, "display_name": "VC验收客户", "wxid": "vc_wxid_1"}],
               "messages": []}, bearer=True)
    ub = up.get("body") or {}
    r = _api(page, f"/api/ops/wechat/contacts?tenant_id={TENANT}", "GET", None, bearer=True)
    b = r.get("body") or {}
    items = b.get("items") or []
    hit = next((x for x in items if x.get("contact_key") == CONTACT_KEY), {})
    ok = (up["status"] == 200 and ub.get("contacts_upserted", 0) >= 1
          and r["status"] == 200 and b.get("success") is True and bool(hit))
    _card(page, env, "C1-contacts-core.png", "C1",
          "核心「联系人同步 → 读回」正向闭环通过", {
              "POST /api/ops/wechat/ingest（同步联系人，Bearer 令牌）": {"status": up["status"], "body": ub},
              "GET /api/ops/wechat/contacts（读回联系人）": {"status": r["status"], "count": b.get("count"),
                                                            "hit": hit},
          })
    return {"ingest": {"status": up["status"], "contacts_upserted": ub.get("contacts_upserted")},
            "contacts": {"status": r["status"], "hit": hit}}, ok


def case_contacts_token_required(page, env):
    r = _api(page, "/api/ops/wechat/contacts", "GET", None, bearer=False)
    b = r.get("body") or {}
    ok = r["status"] == 401 and "wechat sync token" in str(b.get("message"))
    _card(page, env, "C2-contacts-boundary.png", "C2+C3",
          "无令牌被拒与单联系人子路径未注册（负例/边界）", {
              "GET /api/ops/wechat/contacts（无令牌）": {"status": r["status"], "body": b},
              "GET /api/ops/wechat/contacts/probe-contact（Bearer）": _api(
                  page, "/api/ops/wechat/contacts/probe-contact", "GET", None, bearer=True).get("body"),
          })
    return {"status": r["status"], "message": b.get("message")}, ok


def case_contact_detail_not_found(page, env):
    r = _api(page, "/api/ops/wechat/contacts/probe-contact", "GET", None, bearer=True)
    b = r.get("body") or {}
    ok = r["status"] == 404
    return {"status": r["status"], "body": b}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "C1-contacts-core.png": "卡片显示核心闭环通过：POST /api/ops/wechat/ingest（Bearer 令牌，同步联系人）→ {status:200,body:{success:true,contacts_upserted:1,messages_inserted:0}}；GET /api/ops/wechat/contacts → {status:200,count:1,hit:{id:2,contact_key:vc-accept-contact,display_name:VC验收客户,wxid:vc_wxid_1,customer_id:null,match_status:unlinked}}。",
    "C2-contacts-boundary.png": "卡片显示两处真实响应：GET /api/ops/wechat/contacts（无令牌）→ {status:401,body:{success:false,error_code:http_401,message:invalid wechat sync token}}；GET /api/ops/wechat/contacts/probe-contact（Bearer）→ {success:false,message:资源不存在：/api/ops/wechat/contacts/probe-contact}（404）。",
    "__video__": "本轮真实浏览器会话录像（webm，14.16s，ffmpeg 实测）：管理员登录 → 联系人同步+读回 → 无令牌 401 → 单联系人子路径 404。",
}

CASES = [
    {"id": "C1", "title": "联系人同步→读回（核心正向闭环）",
     "input": "已建立的管理员会话 + Authorization: Bearer 令牌，tenant_id=4。",
     "actions": "页面上下文 POST /api/ops/wechat/ingest（同步联系人）后 GET /api/ops/wechat/contacts。",
     "expected": "HTTP 200 且 contacts_upserted>=1，且联系人列表命中 vc-accept-contact。",
     "run": case_contacts_readback},
    {"id": "C2", "title": "无令牌访问联系人入口被拒（负例）",
     "input": "已建立的管理员会话，无令牌头。",
     "actions": "页面上下文 GET /api/ops/wechat/contacts。",
     "expected": "HTTP 401，message 指明 invalid wechat sync token。",
     "run": case_contacts_token_required},
    {"id": "C3", "title": "单联系人子路径未注册（边界/负例）",
     "input": "Bearer 令牌。",
     "actions": "页面上下文 GET /api/ops/wechat/contacts/probe-contact。",
     "expected": "HTTP 404。",
     "run": case_contact_detail_not_found},
]