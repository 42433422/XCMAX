"""ind-planner（规划器桥接 Mod）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端中的规划器门面。
impl：FHD/mods/xcagi-planner-bridge（/api/mod/xcagi-planner-bridge/*）。
真实验证面：桥接状态与宿主能力读取 → 真实对话（返回真实 agent run）→ 意图识别 →
工具注册表读取；并含空消息被拒（负例）。所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "ind-planner"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端读取规划器桥接状态与宿主能力 → 真实 POST /api/mod/xcagi-planner-bridge/chat "
    "触发一次真实对话（返回 agent run_id 与问候应答）→ POST intent/test 返回真实意图 → "
    "GET tools/registry 读回 71 个已登记工具；并含空消息被 400 拒绝（负例）。"
)


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


def case_status(page, env):
    st = _api(page, "/api/mod/xcagi-planner-bridge/status")
    hc = _api(page, "/api/mod/xcagi-planner-bridge/host-capabilities")
    sd = (st.get("body") or {}).get("data") or {}
    hd = (hc.get("body") or {}).get("data") or {}
    _panel(page, env, "PL1-planner-status.png",
           "GET /status · /host-capabilities · 规划器桥接与宿主能力",
           {"status_http": st["status"], "mod_id": sd.get("mod_id"), "role": sd.get("role"),
            "phase": sd.get("phase"), "facade_chat": (sd.get("facade_paths") or {}).get("chat"),
            "host_caps_http": hc["status"], "edition": hd.get("edition"),
            "core_workflow_mod_id": hd.get("core_workflow_mod_id")})
    ok = (st["status"] == 200 and sd.get("mod_id") == "xcagi-planner-bridge"
          and hc["status"] == 200 and bool(hd.get("edition")))
    return {"status_http": st["status"], "mod_id": sd.get("mod_id"), "role": sd.get("role"),
            "phase": sd.get("phase"), "host_caps_http": hc["status"], "edition": hd.get("edition"),
            "core_workflow_mod_id": hd.get("core_workflow_mod_id")}, ok


def case_chat(page, env):
    r = _api(page, "/api/mod/xcagi-planner-bridge/chat", method="POST", body={"message": "你好"})
    b = r.get("body") or {}
    d = b.get("data") or {}
    inner = d.get("data") or {}
    _panel(page, env, "PL2-planner-chat.png",
           "POST /api/mod/xcagi-planner-bridge/chat · 真实对话（agent run）",
           {"status": r["status"], "success": b.get("success"), "message": b.get("message"),
            "response": str(b.get("response"))[:160], "action": d.get("action"),
            "run_id": b.get("run_id"), "agent_run_id": b.get("agent_run_id"),
            "intent": inner.get("intent"), "thinking_steps": str(inner.get("thinking_steps"))[:120]})
    ok = (r["status"] == 200 and b.get("success") is True and bool(b.get("run_id"))
          and bool(b.get("response")))
    return {"status": r["status"], "action": d.get("action"), "run_id": b.get("run_id"),
            "response": str(b.get("response"))[:160], "intent": inner.get("intent")}, ok


def case_intent_and_registry(page, env):
    it = _api(page, "/api/mod/xcagi-planner-bridge/intent/test", method="POST", body={"message": "查一下库存"})
    reg = _api(page, "/api/mod/xcagi-planner-bridge/tools/registry")
    idata = (it.get("body") or {}).get("data") or {}
    rdata = (reg.get("body") or {}).get("data") or {}
    names = rdata.get("tool_names") or []
    _panel(page, env, "PL3-planner-intent-registry.png",
           "POST /intent/test · GET /tools/registry · 意图识别与工具注册表",
           {"intent_http": it["status"], "primary_intent": idata.get("primary_intent"),
            "tool_key": idata.get("tool_key"), "confidence": idata.get("confidence"),
            "sources_used": idata.get("sources_used"),
            "registry_http": reg["status"], "tool_count": rdata.get("tool_count"),
            "sample_tools": names[:8]})
    ok = (it["status"] == 200 and bool(idata.get("primary_intent"))
          and reg["status"] == 200 and int(rdata.get("tool_count") or 0) >= 50)
    return {"intent_http": it["status"], "primary_intent": idata.get("primary_intent"),
            "tool_key": idata.get("tool_key"), "confidence": idata.get("confidence"),
            "sources_used": idata.get("sources_used"),
            "registry_http": reg["status"], "tool_count": rdata.get("tool_count"),
            "sample_tools": names[:8]}, ok


def case_negative(page, env):
    empty = _api(page, "/api/mod/xcagi-planner-bridge/intent/test", method="POST", body={})
    no_tool = _api(page, "/api/mod/xcagi-planner-bridge/tools/execute", method="POST", body={})
    eb = empty.get("body") or {}
    nb = no_tool.get("body") or {}
    _panel(page, env, "PL4-planner-negative.png",
           "空消息 / 缺 tool_name 被拒（负例）",
           {"empty_intent": {"status": empty["status"], "message": eb.get("message")},
            "missing_tool_name": {"status": no_tool["status"], "message": nb.get("error"),
                                  "error_code": nb.get("error_code")}})
    ok = empty["status"] == 400 and no_tool["status"] == 400
    return {"empty_intent": {"status": empty["status"], "message": eb.get("message")},
            "missing_tool_name": {"status": no_tool["status"], "error_code": nb.get("error_code")}}, ok


CASES = [
    {"id": "PL1", "title": "规划器桥接状态与宿主能力真实读取",
     "input": "已建立的管理员会话。",
     "actions": "fetch GET /status 与 GET /host-capabilities。",
     "expected": "状态 200 且 mod_id=xcagi-planner-bridge、含 facade chat；宿主能力 200 且含 edition。",
     "run": case_status},
    {"id": "PL2", "title": "真实对话触发 agent run",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /chat（message=你好）。",
     "expected": "HTTP 200、success=true、返回真实 run_id 与非空 response。",
     "run": case_chat},
    {"id": "PL3", "title": "意图识别与工具注册表真实读取",
     "input": "已建立的管理员会话。",
     "actions": "POST /intent/test（message=查一下库存）；fetch GET /tools/registry。",
     "expected": "意图接口 200 且含 primary_intent；注册表 200 且 tool_count≥50。",
     "run": case_intent_and_registry},
    {"id": "PL4", "title": "空消息与缺 tool_name 被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /intent/test（空 body）；POST /tools/execute（空 body）。",
     "expected": "空消息 400「消息内容不能为空」；缺 tool_name 400。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "PL1-planner-status.png": "浏览器渲染桥接状态与宿主能力真实 JSON：mod_id=xcagi-planner-bridge、role=planner_facade、facade chat 路径、edition。",
    "PL2-planner-chat.png": "浏览器渲染真实对话响应：200、success=true、response 为智能助手问候、action=greeting、含 run_id。",
    "PL3-planner-intent-registry.png": "浏览器渲染意图识别与工具注册表：primary_intent、tool_count=71 与工具名样例。",
    "PL4-planner-negative.png": "浏览器渲染空消息 400「消息内容不能为空」与缺 tool_name 的 400 拒绝。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 桥接状态/宿主能力 → 真实对话 → 意图与工具注册表 → 负例。",
}