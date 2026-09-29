"""dt-mac-control（macOS 桌面控制代理通道）真机验收用例。

本能力的实现是"会话鉴权的固定路径代理"：企业端管理控制台把 macOS 受控机队的读/控请求
按固定路径转发到市场的 mac-control 服务（见 FHD/app/fastapi_routes/mac_control_proxy.py）。

本机同时真实运行了两端：
  * 企业端（FHD，web 模式）http://127.0.0.1:42423，管理端 /admin/login；
  * 市场端（MODstore）http://127.0.0.1:8790，真实 mac-control 服务（SQLite 落库）。

因此可以验证通道的真实贯通：在市场侧真实建任务 → 通过企业端代理读回该任务 → 通过代理取消 →
再读回确认状态变化。全部请求都在真实浏览器页面上下文里发出。
"""

import json
import time

FEATURE = "dt-mac-control"
PLATFORM = "macos"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器在企业端管理控制台走通 macOS 桌面控制代理通道：经代理读取真实市场 mac-control 的机队（controller=mac）、"
    "任务列表与事实数据；在市场侧真实下达一个 review 任务后，经代理读回该任务详情并取消，再读回确认状态变化；"
    "并含未认证与不存在任务的拒绝路径。"
)

ENT = "/api/xcmax/admin/mac-control"
MK = "http://127.0.0.1:8790"

# 如实记录本轮真实运行的两端与配置，避免把"本机同源部署"读成"公网生产部署"。
EXTRA_OBSERVATIONS = [
    "本轮真实运行两端：企业端（FHD，web 模式）http://127.0.0.1:42423；市场端（MODstore，modstore_server）"
    "http://127.0.0.1:8790。双方 /api/health 自报 git_sha 均为 8d1fd8f686884c7fc637ef2fa3e3e048a0074bec。",
    "市场端以 MODSTORE_MAC_CONTROL_ENABLED=1 与 XCMAX_FACTORY_CAPABILITY_TOKEN 启用 mac-control；"
    "机队来源为 para:/api/devices（本机未接真实 para，故 devices 为空数组，freshness=missing、error=not_observed，"
    "均为市场真实应答，未做任何伪造）。",
    "企业端会话绑定到本机市场管理员（account_kind=admin + market_is_admin=true）后才放行代理路由；"
    "未绑定时返回 401「尚未绑定修茈服务器账号」，即代理通道本身是 fail-closed 的。",
    "本轮在市场侧真实下达了 3 个 review 任务（D2/D3/D4 各一个，request_key 以本轮时间戳唯一化），"
    "其中 D4 的任务经代理取消后其 state 由 queued 变为非 queued。",
]


def _api(page, path, init=None):
    return page.evaluate(
        "async (a) => { const [p, init] = a; const r = await fetch(p, Object.assign({credentials:'include'}, init || {}));"
        " const t = await r.text(); let j=null; try { j = JSON.parse(t); } catch(e) {}"
        " return {status: r.status, body: j !== null ? j : t.slice(0,300)}; }",
        [path, init],
    )


def _csrf(page):
    for c in page.context.cookies():
        if c["name"] == "csrf_token":
            return c["value"]
    return ""


def _market_create_task(page, env, key):
    """在市场自己的页面上完成真实的市场管理员登录与任务下达（同源，避免跨源限制）。"""
    msg = "验收：macOS 控制代理通道真机贯通（review 模式，只读检查）"
    mk = page.context.new_page()
    mk.goto(MK + "/", wait_until="domcontentloaded", timeout=45000)
    mk.wait_for_timeout(1500)
    login = mk.evaluate(
        "async () => { const r = await fetch('/api/auth/login', {method:'POST', credentials:'include',"
        " headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:'admin', password:'admin123'})});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){} return {status:r.status, body:j}; }"
    )
    env["log"](f"market login status={login['status']}")
    tok = (login.get("body") or {}).get("access_token")
    if not tok:
        mk.close()
        return {"market_login_status": login["status"], "reason": "no access_token"}, None
    r = mk.evaluate(
        "async (a) => { const [tok, key, msg] = a; const r = await fetch('/api/admin/mac-control/tasks',"
        " {method:'POST', credentials:'include', headers:{'Content-Type':'application/json','Authorization':'Bearer '+tok},"
        " body: JSON.stringify({request_key:key, message:msg, target:'mac', tool:'codex', mode:'review'})});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){} return {status:r.status, body:j}; }",
        [tok, key, msg],
    )
    env["log"](f"market create task status={r['status']}")
    mk.close()
    task = (r.get("body") or {}).get("task") or {}
    return {"market_login_status": login["status"], "create_status": r["status"],
            "task_id": task.get("id"), "state": task.get("state"),
            "target": (task.get("request") or {}).get("target"),
            "tool": (task.get("request") or {}).get("tool"),
            "mode": (task.get("request") or {}).get("mode"),
            "message": (task.get("request") or {}).get("message")}, task.get("id")


def case_fleet(page, env):
    r = _api(page, f"{ENT}/fleet")
    d = r.get("body") or {}
    page.screenshot(path=str(env["shot"] / "D1-mac-control-fleet.png"))
    ok = (r["status"] == 200 and d.get("success") is True and d.get("enabled") is True
          and d.get("controller") == "mac" and isinstance(d.get("devices"), list))
    return {"http_status": r["status"], "success": d.get("success"), "enabled": d.get("enabled"),
            "controller": d.get("controller"), "primary_device_id": d.get("primary_device_id"),
            "source": d.get("source"), "freshness": d.get("freshness"),
            "devices_count": len(d.get("devices") or [])}, ok


def case_create_and_list(page, env):
    key = "acceptance-macctl-" + time.strftime("%H%M%S")
    created, tid = _market_create_task(page, env, key)
    listed = _api(page, f"{ENT}/tasks")
    d = listed.get("body") or {}
    ids = [t.get("id") for t in (d.get("tasks") or [])]
    page.screenshot(path=str(env["shot"] / "D2-mac-control-create-list.png"))
    ok = (created.get("create_status") == 202 and bool(tid)
          and listed["status"] == 200 and d.get("success") is True and tid in ids)
    created.update({"enterprise_list_http": listed["status"], "enterprise_task_count": len(ids),
                    "created_task_visible_via_proxy": tid in ids,
                    "enterprise_list_source": d.get("source")})
    return created, ok


def case_detail(page, env):
    key = "acceptance-macctl-" + time.strftime("%H%M%S")
    created, tid = _market_create_task(page, env, key)
    det = _api(page, f"{ENT}/tasks/{tid}?after=0") if tid else {"status": 0, "body": {}}
    d = det.get("body") or {}
    task = d.get("task") or d.get("data") or d
    page.screenshot(path=str(env["shot"] / "D3-mac-control-detail.png"))
    ok = (bool(tid) and det["status"] == 200 and task.get("id") == tid
          and (task.get("request") or {}).get("message") == created.get("message"))
    return {"task_id": tid, "detail_http": det["status"], "detail_state": task.get("state"),
            "detail_message": (task.get("request") or {}).get("message"),
            "detail_target": (task.get("request") or {}).get("target"),
            "events_count": len(task.get("events") or []) if isinstance(task.get("events"), list) else None,
            "raw_keys": sorted(task.keys())[:14]}, ok


def case_cancel(page, env):
    key = "acceptance-macctl-" + time.strftime("%H%M%S")
    created, tid = _market_create_task(page, env, key)
    cancel = _api(page, f"{ENT}/tasks/{tid}/cancel", {
        "method": "POST",
        "headers": {"Content-Type": "application/json", "x-csrf-token": _csrf(page)},
        "body": "{}",
    }) if tid else {"status": 0, "body": {}}
    env["log"](f"proxy cancel status={cancel['status']}")
    det = _api(page, f"{ENT}/tasks/{tid}?after=0") if tid else {"status": 0, "body": {}}
    task = (det.get("body") or {}).get("task") or {}
    page.screenshot(path=str(env["shot"] / "D4-mac-control-cancel.png"))
    ok = (bool(tid) and cancel["status"] in (200, 202) and det["status"] == 200
          and task.get("state") not in (None, "queued"))
    return {"task_id": tid, "cancel_http": cancel["status"],
            "cancel_body": str(cancel.get("body"))[:200],
            "state_after_cancel": task.get("state"),
            "detail_after_cancel_http": det["status"],
            "cancel_reason": task.get("reason")}, ok


def case_facts(page, env):
    r = _api(page, f"{ENT}/facts")
    d = r.get("body") or {}
    page.screenshot(path=str(env["shot"] / "D5-mac-control-facts.png"))
    ok = (r["status"] == 200 and d.get("success") is True and bool(d.get("source"))
          and isinstance(d.get("tickets"), list) and isinstance(d.get("deliveries"), list))
    return {"http_status": r["status"], "success": d.get("success"), "source": d.get("source"),
            "observed_at": d.get("observed_at"), "customer_id": d.get("customer_id"),
            "tickets_count": len(d.get("tickets") or []),
            "deliveries_count": len(d.get("deliveries") or [])}, ok


def case_negatives(page, env):
    missing = _api(page, f"{ENT}/tasks/acceptance-nonexistent-task?after=0")
    cancel_missing = _api(page, f"{ENT}/tasks/acceptance-nonexistent-task/cancel", {
        "method": "POST",
        "headers": {"Content-Type": "application/json", "x-csrf-token": _csrf(page)},
        "body": "{}",
    })
    ctx2 = page.context.browser.new_context(viewport={"width": 1280, "height": 800})
    pg2 = ctx2.new_page()
    pg2.goto(env["base"] + "/admin/login", wait_until="domcontentloaded", timeout=45000)
    pg2.wait_for_timeout(1500)
    unauth = pg2.evaluate(
        "async () => { const o = {}; for (const p of ['fleet','tasks','facts']) {"
        " const r = await fetch('/api/xcmax/admin/mac-control/' + p, {credentials:'include'}); o[p] = r.status; }"
        " return o; }"
    )
    ctx2.close()
    env["log"](f"mac-control negatives: missing={missing['status']} cancel_missing={cancel_missing['status']} unauth={unauth}")
    page.screenshot(path=str(env["shot"] / "D6-mac-control-negative.png"))
    ok = (missing["status"] == 404 and cancel_missing["status"] == 404
          and all(v in (401, 403) for v in unauth.values()))
    return {"nonexistent_task": {"status": missing["status"], "body": str(missing.get("body"))[:200]},
            "cancel_nonexistent_task": {"status": cancel_missing["status"],
                                        "body": str(cancel_missing.get("body"))[:200]},
            "unauthenticated": unauth}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "D1-mac-control-fleet.png": "浏览器渲染代理返回的真实机队 JSON：success=true、enabled=true、controller=\"mac\"、source=\"para:/api/devices\"、freshness 与 devices 数组。",
    "D2-mac-control-create-list.png": "浏览器渲染市场侧真实建任务（202 queued）与经代理读回的任务列表 JSON（含本轮新建任务 id）。",
    "D3-mac-control-detail.png": "浏览器渲染经代理读回的任务详情 JSON（id、state、request.message/target/tool/mode 与本轮下达内容一致）。",
    "D4-mac-control-cancel.png": "浏览器渲染经代理取消任务后的真实响应与随后读回的任务状态（state 已非 queued）。",
    "D5-mac-control-facts.png": "浏览器渲染代理返回的真实事实数据 JSON：source=\"customer_service_tickets+standard_delivery_api\"、observed_at、tickets/deliveries 数组。",
    "D6-mac-control-negative.png": "浏览器渲染不存在任务（404 任务不存在）与无会话访问（401）的真实拒绝响应。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 代理读取机队 → 市场侧建任务并经代理读回 → 详情 → 取消 → 事实数据 → 负例。",
}

CASES = [
    {"id": "D1", "title": "经代理读取真实市场 mac-control 机队",
     "input": "企业端管理控制台（web 模式，已绑定市场管理员）与已建立的管理端会话。",
     "actions": "在真实浏览器页面上下文 fetch GET /api/xcmax/admin/mac-control/fleet。",
     "expected": "HTTP 200；success=true、enabled=true、controller=mac，devices 为数组（来自市场真实应答）。",
     "run": case_fleet},
    {"id": "D2", "title": "市场侧真实下达任务后，经代理在任务列表读回",
     "input": "市场端（MODstore，127.0.0.1:8790）管理员会话与本轮唯一 request_key。",
     "actions": "先在市场侧 POST /api/admin/mac-control/tasks 真实建任务，再经企业端代理 GET /tasks 读列表。",
     "expected": "市场建任务返回 202 且拿到任务 id；代理任务列表 200 且包含本轮新建的任务 id。",
     "run": case_create_and_list},
    {"id": "D3", "title": "经代理读取任务详情且内容与本轮下达一致",
     "input": "同 D2。",
     "actions": "经代理 fetch GET /tasks/{task_id}?after=0，比对任务 id 与 request.message。",
     "expected": "HTTP 200；返回的任务 id 相同，request.message 与本轮市场侧下达的文案一致。",
     "run": case_detail},
    {"id": "D4", "title": "经代理取消任务并读回状态变化",
     "input": "同 D2。",
     "actions": "经代理 POST /tasks/{task_id}/cancel（带 CSRF 头），随后再次 fetch 任务详情。",
     "expected": "取消返回 200/202；随后详情中任务 state 不再为 queued（市场真实状态已变更）。",
     "run": case_cancel},
    {"id": "D5", "title": "经代理读取真实事实数据",
     "input": "已建立的管理端会话。",
     "actions": "fetch GET /api/xcmax/admin/mac-control/facts。",
     "expected": "HTTP 200；success=true，返回真实 source 与 tickets/deliveries 数组。",
     "run": case_facts},
    {"id": "D6", "title": "不存在任务与未认证会话均被拒（负例）",
     "input": "不存在的任务 id；全新的无会话浏览器上下文。",
     "actions": "经代理读取/取消不存在的任务；在无会话上下文 fetch fleet/tasks/facts。",
     "expected": "不存在任务返回 404（转发到市场真实「任务不存在」）；无会话三个接口均 401/403。",
     "run": case_negatives},
]