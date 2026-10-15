"""ops-self-heal（自治运维与只增审计）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/ops_autonomy_admin_routes.py
（/api/xcmax/admin/autonomy/overview、/operating-metrics、/audit-log）、
FHD/app/fastapi_routes/ops_autonomy_routes.py（/api/ops/autonomy/actions/pending，机器 webhook 令牌门禁）。
管理端 UI：/admin/autonomy-approval-hub（自治审批中心）、
/admin/founder-autonomy（创始人自治驾驶舱）、/admin/xcmax-admin（服务器后台总览）、
/admin/server-functions（服务器功能模块）。
"""

import html as _html
import json as _json

FEATURE = "ops-self-heal"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取自治运维总览（/api/xcmax/admin/autonomy/overview：审批服务健康、待办与审计）→ "
    "读取运行指标（/api/xcmax/admin/autonomy/operating-metrics：30/90 天 veto 率窗口）→ "
    "读取只增审计账本（/api/xcmax/admin/autonomy/audit-log：风险级别与决策）→ "
    "操作端点缺机器令牌被拒（401）→ 无会话访问总览被拒（401）。"
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


def case_overview(page, env):
    text = _render(page, env, "/admin/autonomy-approval-hub",
                   name="S1-overview.png", wait_for="自治审批中心")
    r = _api(page, "/api/xcmax/admin/autonomy/overview")
    d = r.get("body") or {}
    health = d.get("health") or {}
    pending = d.get("pending") or {}
    audit = d.get("audit") or {}
    ok = (r["status"] == 200 and d.get("ok") is True and health.get("ok") is True
          and isinstance(pending.get("count"), int)
          and isinstance(pending.get("items"), list) and isinstance(audit.get("items"), list))
    return {"status": r["status"], "ok": d.get("ok"), "health": health,
            "pending_count": pending.get("count"), "audit_items": len(audit.get("items") or []),
            "ui_has_approval_hub": "产品问题工单审批" in text,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_operating_metrics(page, env):
    text = _render(page, env, "/admin/founder-autonomy",
                   name="S2-operating-metrics.png", wait_for="创始人自治驾驶舱")
    r = _api(page, "/api/xcmax/admin/autonomy/operating-metrics")
    d = r.get("body") or {}
    windows = d.get("windows") or {}
    ok = (r["status"] == 200 and d.get("ok") is True
          and {"30", "90"} <= set(windows.keys())
          and all("veto_rate" in w and "action_count" in w for w in windows.values()))
    return {"status": r["status"], "ok": d.get("ok"),
            "window_keys": sorted(windows.keys()), "w30": windows.get("30"),
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_audit_log(page, env):
    text = _render(page, env, "/admin/xcmax-admin",
                   name="S3-audit-log.png", wait_for="服务器后台总览")
    r = _api(page, "/api/xcmax/admin/autonomy/audit-log")
    d = r.get("body") or {}
    items = d.get("items") or []
    ok = (r["status"] == 200 and d.get("success") is True and d.get("append_only") is True
          and all("risk_level" in it and "decision" in it for it in items))
    return {"status": r["status"], "success": d.get("success"),
            "append_only": d.get("append_only"), "item_count": len(items),
            "items_sample": items[:2],
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_machine_token_denied(page, env):
    text = _render(page, env, "/admin/server-functions",
                   name="S4-machine-token.png", wait_for="服务器功能模块")
    r = _api(page, "/api/ops/autonomy/actions/pending")
    b = r.get("body") or {}
    msg = b.get("message") if isinstance(b, dict) else str(b)
    ok = r["status"] == 401 and "invalid autonomy webhook token" in str(msg)
    return {"status": r["status"], "message": msg,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_unauth_overview_denied(page, env):
    r = _unauth(page, env, "/api/xcmax/admin/autonomy/overview",
                name="S5-unauth-denied.png")
    b = r.get("body") or {}
    ok = r["status"] in (401, 403) and isinstance(b, dict) and b.get("success") is False
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "S1", "title": "自治运维总览（健康+待办+审计）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/autonomy-approval-hub，随后 fetch GET /api/xcmax/admin/autonomy/overview。",
     "expected": "HTTP 200、ok=true，health.ok=true，pending 含整数 count 与 items，audit 含 items。",
     "run": case_overview},
    {"id": "S2", "title": "自治运行指标（veto 率窗口）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/founder-autonomy，随后 fetch GET /api/xcmax/admin/autonomy/operating-metrics。",
     "expected": "HTTP 200、ok=true，windows 含 30/90 窗口且各含 veto_rate 与 action_count。",
     "run": case_operating_metrics},
    {"id": "S3", "title": "只增自治审计账本真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/xcmax-admin，随后 fetch GET /api/xcmax/admin/autonomy/audit-log。",
     "expected": "HTTP 200、success=true、append_only=true，每条含 risk_level 与 decision。",
     "run": case_audit_log},
    {"id": "S4", "title": "操作端点缺机器令牌被拒（负例）",
     "input": "已建立的管理员会话（无 CI/CVM 机器 webhook 令牌）。",
     "actions": "浏览器打开 /admin/server-functions，随后 fetch GET /api/ops/autonomy/actions/pending。",
     "expected": "HTTP 401，提示 invalid autonomy webhook token，不返回待办。",
     "run": case_machine_token_denied},
    {"id": "S5", "title": "无会话访问自治总览被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 的上下文中 fetch GET /api/xcmax/admin/autonomy/overview。",
     "expected": "被拒绝（401/403），success=false，不返回自治数据。",
     "run": case_unauth_overview_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "S1-overview.png": "「自治审批中心」页真实渲染：产品问题工单审批、共享 Work Order 与完整闸门时间线、每 30 秒刷新。",
    "S2-operating-metrics.png": "「创始人自治驾驶舱」页真实渲染：FOUNDER MODE · STRATEGIC ONLY，说明只保留战略方向/少量例外/veto。",
    "S3-audit-log.png": "「服务器后台总览」页真实渲染：本地节点「异常」、本地地址 127.0.0.1:42423、自治健康「不可达」、模块注册表异步显示 0 个模块。",
    "S4-machine-token.png": "「服务器功能模块」页真实渲染：服务器功能注册表 90 个模块。",
    "S5-unauth-denied.png": "无会话的新浏览器上下文停留在管理员登录页，未出现任何自治数据。",
    "__video__": "本轮真实浏览器会话录像（webm，38.72s，1600x1000 25fps，ffmpeg 实测）：管理员登录 → 自治审批中心 → 创始人状态 → 总览 → 服务器功能模块 → 无会话被拒，并 fetch 复核自治总览/运行指标/审计账本与 401。",
}