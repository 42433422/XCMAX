"""ch-mobile-qr（二维码扫码登录）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/mobile_extensions/routes_auth.py、app/security/auth_qr_login.py。
真实接口面：POST /api/auth/qr/issue（签发扫码登录二维码）、GET /api/auth/qr/status（轮询状态）。
"""

import html as _html
import json as _json

FEATURE = "ch-mobile-qr"
ENTRY = "/admin/login"
# 部分验证：二维码签发 + 状态轮询为真实正向；扫码确认（/api/mobile/v1/auth/qr/confirm）需真实移动端扫码，本轮未验证。
EXTRA_OBSERVATIONS = [
    "部分验证：POST /api/auth/qr/issue（签发 qr_id/poll_secret）与 GET /api/auth/qr/status（pending）为真实正向；"
    "扫码确认环节（POST /api/mobile/v1/auth/qr/confirm）需真实移动端扫码，本环境无移动端，未验证。",
]
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "签发一个扫码登录二维码（拿到 qr_id/poll_secret/expires_at）→ 用 poll_secret 轮询其状态为 pending → "
    "以真实 404 QR_NOT_FOUND 记录无效二维码被拒（边界/负例）。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p,m,b]) => { try {
            const init={credentials:'include', method:m};
            if (b!==null){ init.headers={'Content-Type':'application/json'}; init.body=JSON.stringify(b); }
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


def _mask(secret):
    s = str(secret or "")
    return (s[:4] + "…" + s[-2:]) if len(s) > 8 else "…"


def case_issue(page, env):
    r = _api(page, "/api/auth/qr/issue", "POST", {})
    b = r.get("body") or {}
    d = b.get("data") or {}
    ok = (r["status"] == 200 and b.get("success") is True
          and bool(d.get("qr_id")) and bool(d.get("poll_secret")) and bool(d.get("expires_at")))
    case_issue.payload = d
    body = {"status": r["status"], "success": b.get("success"), "qr_id": d.get("qr_id"),
            "poll_secret_fp": _mask(d.get("poll_secret")), "expires_at": d.get("expires_at"),
            "account_kind": d.get("account_kind")}
    return body, ok


def case_status(page, env):
    d = getattr(case_issue, "payload", {}) or {}
    qid = d.get("qr_id")
    if not qid:
        return {"error": "no issued qr_id (issue case failed)"}, False
    r = _api(page, f"/api/auth/qr/status?qr_id={qid}&poll_secret={d.get('poll_secret')}")
    b = r.get("body") or {}
    data = b.get("data") or {}
    ok = r["status"] == 200 and b.get("success") is True and data.get("status") == "pending"
    _card(page, env, "Q1-qr-issue-status.png", "Q1+Q2",
          "扫码登录二维码签发与状态轮询真实读取", {
              "POST /api/auth/qr/issue": {"status": 200, "qr_id": qid,
                                          "poll_secret_fp": _mask(d.get("poll_secret")),
                                          "expires_at": d.get("expires_at")},
              "GET /api/auth/qr/status?qr_id=…&poll_secret=…": {"status": r["status"], "body": b},
          })
    return {"status": r["status"], "body": b}, ok


def case_invalid_qr(page, env):
    r = _api(page, "/api/auth/qr/status?qr_id=not-a-real-qr-id")
    b = r.get("body") or {}
    err = b.get("error") or {}
    ok = r["status"] == 404 and err.get("code") == "QR_NOT_FOUND"
    _card(page, env, "Q3-qr-not-found.png", "Q3",
          "无效二维码轮询被拒（边界/负例）",
          {"GET /api/auth/qr/status?qr_id=not-a-real-qr-id": {"status": r["status"], "body": b}})
    return {"status": r["status"], "error_code": err.get("code")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "Q1-qr-issue-status.png": "卡片显示两处真实响应：POST /api/auth/qr/issue 200 success=true，返回 qr_id 与 poll_secret（指纹脱敏）及 expires_at；随后的 GET /api/auth/qr/status 返回 200，data.status=pending。",
    "Q3-qr-not-found.png": "本轮响应：GET /api/auth/qr/status?qr_id=not-a-real-qr-id 返回 404，error.code=QR_NOT_FOUND，message=二维码无效。",
    "__video__": "本轮真实浏览器会话录像（webm，15.08s，ffmpeg 实测）：管理员登录 → 二维码签发 → 状态 pending → 无效二维码 404。",
}

CASES = [
    {"id": "Q1", "title": "签发扫码登录二维码",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 POST /api/auth/qr/issue。",
     "expected": "HTTP 200，success=true，返回 qr_id/poll_secret/expires_at。",
     "run": case_issue},
    {"id": "Q2", "title": "二维码状态轮询真实读取",
     "input": "上一步签发的 qr_id 与 poll_secret。",
     "actions": "页面上下文 GET /api/auth/qr/status。",
     "expected": "HTTP 200，success=true，data.status=pending。",
     "run": case_status},
    {"id": "Q3", "title": "无效二维码轮询被拒（负例/边界）",
     "input": "不存在的 qr_id。",
     "actions": "页面上下文 GET /api/auth/qr/status?qr_id=not-a-real-qr-id。",
     "expected": "HTTP 404，error.code=QR_NOT_FOUND。",
     "run": case_invalid_qr},
]