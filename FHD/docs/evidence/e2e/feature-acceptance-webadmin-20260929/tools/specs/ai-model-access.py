"""ai-model-access（模型接入与使用计费）Web 管理端真机验收用例。

被测对象：以 web 模式运行的自托管管理端（http://127.0.0.1:42423）。
impl 参考：FHD/app/services/conversation/llm_adapter.py（20+ 厂商 OpenAI 兼容适配、计费元数据）。
真实验证面：模型用量账本（/api/model-payment/usage）、token 用量与成本汇总
（/api/xcmax/admin/token-usage）、修茈会员套餐（/api/market/membership-plans），
以及未绑定市场账号时模型目录的 fail-closed 拒绝（/api/market/llm-catalog）。
管理端 UI：/admin/settings?section=model-payment（系统设置·模型服务）。
"""

FEATURE = "ai-model-access"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，真实鼠标键盘）在自托管 Web 管理端建立管理员会话后："
    "读取模型用量账本（本机 JSON ledger）→ 读取 token 用量与成本汇总（含 Codex 会话账本）→ "
    "未绑定修茈市场账号时模型目录被 fail-closed 拒绝 → 无会话上下文访问用量接口被拒；"
    "并在系统设置·模型服务页真实渲染会员套餐与账户区。"
)


def _api(page, path, method="GET", body=None):
    """在页面上下文真实发起 fetch（带 cookie 与 CSRF 双提交，POST 可用）。"""
    return page.evaluate(
        """async ([p, m, b]) => {
            try {
                const init = {method: m, credentials: 'include', headers: {}};
                if (b !== null && b !== undefined) {
                    init.headers['Content-Type'] = 'application/json';
                    init.body = JSON.stringify(b);
                }
                if (m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);
                    if (cm) init.headers['X-CSRF-Token'] = decodeURIComponent(cm[1]);
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch (e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0, 300)};
            } catch (e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body],
    )


def case_usage_ledger(page, env):
    r = _api(page, "/api/model-payment/usage")
    b = r.get("body") or {}
    d = b.get("data") or {}
    ok = (r["status"] == 200 and b.get("success") is True
          and d.get("backend") == "json" and bool(d.get("ledger_path")))
    return {"status": r["status"], "success": b.get("success"), "backend": d.get("backend"),
            "ledger_path": d.get("ledger_path"), "entry_count": d.get("count"),
            "wallet_backend": d.get("wallet_backend"),
            "entries_sample": (d.get("entries") or [])[:2]}, ok


def case_token_usage(page, env):
    r = _api(page, "/api/xcmax/admin/token-usage")
    b = r.get("body") or {}
    sources = b.get("sources") or {}
    ok = (r["status"] == 200 and b.get("success") is True
          and int(b.get("grand_total_tokens") or 0) > 0
          and "local" in sources
          and bool(sources.get("local", {}).get("available")))
    return {"status": r["status"], "success": b.get("success"),
            "grand_total_tokens": b.get("grand_total_tokens"),
            "grand_prompt_tokens": b.get("grand_prompt_tokens"),
            "grand_completion_tokens": b.get("grand_completion_tokens"),
            "grand_cost_usd": b.get("grand_cost_usd"),
            "sources": {k: {"available": v.get("available"), "source": v.get("source"),
                            "total_tokens": v.get("total_tokens")}
                        for k, v in sources.items()}}, ok


def case_market_catalog_denied(page, env):
    r = _api(page, "/api/market/llm-catalog")
    b = r.get("body") or {}
    ok = r["status"] == 401 and b.get("success") is False and "市场账号" in str(b.get("message"))
    return {"status": r["status"], "success": b.get("success"), "message": b.get("message")}, ok


def case_unauth_token_usage(page, env):
    ctx2 = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1500)
    r = pg2.evaluate(
        "async () => { try { const r = await fetch('/api/xcmax/admin/token-usage', {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){}"
        " return {status: r.status, body: j !== null ? j : t.slice(0,200)}; }"
        " catch(e) { return {status:0, body:String(e)}; } }"
    )
    ctx2.close()
    ok = r["status"] in (401, 403) and (r.get("body") or {}).get("success") is False
    return {"status": r["status"], "body": r.get("body")}, ok


def case_model_payment_page(page, env):
    page.goto(env["base"] + "/admin/settings?section=model-payment", wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(10):
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or ""
        if "模型服务" in text and "会员套餐" in text:
            break
    page.screenshot(path=str(env["shot"] / "M-settings-model-payment.png"))
    ok = "模型服务" in text and "会员套餐" in text
    return {"final_url": page.url, "has_model_service": "模型服务" in text,
            "has_membership": "会员套餐" in text,
            "text_head": text.replace("\n", " ")[:260]}, ok


CASES = [
    {"id": "M1", "title": "模型用量账本真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/model-payment/usage。",
     "expected": "HTTP 200、success=true，返回本机账本 backend=json 且带 ledger_path。",
     "run": case_usage_ledger},
    {"id": "M2", "title": "模型调用 token 用量与成本汇总",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/xcmax/admin/token-usage。",
     "expected": "HTTP 200、success=true，grand_total_tokens>0，sources.local.available=true。",
     "run": case_token_usage},
    {"id": "M3", "title": "未绑定市场账号时模型目录 fail-closed 拒绝（负例/边界）",
     "input": "已建立的管理员会话（本机未绑定修茈市场账号）。",
     "actions": "在页面上下文 fetch GET /api/market/llm-catalog。",
     "expected": "HTTP 401、success=false 且提示需绑定市场账号，不返回模型目录。",
     "run": case_market_catalog_denied},
    {"id": "M4", "title": "无会话访问用量接口被拒（负例）",
     "input": "全新的无会话浏览器上下文。",
     "actions": "在无 cookie 的上下文中 fetch GET /api/xcmax/admin/token-usage。",
     "expected": "被拒绝（401/403），不返回用量数据。",
     "run": case_unauth_token_usage},
    {"id": "M5", "title": "系统设置·模型服务页真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航到 /admin/settings?section=model-payment，等待渲染模型服务与会员套餐区。",
     "expected": "页面渲染「模型服务」与「会员套餐」区块。",
     "run": case_model_payment_page},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「管理员登录」：左侧蓝色品牌栏「XCMAX 服务器后台 · 平台运维 / 服务器后台与自动化治理」；右侧账号框已填 admin、密码框为掩码（●●●●●●●●），可点「登 录」，含忘记账号/忘记密码/帮助链接。",
    "M-settings-model-payment.png": "登录后进入「系统设置」，右侧「模型服务」区：副标题「余额与充值走修茈市场；本页汇总展示，支付在 钱包/套餐 完成」，含「打开修茈钱包 / 会员套餐 / 刷新」按钮、账户余额（本机汇总）与「尚未绑定修茈市场账号，请先登录软件」提示、快捷充值、修茈会员套餐（3 档）与「模型支持」条目。",
    "__video__": "本轮真实浏览器会话录像（webm，17.28s，1600x1000，ffmpeg 实测）：管理员登录 → 用量账本/token 用量读取 → 市场模型目录被拒 → 无会话被拒 → 模型服务页渲染。",
}