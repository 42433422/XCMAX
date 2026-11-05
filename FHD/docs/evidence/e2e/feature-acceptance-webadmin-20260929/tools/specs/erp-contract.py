"""erp-contract（合同单据）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的销售合同生命周期面。
impl：FHD/app/services/contract_lifecycle.py、FHD/app/fastapi_routes/sales_contract_api.py。
真实验证面：合同状态读取 → 真实流转（transition）并在状态读回 → 销售合同/单据模板读取；
并含缺 market_user_id / status 的 422（负例）。所有请求在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-contract"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端走通合同生命周期真实写-读回：GET /api/contract-lifecycle/status?market_user_id=1 读取合同状态 → "
    "POST /api/contract-lifecycle/transition 真实流转到 pending_sign → 再次 GET status 读回新状态 → "
    "GET /api/sales-contract/templates 与 /api/document-templates 读取合同模板；并含缺参 422（负例）。"
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


def case_status_and_transition(page, env):
    before = _api(page, "/api/contract-lifecycle/status?market_user_id=1")
    bd = (before.get("body") or {}).get("data") or {}
    bt = ((bd.get("contract_lifecycle") or {}) or {}).get("status")
    tr = _api(page, "/api/contract-lifecycle/transition", method="POST",
              body={"market_user_id": 1, "status": "pending_sign", "note": "验收流转"})
    tb = tr.get("body") or {}
    td = tb.get("data") or {}
    pipeline = td.get("pipeline") or {}
    after = _api(page, "/api/contract-lifecycle/status?market_user_id=1")
    ad = (after.get("body") or {}).get("data") or {}
    at = ((ad.get("contract_lifecycle") or {}) or {}).get("status")
    _panel(page, env, "CT1-contract-transition.png",
           "GET/POST /api/contract-lifecycle/* · 合同状态真实读-写-读回",
           {"status_before_http": before["status"], "status_before": bt,
            "transition_http": tr["status"], "transition_success": tb.get("success"),
            "pipeline_stage": pipeline.get("stage"),
            "pipeline_contract_status": (pipeline.get("contract_lifecycle") or {}).get("status"),
            "status_after_http": after["status"], "status_after": at})
    ok = (before["status"] == 200 and tr["status"] == 200 and tb.get("success") is True
          and after["status"] == 200 and at == "pending_sign")
    return {"status_before": bt, "transition_http": tr["status"], "status_after": at,
            "pipeline_contract_status": (pipeline.get("contract_lifecycle") or {}).get("status")}, ok


def case_templates(page, env):
    sale = _api(page, "/api/sales-contract/templates")
    doc = _api(page, "/api/document-templates")
    sd = (sale.get("body") or {}).get("data") or []
    dd = (doc.get("body") or {}).get("data") or []
    _panel(page, env, "CT2-contract-templates.png",
           "GET /api/sales-contract/templates · /api/document-templates",
           {"sales_templates_http": sale["status"], "sales_count": len(sd),
            "sales_slugs": [x.get("slug") for x in sd],
            "document_templates_http": doc["status"], "document_count": len(dd),
            "document_roles": [x.get("role") for x in dd]})
    ok = sale["status"] == 200 and len(sd) >= 1 and doc["status"] == 200
    return {"sales_templates_http": sale["status"], "sales_count": len(sd),
            "document_templates_http": doc["status"], "document_count": len(dd)}, ok


def case_negative(page, env):
    no_user = _api(page, "/api/contract-lifecycle/status")
    no_status = _api(page, "/api/contract-lifecycle/transition", method="POST", body={"market_user_id": 1})
    nu, ns = no_user.get("body") or {}, no_status.get("body") or {}
    _panel(page, env, "CT3-contract-negative.png",
           "缺 market_user_id / status 被拒（负例）",
           {"status_without_user": {"status": no_user["status"], "error_code": nu.get("error_code"),
                                    "fields": [e.get("field") for e in (nu.get("errors") or [])]},
            "transition_without_status": {"status": no_status["status"], "error_code": ns.get("error_code"),
                                          "fields": [e.get("field") for e in (ns.get("errors") or [])]}})
    ok = no_user["status"] == 422 and no_status["status"] == 422
    return {"status_without_user": {"status": no_user["status"]},
            "transition_without_status": {"status": no_status["status"]}}, ok


CASES = [
    {"id": "CT1", "title": "合同状态真实读-写-读回",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "GET status?market_user_id=1 → POST transition(pending_sign) → GET status 读回。",
     "expected": "流转 200、success=true；再次读回 contract_lifecycle.status=pending_sign。",
     "run": case_status_and_transition},
    {"id": "CT2", "title": "合同模板真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/sales-contract/templates 与 /api/document-templates。",
     "expected": "两者均 200，销售合同模板数≥1。",
     "run": case_templates},
    {"id": "CT3", "title": "缺 market_user_id / status 被拒（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "GET status（缺 market_user_id）；POST transition（缺 status）。",
     "expected": "两者均 422 validation_error。",
     "run": case_negative},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "CT1-contract-transition.png": "浏览器渲染合同状态读-写-读回真实 JSON：流转 200、success=true，读回 status=pending_sign。",
    "CT2-contract-templates.png": "浏览器渲染销售合同与单据模板真实 JSON（slug/role）。",
    "CT3-contract-negative.png": "浏览器渲染缺 market_user_id 与缺 status 的 422 validation_error。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 合同状态读写读回 → 模板读取 → 负例。",
}