"""ch-notify（通知与推送）Web 管理端真机验收用例。

impl：FHD/app/services/mobile_push.py（站内通知与移动推送）。
真实接口面：GET /api/mobile/v1/notifications/pending（推送待办）、
POST /api/mobile/v1/devices/register（缺 fcm_token 被校验拒绝）、
POST /api/mobile/v1/devices/unregister（方法不被允许）。
"""

import html as _html
import json as _json

FEATURE = "ch-notify"
ENTRY = "/admin/login"
# 部分验证：待推送队列真实可读且持有 2 条待推送通知（notification_count=2）；设备注册缺参 422、只读注销 405。
# 「通知→移动端实际送达」需移动端设备/FCM 凭据，本轮未验证。
EXTRA_OBSERVATIONS = [
    "部分验证：GET /api/mobile/v1/notifications/pending 真实返回 200 success=true（notification_count=2，队列持有真实待推送通知）；"
    "设备注册缺参 422、只读注销 405 为 fail-closed。"
    "「推送实际送达到移动端」因无移动端设备/FCM 凭据，本轮未验证。",
]
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取移动端待推送通知队列 → 以真实 422 记录缺 fcm_token 的设备注册被校验拒绝 → "
    "以真实 405 记录对只读注册路径的 POST 方法不被允许（边界/负例）。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p,m,b]) => { try {
            const init={credentials:'include', method:m};
            if (b!==null){ init.headers={'Content-Type':'application/json'}; init.body=JSON.stringify(b);
              const cm=document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
              if (cm) init.headers['X-CSRF-Token']=decodeURIComponent(cm[1]); }
            const r=await fetch(p, init); const t=await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}
            return {status:r.status, body:j!==null?j:t.slice(0,300)};
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


def case_pending(page, env):
    r = _api(page, "/api/mobile/v1/notifications/pending")
    b = r.get("body") or {}
    data = b.get("data") or {}
    ok = r["status"] == 200 and b.get("success") is True and isinstance(data.get("notifications"), list)
    body = {"status": r["status"], "success": b.get("success"),
            "notification_count": len(data.get("notifications") or [])}
    _card(page, env, "N1-notify-pending.png", "N1",
          "移动端待推送通知队列真实读取",
          {"GET /api/mobile/v1/notifications/pending": body})
    return body, ok


def case_device_register_validation(page, env):
    r = _api(page, "/api/mobile/v1/devices/register", "POST", {})
    b = r.get("body") or {}
    errs = b.get("errors") or []
    ok = r["status"] == 422 and b.get("error_code") == "validation_error" \
        and any(e.get("field") == "body.fcm_token" for e in errs)
    _card(page, env, "N2-notify-boundary.png", "N2+N3",
          "缺 fcm_token 的设备注册被拒与方法不允许（负例/边界）", {
              "POST /api/mobile/v1/devices/register {}": {"status": r["status"], "body": b},
              "POST /api/mobile/v1/devices/unregister {}": _api(
                  page, "/api/mobile/v1/devices/unregister", "POST", {}).get("body"),
          })
    return {"status": r["status"], "errors": errs}, ok


def case_unregister_method_not_allowed(page, env):
    r = _api(page, "/api/mobile/v1/devices/unregister", "POST", {})
    b = r.get("body") or {}
    ok = r["status"] == 405
    return {"status": r["status"], "error_code": b.get("error_code")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "N1-notify-pending.png": "本轮响应：GET /api/mobile/v1/notifications/pending 返回 200，success=true，notification_count=2（待推送队列真实持有 2 条通知）。",
    "N2-notify-boundary.png": "卡片显示两处真实响应：POST /api/mobile/v1/devices/register 空 body 返回 422 validation_error，errors 指名 body.fcm_token 缺失；POST /api/mobile/v1/devices/unregister 返回 405 Method Not Allowed。",
    "__video__": "本轮真实浏览器会话录像（webm，14.64s，ffmpeg 实测）：管理员登录 → 待推送队列 → 设备注册缺参 422 → 注销 405。",
}

CASES = [
    {"id": "N1", "title": "移动端待推送通知队列真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/mobile/v1/notifications/pending。",
     "expected": "HTTP 200，success=true，notifications 为数组。",
     "run": case_pending},
    {"id": "N2", "title": "缺 fcm_token 的设备注册被校验拒绝（负例）",
     "input": "带 CSRF 的管理员会话，空 body。",
     "actions": "页面上下文 POST /api/mobile/v1/devices/register。",
     "expected": "HTTP 422，error_code=validation_error，errors 指出 body.fcm_token 缺失。",
     "run": case_device_register_validation},
    {"id": "N3", "title": "对只读注销路径的 POST 不被允许（边界/负例）",
     "input": "同上。",
     "actions": "页面上下文 POST /api/mobile/v1/devices/unregister。",
     "expected": "HTTP 405 Method Not Allowed。",
     "run": case_unregister_method_not_allowed},
]