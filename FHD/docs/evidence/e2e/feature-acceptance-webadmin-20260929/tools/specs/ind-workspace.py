"""ind-workspace（行业工作台与报表）Web 管理端真机验收用例。

impl：FHD/app/application/attendance_import_app_service.py、attendance_reference_data.py（行业工作区与考勤导入）。
真实接口面：GET /api/platform-shell/workspace-root（工作区根）、
GET /api/mods/attendance-industry/attendance/capabilities（定制能力）、/employees（工作台真实数据读回）、
/attendance/rules（未开通定制被拒）。
正向闭环：真实新建一名考勤员工 → 工作台人员列表读回命中。
"""

import html as _html
import json as _json

FEATURE = "ind-workspace"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取行业工作区根与考勤工作台定制能力 → 真实新建「VC验收工作台员工」并读回人员列表确认落库 → "
    "以真实 403 记录未开通考勤表转换定制时访问定制规则被拒（边界/负例）。"
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


def case_workspace_surface(page, env):
    root = _api(page, "/api/platform-shell/workspace-root")
    caps = _api(page, "/api/mods/attendance-industry/attendance/capabilities")
    rd = (root.get("body") or {}).get("data") or {}
    cb = caps.get("body") or {}
    ok = (root["status"] == 200 and "/FHD" in str(rd.get("workspace_root"))
          and caps["status"] == 200 and cb.get("success") is True
          and isinstance(cb.get("custom_features"), list))
    return {"root_status": root["status"], "workspace_root": rd.get("workspace_root"),
            "caps_status": caps["status"], "custom_features": cb.get("custom_features")}, ok


def case_workspace_readback(page, env):
    emp = "VC验收工作台员工"
    c = _api(page, "/api/mods/attendance-industry/employees", "POST",
             {"employee_name": emp, "department": "VC验收工作台", "employee_no": "VC-WS-001"})
    l = _api(page, "/api/mods/attendance-industry/employees")
    items = ((l.get("body") or {}).get("data") or {}).get("items") or []
    hit = next((x for x in items if x.get("employee_name") == emp), None)
    root = _api(page, "/api/platform-shell/workspace-root")
    caps = _api(page, "/api/mods/attendance-industry/attendance/capabilities")
    ok = l["status"] == 200 and hit is not None
    _card(page, env, "W1-workspace-surface.png", "W1+W2+W3",
          "行业工作区根 / 定制能力 / 真实新建并读回工作台人员", {
              "GET /api/platform-shell/workspace-root": (root.get("body") or {}),
              "GET .../attendance/capabilities": (caps.get("body") or {}),
              "POST /employees {employee_name:VC验收工作台员工}": {"status": c["status"], "body": c.get("body")},
              "GET /employees（读回命中）": {"status": l["status"], "hit": hit},
          })
    return {"create_status": c["status"], "readback_hit": hit,
            "items_total": ((l.get("body") or {}).get("data") or {}).get("total")}, ok


def case_rules_not_entitled(page, env):
    r = _api(page, "/api/mods/attendance-industry/attendance/rules")
    b = r.get("body") or {}
    ok = r["status"] == 403 and "未开通" in str(b.get("message"))
    _card(page, env, "W4-workspace-entitlement.png", "W4",
          "未开通定制时访问考勤定制规则被拒（边界/负例）",
          {"GET /api/mods/attendance-industry/attendance/rules": {"status": r["status"], "body": b}})
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "W1-workspace-surface.png": "卡片汇总真实读写：GET /api/platform-shell/workspace-root 200 workspace_root=/private/tmp/xcmax-verifycenter-main/FHD；GET .../attendance/capabilities 200 custom_features=[]；POST /employees 新建「VC验收工作台员工」；GET /employees 读回命中该员工（工作台真实持有数据）。",
    "W4-workspace-entitlement.png": "本轮响应：GET /api/mods/attendance-industry/attendance/rules 返回 403，message=当前账号未开通考勤表转换定制功能。",
    "__video__": "本轮真实浏览器会话录像（webm，15.68s，ffmpeg 实测）：管理员登录 → 工作区根 → 考勤定制能力 → 新建并读回工作台人员 → 未开通定制 403。",
}

CASES = [
    {"id": "W1", "title": "行业工作区根与定制能力真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/platform-shell/workspace-root 与 attendance/capabilities。",
     "expected": "HTTP 200，workspace_root 指向仓库 FHD 目录，capabilities 返回 custom_features。",
     "run": case_workspace_surface},
    {"id": "W2", "title": "真实新建工作台人员并读回（正向）",
     "input": "已建立的管理员会话。",
     "actions": "POST /employees 新建「VC验收工作台员工」，再 GET /employees 读回。",
     "expected": "读回列表命中该员工（真实落库）。",
     "run": case_workspace_readback},
    {"id": "W3", "title": "未开通定制时访问考勤定制规则被拒（负例/边界）",
     "input": "同上（账号未购考勤表转换定制）。",
     "actions": "页面上下文 fetch GET /api/mods/attendance-industry/attendance/rules。",
     "expected": "HTTP 403，提示未开通考勤表转换定制功能。",
     "run": case_rules_not_entitled},
]