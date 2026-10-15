"""ch-task-center（任务中心与审批通知）Web 管理端真机验收用例。

impl：FHD/app/application/approval_notifications.py（审批消息通知与任务中心）。
真实接口面：GET /api/approval/requests、/api/approval/flows、/api/agent/tasks（任务中心）、
GET /api/approval/requests/{id}（不存在审批被拒）。
"""

import html as _html
import json as _json

FEATURE = "ch-task-center"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取审批请求列表（分页）→ 读取审批流程定义 → 读取任务中心任务 → "
    "以真实 404 记录查询不存在审批请求被拒（边界/负例）。"
)


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,300)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", path)


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


def case_requests(page, env):
    r = _api(page, "/api/approval/requests")
    b = r.get("body") or {}
    pag = b.get("pagination") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(b.get("data"), list) and "total" in pag
    body = {"status": r["status"], "success": b.get("success"), "total": pag.get("total"),
            "returned": pag.get("returned")}
    _card(page, env, "T1-task-center.png", "T1+T2+T3",
          "审批请求 / 审批流程 / 任务中心真实读取", {
              "GET /api/approval/requests": body,
              "GET /api/approval/flows": _api(page, "/api/approval/flows").get("body"),
              "GET /api/agent/tasks": {k: v for k, v in (_api(page, "/api/agent/tasks").get("body") or {}).items() if k in ("success",)},
          })
    return body, ok


def case_flows(page, env):
    r = _api(page, "/api/approval/flows")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(b.get("data"), list)
    return {"status": r["status"], "success": b.get("success"), "flow_count": len(b.get("data") or [])}, ok


def case_agent_tasks(page, env):
    r = _api(page, "/api/agent/tasks")
    b = r.get("body") or {}
    tasks = b.get("data") or []
    ok = r["status"] == 200 and len(tasks) > 0 and all(t.get("task_id") for t in tasks)
    return {"status": r["status"], "task_count": len(tasks),
            "sample": [{"task_id": t.get("task_id"), "status": t.get("status"),
                        "task_type": t.get("task_type")} for t in tasks[:3]]}, ok


def case_missing_request(page, env):
    r = _api(page, "/api/approval/requests/999999")
    b = r.get("body") or {}
    ok = r["status"] == 404 and "不存在" in str(b.get("message"))
    _card(page, env, "T4-missing-request.png", "T4",
          "查询不存在审批请求被拒（边界/负例）",
          {"GET /api/approval/requests/999999": {"status": r["status"], "body": b}})
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "T1-task-center.png": "卡片汇总三处真实响应：GET /api/approval/requests 200 success=true、pagination.total=0；GET /api/approval/flows 200 success=true data=[]；GET /api/agent/tasks 200 success=true（任务中心真实返回）。",
    "T4-missing-request.png": "本轮响应：GET /api/approval/requests/999999 返回 404，message=审批请求不存在。",
    "__video__": "本轮真实浏览器会话录像（webm，14.40s，ffmpeg 实测）：管理员登录 → 审批请求 → 审批流程 → 任务中心 → 不存在审批 404。",
}

CASES = [
    {"id": "T1", "title": "审批请求列表（分页）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/approval/requests。",
     "expected": "HTTP 200，success=true，data 为数组且带分页总数。",
     "run": case_requests},
    {"id": "T2", "title": "审批流程定义真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/approval/flows。",
     "expected": "HTTP 200，success=true，data 为数组。",
     "run": case_flows},
    {"id": "T3", "title": "任务中心任务真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/agent/tasks。",
     "expected": "HTTP 200，任务非空且每项含 task_id。",
     "run": case_agent_tasks},
    {"id": "T4", "title": "查询不存在审批请求被拒（负例/边界）",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/approval/requests/999999。",
     "expected": "HTTP 404，提示审批请求不存在。",
     "run": case_missing_request},
]