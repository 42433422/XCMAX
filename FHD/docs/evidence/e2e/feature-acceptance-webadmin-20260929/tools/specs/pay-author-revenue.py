"""pay-author-revenue（作者收益与分成结算）Web 管理端真机验收用例。

impl 源码：FHD/app/services/catalog_client.py（→ app.infrastructure.mods.catalog_client：商品/作者与定价口径）
真实接口：GET /api/mod-store/catalog（已安装商品作者归属）、GET /api/ai/kitten/charts/revenue（营收口径）、
          GET /api/mod/ecosystem-revenue-share-reconciler/employees[/.../status]（生态分润对账员工）、
          GET /api/finance/payables（结算台账）、GET /api/xcmax/admin/market/wallets（被拒）。
"""

import html as _html
import json as _json

FEATURE = "pay-author-revenue"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → 「员工自治」页真实渲染 → "
    "已安装商品清单返回作者归属（author）→ 月度营收趋势口径真实读取 → "
    "「生态分润对账员」员工在册且状态 ready → 结算应付台账真实读取（空台账也不伪造）→ "
    "市场结算钱包视图在未绑定市场账号时被拒（401）。"
)


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,400)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", path)


def _card(page, env, name, cid, title, path, status, body):
    payload = _json.dumps(body, ensure_ascii=False, default=str)
    if len(payload) > 2600:
        payload = payload[:2600] + " …(截断)"
    page.set_content(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><style>"
        "body{margin:0;padding:22px;background:#0b1b2b;color:#e8f1fb;font:13px/1.7 -apple-system,'Segoe UI',sans-serif}"
        "h1{font-size:15px;margin:0 0 4px}.sub{color:#8fb3d9;font-size:12px;margin-bottom:14px}"
        ".card{background:#122b45;border:1px solid #21405f;border-radius:10px;padding:16px}"
        ".kv{padding:3px 0;border-bottom:1px dashed #21405f}.k{color:#8fb3d9;display:inline-block;width:120px}"
        "pre{background:#08131f;border-radius:8px;padding:12px;white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font-size:12px}"
        "</style></head><body>"
        f"<h1>{cid} · {_html.escape(title)}</h1>"
        "<div class='sub'>XCMAX 服务器后台 · 真实浏览器本轮 fetch 观测（内容为本轮真实响应，非构造）</div>"
        "<div class='card'>"
        f"<div class='kv'><span class='k'>请求</span>{_html.escape(path)}</div>"
        f"<div class='kv'><span class='k'>HTTP 状态</span>{status}</div>"
        f"<pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_employee_autonomy_ui(page, env):
    page.goto(env["base"] + "/admin/employee-autonomy", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)
    text = (page.inner_text("body") or "").replace("\n", " ")
    title = page.title() or ""
    ok = "员工自治" in text and "履职覆盖" in text and "成绩单" in text
    page.screenshot(path=str(env["shot"] / "PA1-employee-autonomy.png"))
    return {"final_url": page.url, "title": title, "text_head": text[:320]}, ok


def case_catalog_author(page, env):
    path = "/api/mod-store/catalog"
    r = _api(page, path)
    body = r.get("body") or {}
    installed = ((body.get("data") or {}).get("installed")) or []
    sample = [{"id": it.get("id"), "author": it.get("author"), "version": it.get("version")}
              for it in installed[:4]]
    ok = (r["status"] == 200 and body.get("success") is True and len(installed) > 0
          and all(str(it.get("author") or "").strip() for it in installed))
    _card(page, env, "PA2-catalog-author.png", "PA2",
          "已安装商品作者归属（author）真实读取", path, r["status"],
          {"installed_count": len(installed), "sample": sample})
    return {"status": r["status"], "installed_count": len(installed), "sample": sample}, ok


def case_revenue_chart(page, env):
    path = "/api/ai/kitten/charts/revenue"
    r = _api(page, path)
    body = r.get("body") or {}
    data = body.get("data") or {}
    ok = (r["status"] == 200 and body.get("success") is True and body.get("type") == "line"
          and isinstance(data.get("labels"), list) and isinstance(data.get("revenue"), list)
          and len(data.get("labels")) == len(data.get("revenue")) > 0
          and isinstance(data.get("orders"), list))
    _card(page, env, "PA3-revenue-chart.png", "PA3",
          "月度营收趋势口径真实读取", path, r["status"], body)
    return {"status": r["status"], "title": body.get("title"), "labels": data.get("labels"),
            "revenue": data.get("revenue"), "orders": data.get("orders")}, ok


def case_share_reconciler_employee(page, env):
    roster = _api(page, "/api/mod/ecosystem-revenue-share-reconciler/employees")
    status = _api(page,
                  "/api/mod/ecosystem-revenue-share-reconciler/employees/"
                  "ecosystem-revenue-share-reconciler/status")
    rows = ((roster.get("body") or {}).get("data")) or []
    emp = ((status.get("body") or {}).get("data")) or {}
    names = [r.get("label") for r in rows]
    ok = (roster["status"] == 200 and status["status"] == 200
          and any(r.get("id") == "ecosystem-revenue-share-reconciler" for r in rows)
          and emp.get("status") == "ready")
    _card(page, env, "PA4-share-reconciler.png", "PA4",
          "生态分润对账员工在册且状态就绪", "/api/mod/ecosystem-revenue-share-reconciler/employees[/.../status]",
          status["status"], {"employees": rows, "status": emp})
    return {"roster_status": roster["status"], "employees": names,
            "status_status": status["status"], "employee_status": emp.get("status")}, ok


def case_payables_ledger(page, env):
    path = "/api/finance/payables?page=1&per_page=20"
    r = _api(page, path)
    body = r.get("body") or {}
    ok = (r["status"] == 200 and body.get("success") is True
          and isinstance(body.get("data"), list) and isinstance(body.get("total"), int))
    _card(page, env, "PA5-payables-ledger.png", "PA5",
          "结算应付台账真实读取（空台账如实返回）", path, r["status"], body)
    return {"status": r["status"], "total": body.get("total"), "row_count": len(body.get("data") or [])}, ok


def case_wallets_denied(page, env):
    path = "/api/xcmax/admin/market/wallets"
    r = _api(page, path)
    body = r.get("body") or {}
    ok = r["status"] == 401 and body.get("success") is False
    _card(page, env, "PA6-wallets-denied.png", "PA6",
          "市场结算钱包视图未绑定市场账号被拒", path, r["status"], body)
    return {"status": r["status"], "message": body.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号 admin、密码为掩码。",
    "PA1-employee-autonomy.png": "「员工自治」页真实渲染：副标题「运行自洽 · 履职覆盖 · 建议看板 · 问答 · 成绩单」，含 批量通过(0)、刷新 控件；红条如实提示「部分数据刷新失败：运行态/履职覆盖/建议/问答/成绩单：尚未绑定修茈服务器账号…」；分页 自治总览/建议看板/问答/成绩单 与 系统运行态/定时履职/能力证明/生产履职 指标卡。",
    "PA2-catalog-author.png": "本工具在真实浏览器中渲染的本轮响应：GET /api/mod-store/catalog 返回 200，success=true，installed_count=6，样例 author 含「成都修茈科技有限公司」「XCAGI」「XCAGI」「成都修茈科技有限公司」，均非空。",
    "PA3-revenue-chart.png": "本轮响应：GET /api/ai/kitten/charts/revenue 返回 200，type=line，title=月度营收趋势，labels=['2026-05'…'2026-09']，revenue 与 orders 等长并列（本轮全为 0）。",
    "PA4-share-reconciler.png": "本轮响应：GET /api/mod/ecosystem-revenue-share-reconciler/employees 返回 200（label=生态分润对账员）；.../status 返回 200 且 {employee_id:'ecosystem-revenue-share-reconciler', status:'ready'}。",
    "PA5-payables-ledger.png": "本轮响应：GET /api/finance/payables?page=1&per_page=20 返回 200，success=true，data=[]，total=0，page=1，per_page=20。",
    "PA6-wallets-denied.png": "本轮响应：GET /api/xcmax/admin/market/wallets 返回 401，success=false，message=尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization。",
    "__video__": "本轮真实浏览器会话录像（webm，21.44s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 员工自治页渲染 → 商品作者归属读取 → 营收趋势 → 分润对账员工状态 → 应付台账 → 结算钱包 401。",
}

CASES = [
    {"id": "PA1", "title": "「员工自治」页真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/employee-autonomy，等待 SPA 渲染后读取标题与正文。",
     "expected": "渲染出「员工自治」并含 履职覆盖/成绩单 等字样。",
     "run": case_employee_autonomy_ui},
    {"id": "PA2", "title": "已安装商品作者归属（author）真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/mod-store/catalog。",
     "expected": "200 且 success=true，installed 非空且每条 author 均非空。",
     "run": case_catalog_author},
    {"id": "PA3", "title": "月度营收趋势口径真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/ai/kitten/charts/revenue。",
     "expected": "200，type=line，labels 与 revenue/orders 等长且非空。",
     "run": case_revenue_chart},
    {"id": "PA4", "title": "生态分润对账员工在册且状态就绪",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch 员工清单与 ecosystem-revenue-share-reconciler 状态。",
     "expected": "两者均 200，员工 id 在册，状态 = ready。",
     "run": case_share_reconciler_employee},
    {"id": "PA5", "title": "结算应付台账真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/finance/payables?page=1&per_page=20。",
     "expected": "200 且 success=true，data 为数组，total 为整数（本轮为空台账）。",
     "run": case_payables_ledger},
    {"id": "PA6", "title": "市场结算钱包视图未绑定市场账号被拒",
     "input": "已建立的管理员会话，但未绑定市场 Authorization。",
     "actions": "页面上下文 fetch GET /api/xcmax/admin/market/wallets。",
     "expected": "HTTP 401，success=false，不返回钱包数据。",
     "run": case_wallets_denied},
]