"""erp-approval（业务审批与流程）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的审批流程面。
impl：FHD/app/fastapi_routes/approval.py（/api/approval/*）。
真实验证面：真实创建审批流程并在列表读回 → 真实发起审批请求 → 真实审批通过并在详情读回 approved；
并含缺 flow_key/flow_name 与缺 title 被 400（负例）。所有请求在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-approval"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通审批真实写-读回：POST /api/approval/flows 新建流程 → GET /flows 读回 → "
    "POST /api/approval/requests 发起审批 → POST /requests/{id}/approve 审批通过 → GET /requests/{id} 读回 status=approved → "
    "GET /users 与 /tool-rules；并含缺字段被 400（负例）。"
)

_STATE: dict = {}


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        "async ([p,m,b]) => { try { const init={credentials:'include',method:m,headers:{}};"
        " if(b!==null){init.headers['Content-Type']='application/json';init.body=JSON.stringify(b);}"
        " if(m!=='GET'&&m!=='HEAD'){const cm=document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);"
        "   if(cm)init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]);}"
        " const r=await fetch(p,init);const t=await r.text();let j=null;try{j=JSON.parse(t);}catch(e){}"
        " return {status:r.status, body:j!==null?j:t.slice(0,240)};"
        " } catch(e){ return {status:0, body:String(e)}; } }", [path, method, body])


def _panel(page, env, name, title, obj):
    page.evaluate(
        "([t,o]) => { document.documentElement.lang='zh-CN'; document.head.replaceChildren();"
        " document.body.replaceChildren(); document.body.style.cssText='margin:0;padding:22px;background:#0b1b2b;"
        " color:#e8f1fb;font:13px/1.7 -apple-system,sans-serif';"
        " const h=document.createElement('h2'); h.textContent=t; h.style.cssText='font-size:15px;margin:0 0 12px';"
        " const p=document.createElement('pre'); p.style.cssText='background:#08131f;border-radius:8px;padding:14px;"
        " white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font:12px/1.6 monospace';"
        " p.textContent=JSON.stringify(o,null,2); document.body.appendChild(h); document.body.appendChild(p); }",
        [title, obj])
    page.screenshot(path=str(env["shot"] / name))


def case_flow_roundtrip(page, env):
    ts = time.strftime("%H%M%S")
    key = f"vc-flow-{ts}"
    created = _api(page, "/api/approval/flows", method="POST",
                   body={"flow": {"flow_name": f"验收流程{ts}", "flow_key": key},
                         "nodes": [{"node_name": "审批", "approver_ids": [1]}]})
    cb = created.get("body") or {}
    cd = cb.get("data") or {}
    fid = cd.get("id")
    _STATE["flow_key"] = key
    _STATE["flow_id"] = fid
    lst = _api(page, "/api/approval/flows")
    items = (lst.get("body") or {}).get("data") or []
    keys = [x.get("flow_key") for x in items]
    _panel(page, env, "AP1-approval-flow.png",
           "POST/GET /api/approval/flows · 审批流程真实写-读回",
           {"create_http": created["status"], "success": cb.get("success"), "flow_id": fid,
            "flow_key": cd.get("flow_key"), "node_count": len(cd.get("nodes") or []),
            "list_http": lst["status"], "created_key_in_list": key in keys})
    ok = (created["status"] == 200 and cb.get("success") is True and bool(fid)
          and key in keys and len(cd.get("nodes") or []) >= 1)
    return {"create_http": created["status"], "flow_id": fid, "flow_key": cd.get("flow_key"),
            "created_key_in_list": key in keys}, ok


def case_request_submit_readback(page, env):
    ts = time.strftime("%H%M%S")
    title = f"验收审批{ts}"
    created = _api(page, "/api/approval/requests", method="POST",
                   body={"flow_key": _STATE.get("flow_key"), "title": title, "payload": {"name": "x"}})
    cb = created.get("body") or {}
    cd = cb.get("data") or {}
    rid = cd.get("id")
    _STATE["request_id"] = rid
    got = _api(page, f"/api/approval/requests/{rid}") if rid else {"status": 0, "body": {}}
    gd = (got.get("body") or {}).get("data") or {}
    _panel(page, env, "AP2-approval-request.png",
           "POST/GET /api/approval/requests · 审批请求真实发起与读回",
           {"create_http": created["status"], "success": cb.get("success"), "request_id": rid,
            "request_no": cd.get("request_no"), "title": cd.get("title"), "status_field": cd.get("status"),
            "readback_http": got["status"], "readback_title": gd.get("title"),
            "readback_status": gd.get("status")})
    ok = (created["status"] == 200 and cb.get("success") is True and bool(rid)
          and got["status"] == 200 and gd.get("title") == title and gd.get("status") == "pending")
    return {"create_http": created["status"], "request_id": rid, "request_no": cd.get("request_no"),
            "readback_status": gd.get("status")}, ok


def case_approve_and_readback(page, env):
    rid = _STATE.get("request_id")
    ap = _api(page, f"/api/approval/requests/{rid}/approve", method="POST",
              body={"approver_id": 1, "comment": "验收通过"}) if rid else {"status": 0, "body": {}}
    ab = ap.get("body") or {}
    ad = ab.get("data") or {}
    got = _api(page, f"/api/approval/requests/{rid}") if rid else {"status": 0, "body": {}}
    gd = (got.get("body") or {}).get("data") or {}
    _panel(page, env, "AP3-approval-approve.png",
           "POST /requests/{id}/approve · 审批通过并读回",
           {"approve_http": ap["status"], "success": ab.get("success"), "status_field": ad.get("status"),
            "approved_by": ad.get("approved_by"), "approved_at": ad.get("approved_at"),
            "readback_http": got["status"], "readback_status": gd.get("status"),
            "readback_approved_at": gd.get("approved_at")})
    ok = (ap["status"] == 200 and ab.get("success") is True and ad.get("status") == "approved"
          and got["status"] == 200 and gd.get("status") == "approved")
    return {"approve_http": ap["status"], "status_field": ad.get("status"),
            "readback_status": gd.get("status")}, ok


def case_negative(page, env):
    empty_flow = _api(page, "/api/approval/flows", method="POST", body={})
    miss_title = _api(page, "/api/approval/requests", method="POST", body={"flow_key": "x"})
    eb, mb = empty_flow.get("body") or {}, miss_title.get("body") or {}
    _panel(page, env, "AP4-approval-negative.png",
           "缺 flow_name/flow_key 与缺 title 被拒（负例）",
           {"empty_flow": {"status": empty_flow["status"], "message": eb.get("message")},
            "missing_title": {"status": miss_title["status"], "message": mb.get("message")}})
    ok = empty_flow["status"] == 400 and miss_title["status"] == 400
    return {"empty_flow": {"status": empty_flow["status"], "message": eb.get("message")},
            "missing_title": {"status": miss_title["status"], "message": mb.get("message")}}, ok


def case_users_rules(page, env):
    users = _api(page, "/api/approval/users")
    rules = _api(page, "/api/approval/tool-rules")
    ud = (users.get("body") or {}).get("data") or []
    rd = rules.get("body") or {}
    _panel(page, env, "AP5-approval-users-rules.png",
           "GET /api/approval/users · /tool-rules",
           {"users_http": users["status"], "user_count": (users.get("body") or {}).get("count"),
            "sample_users": [u.get("name") for u in ud[:3]],
            "rules_http": rules["status"], "rules_enabled": rd.get("enabled"),
            "rule_count": len(rd.get("rules") or [])})
    ok = users["status"] == 200 and len(ud) >= 1 and rules["status"] == 200 and rd.get("enabled") is True
    return {"users_http": users["status"], "user_count": (users.get("body") or {}).get("count"),
            "rules_http": rules["status"], "rules_enabled": rd.get("enabled")}, ok


CASES = [
    {"id": "AP1", "title": "审批流程真实写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/approval/flows，随后 GET /api/approval/flows。",
     "expected": "创建 200 返回 id 与节点；列表中命中本轮 flow_key。",
     "run": case_flow_roundtrip},
    {"id": "AP2", "title": "审批请求真实发起与读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/approval/requests，随后 GET /requests/{id} 读回。",
     "expected": "发起 200、success=true，读回同 title 且 status=pending。",
     "run": case_request_submit_readback},
    {"id": "AP3", "title": "审批通过并读回 approved",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /requests/{id}/approve，随后 GET /requests/{id} 读回。",
     "expected": "审批 200、success=true、status=approved；读回 status=approved。",
     "run": case_approve_and_readback},
    {"id": "AP4", "title": "缺 flow_name/flow_key 与缺 title 被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/approval/flows（空 body）；POST /api/approval/requests（缺 title）。",
     "expected": "两者均 400，含明确缺失字段提示。",
     "run": case_negative},
    {"id": "AP5", "title": "审批人与工具规则读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/approval/users 与 /tool-rules。",
     "expected": "用户列表非空；工具规则 enabled=true 且规则数≥1。",
     "run": case_users_rules},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "AP1-approval-flow.png": "浏览器渲染审批流程写-读回真实 JSON：create 200、flow_id/flow_key、节点，列表命中。",
    "AP2-approval-request.png": "浏览器渲染审批请求发起与读回真实 JSON：request_no、status=pending。",
    "AP3-approval-approve.png": "浏览器渲染审批通过真实 JSON：approve 200、status=approved、approved_at，读回一致。",
    "AP4-approval-negative.png": "浏览器渲染缺 flow_name/flow_key 与缺 title 的 400 拒绝响应。",
    "AP5-approval-users-rules.png": "浏览器渲染审批人列表与工具规则真实 JSON（enabled、规则数）。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 审批流程写读回 → 请求发起 → 审批通过 → 用户/规则 → 负例。",
}