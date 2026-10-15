"""ops-employee-gov（创始人自治 · 员工治理）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/xcmax_ops.py（/api/xcmax/ops/founder-autonomy）、
FHD/app/fastapi_routes/admin_ai_groups.py（/api/admin/ai-groups）、
FHD/app/fastapi_routes/local_duty_graph.py（/api/xcmax/local/duty-graph/health）。
管理端 UI：/admin/founder-autonomy（创始人自治驾驶舱）、
/admin/employee-autonomy（员工自治）、/admin/duty-roster-graph（员工图谱）。
"""

import html as _html
import json as _json

FEATURE = "ops-employee-gov"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，真实鼠标键盘）在自托管 Web 管理端建立管理员会话后："
    "读取创始人自治七维快照（/api/xcmax/ops/founder-autonomy）→ "
    "读取企业员工分组与成员数（/api/admin/ai-groups）→ "
    "读取本地编制在岗健康（/api/xcmax/local/duty-graph/health）；"
    "并在创始人状态、员工自治、员工图谱页真实渲染；无会话访问自治快照被拒。"
)


def _api(page, path, method="GET", body=None, csrf=True):
    return page.evaluate(
        """async ([p, m, b, useCsrf]) => {
            try {
                const init = {method: m, credentials: 'include', headers: {}};
                if (b !== null && b !== undefined) {
                    init.headers['Content-Type'] = 'application/json';
                    init.body = JSON.stringify(b);
                }
                if (useCsrf && m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);
                    if (cm) init.headers['X-CSRF-Token'] = decodeURIComponent(cm[1]);
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch (e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0, 400)};
            } catch (e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body, csrf],
    )


def _render(page, env, route, name=None, wait_for=None, tries=10):
    page.goto(env["base"] + route, wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(tries):
        page.wait_for_timeout(2000)
        text = page.inner_text("body") or ""
        if wait_for is None or wait_for in text:
            break
    if name:
        page.screenshot(path=str(env["shot"] / name))
    return text


def _unauth(page, env, path, method="GET", body=None, csrf=True, name=None):
    ctx = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg = ctx.new_page()
    pg.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg.wait_for_timeout(1200)
    r = _api(pg, path, method, body, csrf)
    if name:
        pg.screenshot(path=str(env["shot"] / name))
    ctx.close()
    return r


def case_founder_autonomy(page, env):
    text = _render(page, env, "/admin/founder-autonomy",
                   name="G1-founder-autonomy.png", wait_for="创始人自治驾驶舱")
    r = _api(page, "/api/xcmax/ops/founder-autonomy")
    d = r.get("body") or {}
    dims = d.get("dimensions") or {}
    dim_ids = sorted(dims.keys()) if isinstance(dims, dict) else []
    ok = (r["status"] == 200 and d.get("success") is True
          and d.get("schema_version") == "founder_autonomy_status.v1"
          and len(dim_ids) == 7
          and all("status" in (dims[k] or {}) for k in dim_ids))
    return {"status": r["status"], "success": d.get("success"),
            "schema_version": d.get("schema_version"),
            "target_state": d.get("target_state"),
            "overall_progress": d.get("overall_progress"),
            "dimension_ids": dim_ids,
            "ui_has_cockpit": "创始人自治驾驶舱" in text,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_ai_groups(page, env):
    text = _render(page, env, "/admin/employee-autonomy",
                   name="G2-employee-groups.png", wait_for="员工自治")
    r = _api(page, "/api/admin/ai-groups")
    d = r.get("body") or {}
    groups = d.get("groups") or []
    ok = (r["status"] == 200 and d.get("success") is True and len(groups) > 0
          and all(g.get("id") and int(g.get("member_count") or 0) > 0 for g in groups))
    sample = [{"id": g.get("id"), "name": g.get("name"),
               "member_count": g.get("member_count")} for g in groups[:4]]
    return {"status": r["status"], "success": d.get("success"),
            "group_count": len(groups), "groups_sample": sample,
            "ui_has_autonomy": "员工自治" in text,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_duty_graph_health(page, env):
    text = _render(page, env, "/admin/duty-roster-graph",
                   name="G3-duty-roster.png", wait_for="员工图谱")
    r = _api(page, "/api/xcmax/local/duty-graph/health")
    d = r.get("body") or {}
    ok = (r["status"] == 200 and d.get("success") is True
          and int(d.get("planned_count") or 0) > 0
          and int(d.get("registered_count") or 0) > 0)
    return {"status": r["status"], "success": d.get("success"),
            "source": d.get("source"), "planned_count": d.get("planned_count"),
            "registered_count": d.get("registered_count"),
            "missing_employees": d.get("missing_employees"),
            "ui_has_roster": "在岗员工节点图" in text,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_unauth_founder_denied(page, env):
    r = _unauth(page, env, "/api/xcmax/ops/founder-autonomy",
                name="G4-unauth-denied.png")
    b = r.get("body") or {}
    ok = r["status"] in (401, 403) and isinstance(b, dict) and b.get("success") is False
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "G1", "title": "创始人自治七维策略快照真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/founder-autonomy，随后 fetch GET /api/xcmax/ops/founder-autonomy。",
     "expected": "HTTP 200、success=true，schema=founder_autonomy_status.v1，七维 id 齐全且各维含 status。",
     "run": case_founder_autonomy},
    {"id": "G2", "title": "企业员工分组与成员数真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/employee-autonomy，随后 fetch GET /api/admin/ai-groups。",
     "expected": "HTTP 200、success=true，返回非空分组且每组含 id 与非零 member_count。",
     "run": case_ai_groups},
    {"id": "G3", "title": "本地编制在岗健康真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/duty-roster-graph，随后 fetch GET /api/xcmax/local/duty-graph/health。",
     "expected": "HTTP 200、success=true，planned_count 与 registered_count 均 > 0。",
     "run": case_duty_graph_health},
    {"id": "G4", "title": "无会话访问自治快照被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 的上下文中 fetch GET /api/xcmax/ops/founder-autonomy。",
     "expected": "被拒绝（401/403），success=false，不返回自治数据。",
     "run": case_unauth_founder_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "G1-founder-autonomy.png": "「创始人自治驾驶舱」页真实渲染：FOUNDER MODE · STRATEGIC ONLY，说明「日常运营交给 AI 员工与 Loops；这里只保留战略方向、少量例外与 veto」，并显示正在汇总审批/知识库/员工/Goals/Loop 账本。",
    "G2-employee-groups.png": "「员工自治」页真实渲染：子导航「自洽总览 / 建议看板 / 问答 / 成绩单」，系统运行态显示「降级」，含定时履职/能力证明/生产履职 0/0 卡片与「需人工审批岗位：没有待审批的高风险岗位」。",
    "G3-duty-roster.png": "「员工图谱」页真实渲染：顶部「在岗员工节点图 编制 55 岗」，含中心图/六部门/物理分区/客户端车间/自进化 Loop 视图切换，图区显示正在拉取在岗员工列表。",
    "G4-unauth-denied.png": "无会话的新浏览器上下文停留在管理员登录页，未出现任何自治数据。",
    "__video__": "本轮真实浏览器会话录像（webm，31.32s，1600x1000 25fps，ffmpeg 实测）：管理员登录 → 创始人状态 → 员工自治 → 员工图谱 → 无会话被拒，并 fetch 复核自治快照/员工分组/编制健康三个接口。",
}