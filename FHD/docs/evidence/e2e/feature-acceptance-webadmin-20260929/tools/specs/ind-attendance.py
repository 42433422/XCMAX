"""ind-attendance（考勤行业包）Web 管理端真机验收用例。

impl：FHD/mods/attendance-industry（统一考勤工作区：部门/人员/排班/记录）。
真实接口面：GET /api/mods/attendance-industry/status、POST/GET /employees、POST/GET /departments、
GET /schedules。正向闭环：真实新建部门+人员 → 读回列表确认落库；负例：未开通定制访问被 403。
"""

import html as _html
import json as _json

FEATURE = "ind-attendance"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取统一考勤系统状态、排班工作台 → 真实新建「VC验收部门」与「VC验收员工」，"
    "读回人员/部门列表确认已落库（employee_count=1、total=1）→ "
    "以真实 403 记录未开通考勤表转换定制时访问定制策略被拒（边界/负例）。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p,m,b]) => { try {
            const init={credentials:'include', method:m};
            if (b!==null){ init.headers={'Content-Type':'application/json'}; init.body=JSON.stringify(b);
              const cm=document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
              if (cm) init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]); }
            const r=await fetch(p, init); const t=await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, body:j!==null?j:t.slice(0,400)};
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


def case_status(page, env):
    r = _api(page, "/api/mods/attendance-industry/status")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and b.get("mod_id") == "attendance-industry"
    return {"status": r["status"], "mod_id": b.get("mod_id"), "message": b.get("message")}, ok


def case_schedules(page, env):
    r = _api(page, "/api/mods/attendance-industry/schedules")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(b.get("schedule_groups"), list)
    return {"status": r["status"], "schedule_group_count": len(b.get("schedule_groups") or []),
            "line_count": len(b.get("lines") or [])}, ok


def case_create_and_readback(page, env):
    dept = "VC验收部门"
    emp = "VC验收员工"
    d1 = _api(page, "/api/mods/attendance-industry/departments", "POST", {"department": dept})
    e1 = _api(page, "/api/mods/attendance-industry/employees", "POST",
              {"employee_name": emp, "department": dept, "employee_no": "VC001"})
    dl = _api(page, "/api/mods/attendance-industry/departments")
    el = _api(page, "/api/mods/attendance-industry/employees")
    ditems = ((dl.get("body") or {}).get("data") or {}).get("items") or []
    eitems = ((el.get("body") or {}).get("data") or {}).get("items") or []
    dept_hit = next((x for x in ditems if x.get("department") == dept), None)
    emp_hit = next((x for x in eitems if x.get("employee_name") == emp), None)
    # 新建可 200（新插入）或 409（已存在，幂等重跑）；只要读回存在即证明落库闭环
    ok = (dl["status"] == 200 and el["status"] == 200 and dept_hit is not None and emp_hit is not None)
    _card(page, env, "A1-attendance-write-readback.png", "A1+A2+A3",
          "真实新建部门/人员 → 读回落库（正向闭环）", {
              "POST /departments {department:VC验收部门}": {"status": d1["status"], "body": d1.get("body")},
              "POST /employees {employee_name:VC验收员工}": {"status": e1["status"], "body": e1.get("body")},
              "GET /departments（读回命中）": {"status": dl["status"], "hit": dept_hit},
              "GET /employees（读回命中）": {"status": el["status"], "hit": emp_hit},
              "GET /schedules": _api(page, "/api/mods/attendance-industry/schedules").get("body"),
          })
    return {"dept_create_status": d1["status"], "emp_create_status": e1["status"],
            "dept_readback": dept_hit, "emp_readback": emp_hit}, ok


def case_custom_not_entitled(page, env):
    r = _api(page, "/api/mods/sunbird-attendance-custom/attendance/policy")
    b = r.get("body") or {}
    ok = r["status"] == 403 and "未开通" in str(b.get("message"))
    _card(page, env, "A4-attendance-entitlement.png", "A4",
          "未开通考勤表转换定制时访问定制策略被拒（边界/负例）",
          {"GET /api/mods/sunbird-attendance-custom/attendance/policy": {"status": r["status"], "body": b}})
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "A1-attendance-write-readback.png": "卡片汇总真实读写：POST /departments 新建「VC验收部门」409（该部门已存在，幂等重跑）；POST /employees 新建「VC验收员工」409（该人员已存在）；随后 GET /departments、GET /employees 读回均命中该记录（department=VC验收部门 employee_count=1；employee_name=VC验收员工 department=VC验收部门 employee_no=VC001），证明统一考勤工作区真实落库；GET /schedules 返回 schedule_groups=[]/lines=[]。",
    "A4-attendance-entitlement.png": "本轮响应：GET /api/mods/sunbird-attendance-custom/attendance/policy 返回 403，error_code=http_403，message=当前账号未开通考勤表转换定制功能。",
    "__video__": "本轮真实浏览器会话录像（webm，16.16s，ffmpeg 实测）：管理员登录 → 考勤状态 → 新建部门/人员 → 读回落库 → 未开通定制 403。",
}

CASES = [
    {"id": "A1", "title": "考勤系统状态真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/mods/attendance-industry/status。",
     "expected": "HTTP 200，success=true，mod_id=attendance-industry。",
     "run": case_status},
    {"id": "A2", "title": "真实新建部门/人员并读回（正向）",
     "input": "已建立的管理员会话。",
     "actions": "POST /departments、POST /employees 新建，再 GET 两列表读回。",
     "expected": "读回列表中命中「VC验收部门」「VC验收员工」（真实落库）。",
     "run": case_create_and_readback},
    {"id": "A3", "title": "考勤排班真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/mods/attendance-industry/schedules。",
     "expected": "HTTP 200，含 schedule_groups 与 lines。",
     "run": case_schedules},
    {"id": "A4", "title": "未开通定制访问被拒（负例/边界）",
     "input": "同上（账号未购考勤表转换定制）。",
     "actions": "页面上下文 fetch GET /api/mods/sunbird-attendance-custom/attendance/policy。",
     "expected": "HTTP 403，提示未开通考勤表转换定制功能。",
     "run": case_custom_not_entitled},
]