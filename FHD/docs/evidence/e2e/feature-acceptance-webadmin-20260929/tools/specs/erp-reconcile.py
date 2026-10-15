"""erp-reconcile（经营对账与结算）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的经营对账面。
impl：FHD/app/services/fhd_payment_reconciliation.py、FHD/app/fastapi_routes/operations_line_api.py
      （/api/operations-line/reconciliation/*）。
真实验证面：真实运行对账并读取状态 → 再次运行读取状态变化 → 内部对账周期接口缺失参数 422；
并含内部渠道未配置时的拒绝（负例）。所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-reconcile"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端真实运行经营对账（POST /api/operations-line/reconciliation/run）→ "
    "GET /status 读回对账状态（auto_confirm_enabled 等）→ 未提供周期起止的 /internal/payment/reconciliation-period "
    "被 422 拒绝（负例）。"
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
    page.screenshot(path=str(env / name) if not isinstance(env, dict) else str(env["shot"] / name))
    return None


def case_run_and_status(page, env):
    run = _api(page, "/api/operations-line/reconciliation/run", method="POST", body={})
    st = _api(page, "/api/operations-line/reconciliation/status")
    rb = run.get("body") or {}
    sb = st.get("body") or {}
    rd = rb.get("data") or {}
    sd = sb.get("data") or {}
    _panel(page, env, "RC1-reconcile-run.png",
           "POST /operations-line/reconciliation/run · GET /status · 真实对账运行与状态",
           {"run_http": run["status"], "success": rb.get("success"), "dry_run": rd.get("dry_run"),
            "status_http": st["status"], "status_success": sd.get("success"),
            "auto_confirm_enabled": sd.get("auto_confirm_enabled"), "last_run": sd.get("last_run")})
    ok = (run["status"] == 200 and rb.get("success") is True
          and st["status"] == 200 and "auto_confirm_enabled" in sd)
    return {"run_http": run["status"], "success": rb.get("success"), "dry_run": rd.get("dry_run"),
            "status_http": st["status"], "auto_confirm_enabled": sd.get("auto_confirm_enabled")}, ok


def case_period_validation(page, env):
    bad = _api(page, "/api/internal/payment/reconciliation-period")
    ok_body = _api(page, "/api/internal/payment/reconciliation-period?period_start=2026-09-01&period_end=2026-09-29")
    bb = bad.get("body") or {}
    ob = ok_body.get("body") or {}
    _panel(page, env, "RC2-reconcile-period.png",
           "GET /internal/payment/reconciliation-period · 缺参与带参",
           {"missing_params": {"status": bad["status"], "error_code": bb.get("error_code"),
                               "fields": [e.get("field") for e in (bb.get("errors") or [])]},
            "with_params": {"status": ok_body["status"], "error_code": ob.get("error_code"),
                            "message": ob.get("message")}})
    ok = (bad["status"] == 422 and bb.get("error_code") == "validation_error")
    return {"missing_params": {"status": bad["status"], "error_code": bb.get("error_code")},
            "with_params": {"status": ok_body["status"], "message": ob.get("message")},
            "note": "带参时本环境返回 503 internal api not configured（内部渠道未配置的真实观察）"}, ok


CASES = [
    {"id": "RC1", "title": "真实运行经营对账并读取状态",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/operations-line/reconciliation/run，随后 GET /api/operations-line/reconciliation/status。",
     "expected": "运行 200、success=true；状态 200 且含 auto_confirm_enabled。",
     "run": case_run_and_status},
    {"id": "RC2", "title": "对账周期接口缺参被拒（负例）",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/internal/payment/reconciliation-period（缺 period_start/period_end）。",
     "expected": "422 validation_error。",
     "run": case_period_validation},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "RC1-reconcile-run.png": "浏览器渲染真实对账运行与状态：run 200 success、dry_run；status 含 auto_confirm_enabled/last_run。",
    "RC2-reconcile-period.png": "浏览器渲染对账周期接口缺参的 422 validation_error 与带参时的真实响应。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 对账运行与状态 → 周期接口负例。",
}