"""erp-replenishment（库存补货建议）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的补货建议面。
impl：FHD/app/services/replenishment_service.py（经已登记 ERP 能力 inventory.replenishment_suggest，
      由 planner 门面 /api/mod/xcagi-planner-bridge/tools/execute 以真实 HTTP 门面执行）。
真实验证面：真实执行补货建议能力 → 低库存预警读取 → 规划器对话补货意图 → 汇总；
并含未登记能力被拒（负例）。所有请求均在真实浏览器页面上下文发起。
"""

import json
import time

FEATURE = "erp-replenishment"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端经 planner 门面真实执行已登记 ERP 能力 inventory.replenishment_suggest（低风险自动执行）→ "
    "GET /api/inventory/alert 与 /combined-alert 读取低库存/物料预警 → POST /api/mod/xcagi-planner-bridge/chat "
    "触发补货意图并返回真实应答；并含未登记/错误动作被拒（负例）。"
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


def _cap(page, tool, action, params):
    return _api(page, "/api/mod/xcagi-planner-bridge/tools/execute", method="POST",
                body={"tool_name": "execute_erp_capability",
                      "arguments": {"tool_id": tool, "action": action, "params": params or {}}})


def case_replenishment(page, env):
    r = _cap(page, "inventory", "replenishment_suggest", {"threshold": 100, "per_page": 50})
    b = r.get("body") or {}
    d = b.get("data") or {}
    result = d.get("result")
    parsed = json.loads(result) if isinstance(result, str) and result.strip().startswith("{") else {}
    _panel(page, env, "RP1-replenishment.png",
           "执行 ERP 能力 inventory.replenishment_suggest（真实门面）",
           {"http": r["status"], "success": b.get("success"), "tool_name": d.get("tool_name"),
            "result_success": parsed.get("success"), "result_message": parsed.get("message"),
            "capability": parsed.get("capability"), "approval_reason": (parsed.get("approval") or {}).get("risk_decision")})
    ok = (r["status"] == 200 and b.get("success") is True and parsed.get("success") is True
          and (parsed.get("capability") or {}).get("action") == "replenishment_suggest")
    return {"http": r["status"], "result_success": parsed.get("success"),
            "result_message": parsed.get("message"), "tool_id": (parsed.get("capability") or {}).get("tool_id")}, ok


def case_alerts(page, env):
    a = _api(page, "/api/inventory/alert")
    c = _api(page, "/api/inventory/combined-alert")
    low = _cap(page, "inventory", "low_stock_alert", {})
    ab, cb = a.get("body") or {}, c.get("body") or {}
    lb = low.get("body") or {}
    _panel(page, env, "RP2-replenishment-alerts.png",
           "GET 预警接口 · 执行 low_stock_alert 能力",
           {"alert_http": a["status"], "alert_count": ab.get("count"),
            "combined_http": c["status"], "total_alerts": cb.get("total_alerts"),
            "low_stock_cap_http": low["status"], "low_stock_result": str((lb.get("data") or {})).replace("'", '"')[:200]})
    ok = a["status"] == 200 and c["status"] == 200 and low["status"] == 200
    return {"alert_http": a["status"], "total_alerts": cb.get("total_alerts"),
            "low_stock_cap_http": low["status"]}, ok


def case_chat_intent(page, env):
    r = _api(page, "/api/mod/xcagi-planner-bridge/chat", method="POST", body={"message": "给我库存补货建议"})
    b = r.get("body") or {}
    d = b.get("data") or {}
    _panel(page, env, "RP3-replenishment-chat.png",
           "POST /api/mod/xcagi-planner-bridge/chat · 补货意图真实应答",
           {"status": r["status"], "success": b.get("success"), "response": str(b.get("response"))[:160],
            "intent": d.get("intent"), "run_id": b.get("run_id")})
    ok = r["status"] == 200 and b.get("success") is True and bool(b.get("response"))
    return {"status": r["status"], "response": str(b.get("response"))[:160], "intent": d.get("intent"),
            "run_id": b.get("run_id")}, ok


def case_negative(page, env):
    bad_tool = _cap(page, "no_such_tool", "x", {})
    bad_action = _cap(page, "inventory", "no_such_action", {})
    bt, ba = bad_tool.get("body") or {}, bad_action.get("body") or {}
    _panel(page, env, "RP4-replenishment-negative.png",
           "未登记 tool_id / action 被拒（负例）",
           {"unknown_tool": {"status": bad_tool["status"], "error": (bt.get("data") or {}).get("error"),
                             "error_code": (bt.get("data") or {}).get("error_code")},
            "unknown_action": {"status": bad_action["status"], "error": (ba.get("data") or {}).get("error"),
                               "error_code": (ba.get("data") or {}).get("error_code")}})
    ok = bad_tool["status"] == 400 and bad_action["status"] == 400
    return {"unknown_tool": {"status": bad_tool["status"]}, "unknown_action": {"status": bad_action["status"]}}, ok


CASES = [
    {"id": "RP1", "title": "真实执行补货建议能力",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "经 planner 门面执行 execute_erp_capability：inventory.replenishment_suggest。",
     "expected": "HTTP 200、success=true，能力执行成功且 action=replenishment_suggest。",
     "run": case_replenishment},
    {"id": "RP2", "title": "低库存预警读取与 low_stock_alert 能力执行",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "GET 预警接口；经 planner 执行 inventory.low_stock_alert。",
     "expected": "预警接口 200；low_stock_alert 能力 HTTP 200。",
     "run": case_alerts},
    {"id": "RP3", "title": "补货意图真实应答",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/mod/xcagi-planner-bridge/chat（message=给我库存补货建议）。",
     "expected": "200、success=true、返回非空应答与 run_id。",
     "run": case_chat_intent},
    {"id": "RP4", "title": "未登记 tool_id / action 被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "执行不存在的能力 tool_id 与不存在 action。",
     "expected": "两者均 400 被拒。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "RP1-replenishment.png": "浏览器渲染真实执行补货建议能力的响应：200、success=true、capability.action=replenishment_suggest 与风险门判定。",
    "RP2-replenishment-alerts.png": "浏览器渲染库存预警接口与 low_stock_alert 能力执行的真实 JSON。",
    "RP3-replenishment-chat.png": "浏览器渲染补货意图对话的真实应答（低库存状态说明）与 run_id。",
    "RP4-replenishment-negative.png": "浏览器渲染未登记 tool_id/action 的 400 拒绝响应。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 补货建议能力执行 → 预警 → 对话 → 负例。",
}