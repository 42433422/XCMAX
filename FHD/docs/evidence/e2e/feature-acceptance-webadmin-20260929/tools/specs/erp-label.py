"""erp-label（标签打印）Web 管理端真机验收用例。

被测对象：web 模式自托管管理端的标签打印面。
impl：FHD/app/fastapi_routes/print_routes.py、label_jobs.py；业务出口 /api/business/print/label；
      工作流员工 /api/mod/xcagi-core-workflow-employees/employees/label_print/*。
真实验证面：标签打印员工状态读取 → 真实发布打印作业事件 → 旧打印接口 403 fail-closed（负例）。
所有请求均在真实浏览器页面上下文发起。
"""

import time

FEATURE = "erp-label"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在 Web 管理端读回标签打印员工状态（label_print/status）→ POST /api/business/print/label "
    "真实发布打印作业事件（print.job.submitted）→ 对旧 /api/print/templates 与 /api/print/label 发起请求并记录 "
    "403 fail-closed（负例）。"
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


def case_employee_status(page, env):
    r = _api(page, "/api/mod/xcagi-core-workflow-employees/employees/label_print/status")
    d = (r.get("body") or {}).get("data") or {}
    _panel(page, env, "LB1-label-employee.png",
           "GET .../employees/label_print/status · 标签打印员工状态",
           {"status": r["status"], "ok": d.get("ok"), "summary": d.get("summary"), "meta": d.get("meta")})
    ok = r["status"] == 200 and d.get("ok") is True
    return {"status": r["status"], "ok": d.get("ok"), "summary": d.get("summary")}, ok


def case_print_job_event(page, env):
    ts = time.strftime("%H%M%S")
    r = _api(page, "/api/business/print/label", method="POST",
             body={"job_id": f"vc-{ts}", "document_name": "验收标签", "copies": 1})
    b = r.get("body") or {}
    _panel(page, env, "LB2-label-print-event.png",
           "POST /api/business/print/label · 真实发布打印作业事件",
           {"status": r["status"], "success": b.get("success"), "job_id": b.get("job_id"),
            "event": b.get("event"), "run_id": b.get("run_id")})
    ok = (r["status"] == 200 and b.get("success") is True
          and b.get("event") == "print.job.submitted" and bool(b.get("run_id")))
    return {"status": r["status"], "success": b.get("success"), "event": b.get("event"),
            "run_id": b.get("run_id")}, ok


def case_legacy_denied(page, env):
    tpl = _api(page, "/api/print/templates")
    label = _api(page, "/api/print/label", method="POST", body={"product_id": 1, "quantity": 1})
    printers = _api(page, "/api/print/printers")
    tb, lb, pb = tpl.get("body") or {}, label.get("body") or {}, printers.get("body") or {}
    _panel(page, env, "LB3-label-legacy-denied.png",
           "旧打印接口 403 fail-closed（负例）",
           {"print_templates": {"status": tpl["status"], "error_code": tb.get("error_code")},
            "print_label": {"status": label["status"], "error_code": lb.get("error_code")},
            "print_printers": {"status": printers["status"], "error_code": pb.get("error_code")}})
    ok = tpl["status"] == 403 and label["status"] == 403 and printers["status"] == 403
    return {"print_templates": {"status": tpl["status"]}, "print_label": {"status": label["status"]},
            "print_printers": {"status": printers["status"]}}, ok


CASES = [
    {"id": "LB1", "title": "标签打印员工状态真实读取",
     "input": "已建立的管理员会话。",
     "actions": "GET /api/mod/xcagi-core-workflow-employees/employees/label_print/status。",
     "expected": "200 且 ok=true。",
     "run": case_employee_status},
    {"id": "LB2", "title": "真实发布打印作业事件",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "POST /api/business/print/label。",
     "expected": "200、success=true、event=print.job.submitted、含 run_id。",
     "run": case_print_job_event},
    {"id": "LB3", "title": "旧打印接口 403 fail-closed（负例）",
     "input": "已建立的管理员会话（带 CSRF 令牌）。",
     "actions": "GET /api/print/templates、POST /api/print/label、GET /api/print/printers。",
     "expected": "三者均 403，不返回未隔离打印数据。",
     "run": case_legacy_denied},
]

VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "LB1-label-employee.png": "浏览器渲染标签打印员工 status 真实 JSON（ok、summary、meta）。",
    "LB2-label-print-event.png": "浏览器渲染打印作业事件发布真实响应：200、job_id、event=print.job.submitted、run_id。",
    "LB3-label-legacy-denied.png": "浏览器渲染旧打印接口 /api/print/templates、/label、/printers 的 403 fail-closed。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 标签员工状态 → 打印事件发布 → 旧接口负例。",
}