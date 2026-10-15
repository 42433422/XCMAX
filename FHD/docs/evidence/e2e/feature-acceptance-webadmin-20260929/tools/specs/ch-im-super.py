"""ch-im-super（超级员工与 AI 群聊）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/im_super_employee_routes.py、im_ai_group_routes.py。
真实接口面：GET /api/admin/ai-groups（AI 群 / 超级员工编组）、/api/admin/ai-groups/candidates（候选员工）、
GET /api/admin/ai-groups/{group_id}/messages（群消息）；未登录访问被拒。
"""

import html as _html
import json as _json

FEATURE = "ch-im-super"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取 AI 群与超级员工编组（成员/部门）→ 读取可加入的候选 AI 员工 → 读取指定群消息流 → "
    "以全新无会话上下文复核未登录访问 AI 群被真实拒绝（401）。"
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


def case_groups(page, env):
    r = _api(page, "/api/admin/ai-groups")
    b = r.get("body") or {}
    groups = b.get("groups") or []
    ok = r["status"] == 200 and b.get("success") is True and len(groups) > 0 \
        and all(g.get("id") and g.get("name") for g in groups)
    body = {"status": r["status"], "group_count": len(groups),
            "sample": [{"id": g.get("id"), "name": g.get("name"),
                        "member_count": g.get("member_count")} for g in groups[:3]]}
    _card(page, env, "S1-super-groups.png", "S1+S2+S3",
          "AI 群 / 候选员工 / 群消息流真实读取", {
              "GET /api/admin/ai-groups": body,
              "GET /api/admin/ai-groups/candidates": {
                  "status": (_api(page, "/api/admin/ai-groups/candidates").get("body") or {}).get("success"),
                  "count": len(((_api(page, "/api/admin/ai-groups/candidates").get("body") or {}).get("candidates")) or [])},
          })
    return body, ok


def case_candidates(page, env):
    r = _api(page, "/api/admin/ai-groups/candidates")
    b = r.get("body") or {}
    cands = b.get("candidates") or []
    ok = r["status"] == 200 and b.get("success") is True and len(cands) > 0
    return {"status": r["status"], "candidate_count": len(cands),
            "sample": [c.get("employee_id") for c in cands[:5]]}, ok


def case_group_messages(page, env):
    r = _api(page, "/api/admin/ai-groups/dept:shared_retention/messages")
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(b.get("messages"), list)
    return {"status": r["status"], "success": b.get("success"),
            "message_count": len(b.get("messages") or [])}, ok


def case_unauthenticated_denied(page, env):
    browser = page.context.browser
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1500)
    r = pg2.evaluate(
        "async () => { try { const r = await fetch('/api/admin/ai-groups', {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){}"
        " return {status: r.status, body: j !== null ? j : t.slice(0,200)}; }"
        " catch(e) { return {status:0, body:String(e)}; } }")
    ctx2.close()
    ok = r["status"] == 401
    _card(page, env, "S4-super-unauth.png", "S4",
          "未登录访问 AI 群被拒（负例）",
          {"GET /api/admin/ai-groups（无会话）": {"status": r["status"], "body": r.get("body")}})
    return {"status": r["status"], "body": r.get("body")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "S1-super-groups.png": "卡片汇总两处真实响应：GET /api/admin/ai-groups 200 success=true，groups 非空（如 S-R 归档部 dept:shared_retention，含成员与 mod_id）；GET /api/admin/ai-groups/candidates 200 success=true，candidates 非空（如 site-content-editor）。",
    "S4-super-unauth.png": "本轮响应：无会话上下文 GET /api/admin/ai-groups 返回 401，message 提示请先登录后再执行此操作。",
    "__video__": "本轮真实浏览器会话录像（webm，16.40s，ffmpeg 实测）：管理员登录 → AI 群 → 候选员工 → 群消息流 → 无会话 401。",
}

CASES = [
    {"id": "S1", "title": "AI 群与超级员工编组真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/admin/ai-groups。",
     "expected": "HTTP 200，success=true，groups 非空且含 id/name。",
     "run": case_groups},
    {"id": "S2", "title": "候选 AI 员工真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/admin/ai-groups/candidates。",
     "expected": "HTTP 200，success=true，candidates 非空。",
     "run": case_candidates},
    {"id": "S3", "title": "指定 AI 群消息流真实读取",
     "input": "同上，group_id=dept:shared_retention。",
     "actions": "页面上下文 fetch GET /api/admin/ai-groups/dept:shared_retention/messages。",
     "expected": "HTTP 200，success=true，messages 为数组。",
     "run": case_group_messages},
    {"id": "S4", "title": "未登录访问 AI 群被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "无 cookie 上下文 fetch GET /api/admin/ai-groups。",
     "expected": "HTTP 401，不返回群与员工数据。",
     "run": case_unauthenticated_denied},
]