"""ops-work-order（共享工单与自治审批）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/ops_autonomy_routes.py
（/api/ops/autonomy/work-orders、/api/ops/autonomy/work-orders/{wo_id}/owner-decision）。
管理端 UI：/admin/autonomy-approval-hub（自治审批中心，产品问题工单审批）、
/admin/delivery-center（客户交付中心）、/admin/server-functions（服务器功能模块）。
"""

import html as _html
import json as _json

FEATURE = "ops-work-order"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取共享工单列表（/api/ops/autonomy/work-orders）→ "
    "非法 limit 参数被参数校验拒绝（422）→ "
    "非 Owner 提交 owner-decision 被越权拒绝（403）→ "
    "无会话访问工单列表被拒（401）；并在自治审批中心页真实渲染工单审批面。"
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


def case_work_orders(page, env):
    text = _render(page, env, "/admin/autonomy-approval-hub",
                   name="W1-work-orders.png", wait_for="自治审批中心")
    r = _api(page, "/api/ops/autonomy/work-orders")
    d = r.get("body") or {}
    items = d.get("items") or []
    ok = (r["status"] == 200 and d.get("ok") is True
          and isinstance(d.get("count"), int) and isinstance(items, list))
    return {"status": r["status"], "ok": d.get("ok"), "count": d.get("count"),
            "items_sample": items[:3],
            "ui_has_approval_hub": "产品问题工单审批" in text,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_invalid_limit_denied(page, env):
    text = _render(page, env, "/admin/delivery-center",
                   name="W2-invalid-limit.png", wait_for="客户交付中心")
    r = _api(page, "/api/ops/autonomy/work-orders?limit=abc")
    d = r.get("body") or {}
    fields = [e.get("field") for e in (d.get("errors") or [])]
    ok = (r["status"] == 422 and d.get("error_code") == "validation_error"
          and "query.limit" in fields)
    return {"status": r["status"], "error_code": d.get("error_code"),
            "message": d.get("message"), "errors": d.get("errors"),
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_non_owner_denied(page, env):
    text = _render(page, env, "/admin/server-functions",
                   name="W3-non-owner.png", wait_for="服务器功能模块")
    r = _api(page, "/api/ops/autonomy/work-orders/wo-acceptance-probe/owner-decision",
             "POST", {"decision": "approve"})
    b = r.get("body") or {}
    ok = r["status"] == 403 and "仅 Owner 本人可执行工单决策" in str(b.get("message"))
    return {"status": r["status"], "message": b.get("message"), "body": b,
            "ui_head": text.replace("\n", " ")[:240]}, ok


def case_unauth_work_orders_denied(page, env):
    r = _unauth(page, env, "/api/ops/autonomy/work-orders",
                name="W4-unauth-denied.png")
    b = r.get("body") or {}
    ok = r["status"] in (401, 403) and isinstance(b, dict) and b.get("success") is False
    return {"status": r["status"], "body": b}, ok


CASES = [
    {"id": "W1", "title": "共享工单列表真实读取",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/autonomy-approval-hub，随后 fetch GET /api/ops/autonomy/work-orders。",
     "expected": "HTTP 200、ok=true，返回 items 列表与整数 count。",
     "run": case_work_orders},
    {"id": "W2", "title": "非法 limit 参数被参数校验拒绝（负例）",
     "input": "已建立的管理员会话。",
     "actions": "浏览器打开 /admin/delivery-center，随后 fetch GET /api/ops/autonomy/work-orders?limit=abc。",
     "expected": "HTTP 422、error_code=validation_error，指明 query.limit 解析失败。",
     "run": case_invalid_limit_denied},
    {"id": "W3", "title": "非 Owner 提交工单决策被越权拒绝（负例）",
     "input": "已建立的管理员会话（当前管理员非 Owner 本人）。",
     "actions": "浏览器打开 /admin/server-functions，随后 POST /api/ops/autonomy/work-orders/{wo_id}/owner-decision。",
     "expected": "HTTP 403，提示仅 Owner 本人可执行工单决策。",
     "run": case_non_owner_denied},
    {"id": "W4", "title": "无会话访问工单列表被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 的上下文中 fetch GET /api/ops/autonomy/work-orders。",
     "expected": "被拒绝（401/403），success=false，不返回工单数据。",
     "run": case_unauth_work_orders_denied},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "W1-work-orders.png": "「自治审批中心」页真实渲染：标题「产品问题工单审批」，副标题「共享 Work Order 与完整闸门时间线；每 30 秒刷新」，含刷新工单按钮，显示「当前没有共享工单」。",
    "W2-invalid-limit.png": "「客户交付中心」页真实渲染：Mac 主控·四设备协同，企业用户/永久购买账户/体验账户/永久待安装/定制交付工单等计数卡片（均为 0）。",
    "W3-non-owner.png": "「服务器功能模块」页真实渲染：服务器功能注册表 90 个模块列表。",
    "W4-unauth-denied.png": "无会话的新浏览器上下文停留在管理员登录页，未出现任何工单数据。",
    "__video__": "本轮真实浏览器会话录像（webm，30.16s，1600x1000 25fps，ffmpeg 实测）：管理员登录 → 自治审批中心 → 客户交付中心 → 服务器功能模块 → 无会话被拒，并 fetch/POST 复核工单列表与 422/403/401。",
}