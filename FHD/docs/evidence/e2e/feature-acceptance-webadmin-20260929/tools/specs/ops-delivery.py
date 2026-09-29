"""ops-delivery（客户专属交付与进度）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/private_mod_delivery_routes.py
（/api/mod-store/private-delivery/requests）、
FHD/app/fastapi_routes/private_mod_delivery_progress_routes.py
（/api/mod/xcagi-customer-service-bridge/user-cs/delivery）。
管理端 UI：/admin/delivery-center（客户交付中心）。
"""

import html as _html
import json as _json

FEATURE = "ops-delivery"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端完成：管理员登录 → "
    "「客户交付中心」页真实渲染（定制交付工单 / 生产进行中 / 已受理·AI 生产中·待验收·待返工 阶段，"
    "及「客户安装与业务验收独立核对」交付口径）→ "
    "提交客户定制需求在未绑定市场账号时被身份门禁拒绝（401）→ "
    "非法 kind 被参数校验拒绝（400）→ "
    "交付进度接口按 market_user_id 返回交付里程碑（status=planned）。"
    "本机未绑定修茈市场账号，故专属 Mod 交付的 200 正向流转不可达，相关拒绝路径为真实产品响应。"
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


def _card(page, env, name, cid, title, req, status, body):
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
        f"<div class='kv'><span class='k'>请求</span>{_html.escape(req)}</div>"
        f"<div class='kv'><span class='k'>HTTP 状态</span>{status}</div>"
        f"<pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def _delivery_request(env):
    return {"kind": "module", "name": "验收探针定制模块",
            "customer_scope": "测试客户", "notes": "验收用载荷"}


def case_delivery_center(page, env):
    text = _render(page, env, "/admin/delivery-center",
                   name="OD1-delivery-center.png", wait_for="客户交付中心")
    ok = ("客户交付中心" in text and "定制交付工单" in text
          and "生产进行中" in text and "客户安装与业务验收独立核对" in text)
    return {"final_url": page.url, "title": page.title(),
            "has_delivery_center": "客户交付中心" in text,
            "has_custom_ticket": "定制交付工单" in text,
            "has_production_stage": "生产进行中" in text,
            "has_acceptance_wording": "客户安装与业务验收独立核对" in text,
            "text_head": text.replace("\n", " ")[:240]}, ok


def case_request_market_gate(page, env):
    r = _api(page, "/api/mod-store/private-delivery/requests", "POST", _delivery_request(env))
    b = r.get("body") or {}
    ok = r["status"] == 401 and b.get("success") is False and "绑定修茈市场账号" in str(b.get("message"))
    _card(page, env, "OD2-request-market-gate.png", "OD2",
          "提交客户定制需求未绑定市场账号被拒",
          "POST /api/mod-store/private-delivery/requests", r["status"], b)
    return {"status": r["status"], "message": b.get("message"),
            "error_code": b.get("error_code")}, ok


def case_invalid_kind_denied(page, env):
    payload = _delivery_request(env)
    payload["kind"] = "__bad__"
    r = _api(page, "/api/mod-store/private-delivery/requests", "POST", payload)
    b = r.get("body") or {}
    ok = r["status"] == 400 and "kind 必须是 module、employee 或 bundle" in str(b.get("message"))
    _card(page, env, "OD3-invalid-kind.png", "OD3",
          "定制需求 kind 非法被参数校验拒绝",
          "POST /api/mod-store/private-delivery/requests (kind=__bad__)", r["status"], b)
    return {"status": r["status"], "message": b.get("message")}, ok


def case_cs_delivery_progress(page, env):
    r = _api(page, "/api/mod/xcagi-customer-service-bridge/user-cs/delivery?market_user_id=1")
    b = r.get("body") or {}
    delivery = b.get("delivery") or {}
    ok = (r["status"] == 200 and b.get("success") is True
          and delivery.get("status") == "planned"
          and isinstance(delivery.get("milestones"), list))
    _card(page, env, "OD4-cs-delivery-progress.png", "OD4",
          "客户交付进度与里程碑",
          "GET /api/mod/xcagi-customer-service-bridge/user-cs/delivery?market_user_id=1",
          r["status"], {"delivery": delivery, "payment": b.get("payment")})
    return {"status": r["status"], "delivery": delivery,
            "payment": b.get("payment")}, ok


CASES = [
    {"id": "OD1", "title": "「客户交付中心」页真实渲染专属交付台账",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/delivery-center，等待 SPA 渲染后读取标题与正文。",
     "expected": "渲染出「客户交付中心」与「定制交付工单」「生产进行中」交付阶段及独立验收口径。",
     "run": case_delivery_center},
    {"id": "OD2", "title": "提交客户定制需求未绑定市场账号被拒（负例）",
     "input": "已建立的管理员会话，但未绑定修茈市场账号；合法定制需求载荷。",
     "actions": "页面上下文 POST /api/mod-store/private-delivery/requests。",
     "expected": "HTTP 401，success=false，提示需先登录并绑定市场账号。",
     "run": case_request_market_gate},
    {"id": "OD3", "title": "定制需求 kind 非法被参数校验拒绝（边界）",
     "input": "kind=__bad__，其余字段合法。",
     "actions": "页面上下文 POST /api/mod-store/private-delivery/requests。",
     "expected": "HTTP 400，success=false，提示 kind 必须是 module/employee/bundle。",
     "run": case_invalid_kind_denied},
    {"id": "OD4", "title": "客户交付进度与里程碑真实读取",
     "input": "market_user_id=1。",
     "actions": "页面上下文 GET /api/mod/xcagi-customer-service-bridge/user-cs/delivery?market_user_id=1。",
     "expected": "HTTP 200、success=true，delivery.status=planned，milestones 为列表。",
     "run": case_cs_delivery_progress},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "OD1-delivery-center.png": "「客户交付中心」页真实渲染：顶部「Mac 主控 · 四设备协同」（目标/执行设备/任务类型/关联工单）与红字「尚未绑定修茈服务器账号…」及「客户安装与业务验收独立核对；执行器报告完成不等于已交付。」；下方 CUSTOMER DELIVERY CONTROL「客户交付中心」台账：企业用户/永久购买账户/体验账户/永久待安装/待首次登录/永久交付完成/内部本机排除/定制交付工单/生产进行中 均为 0，含搜索框与「全部阶段｜定制工单」筛选。",
    "OD2-request-market-gate.png": "本轮响应：POST /api/mod-store/private-delivery/requests → 401，success=false，error_code=http_401，message=请先登录并绑定修茈市场账号。",
    "OD3-invalid-kind.png": "本轮响应：POST /api/mod-store/private-delivery/requests（kind=__bad__）→ 400，success=false，message=kind 必须是 module、employee 或 bundle。",
    "OD4-cs-delivery-progress.png": "本轮响应：GET /api/mod/xcagi-customer-service-bridge/user-cs/delivery?market_user_id=1 → 200，success=true，delivery={milestones:[], status:'planned'}，payment={}，invoice={}。",
    "__video__": "本轮真实浏览器会话录像（webm，17.56s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → 客户交付中心 → 定制需求 401 → kind 非法 400 → 交付进度 200。",
}