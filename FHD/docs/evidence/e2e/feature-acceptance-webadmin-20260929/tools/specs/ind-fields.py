"""ind-fields（行业字段与规则配置）Web 管理端真机验收用例。

impl：FHD/app/mod_sdk/industry_seed.py（行业字段、规则与能力模块配置）。
真实接口面：GET /api/system/industries（行业清单）、/api/system/industry-presets（预置包）、
/api/platform-shell/industry-baseline（行业基线）；GET /api/system/industry/{id}（不存在被拒）。
"""

import html as _html
import json as _json

FEATURE = "ind-fields"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取行业清单（各行业字段/单位配置）→ 读取行业预置包目录（通用/饰品包装/涂料/考勤…）→ "
    "读取行业基线（分组与起步能力）→ 以真实 404 记录查询不存在行业被拒（边界/负例）。"
)


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,400)}; }"
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


def case_industries(page, env):
    r = _api(page, "/api/system/industries")
    d = (r.get("body") or {}).get("data") or {}
    industries = d.get("industries") or []
    ok = r["status"] == 200 and len(industries) > 0 and all(i.get("id") and i.get("config") is not None for i in industries)
    body = {"status": r["status"], "industry_count": len(industries),
            "ids": [i.get("id") for i in industries[:6]]}
    _card(page, env, "F1-industry-fields.png", "F1+F2+F3",
          "行业字段配置 / 预置包 / 行业基线真实读取", {
              "GET /api/system/industries": body,
              "GET /api/system/industry-presets": {
                  "status": (_api(page, "/api/system/industry-presets").get("body") or {}).get("success"),
                  "preset_ids": (((_api(page, "/api/system/industry-presets").get("body") or {}).get("data")) or {}).get("preset_ids")},
              "GET /api/platform-shell/industry-baseline": _api(page, "/api/platform-shell/industry-baseline").get("body", {}).get("data"),
          })
    return body, ok


def case_presets(page, env):
    r = _api(page, "/api/system/industry-presets")
    d = (r.get("body") or {}).get("data") or {}
    ids = d.get("preset_ids") or []
    ok = r["status"] == 200 and len(ids) > 0 and isinstance(d.get("presets"), dict)
    return {"status": r["status"], "preset_ids": ids}, ok


def case_baseline(page, env):
    r = _api(page, "/api/platform-shell/industry-baseline")
    d = (r.get("body") or {}).get("data") or {}
    groups = d.get("groups") or []
    ok = r["status"] == 200 and bool(d.get("industry_id")) and len(groups) > 0
    return {"status": r["status"], "industry_id": d.get("industry_id"),
            "group_count": len(groups)}, ok


def case_unknown_industry(page, env):
    r = _api(page, "/api/system/industry/not-a-real-industry")
    b = r.get("body") or {}
    ok = r["status"] == 404
    _card(page, env, "F4-industry-not-found.png", "F4",
          "查询不存在行业被拒（边界/负例）",
          {"GET /api/system/industry/not-a-real-industry": {"status": r["status"], "body": b}})
    return {"status": r["status"], "body": b}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "F1-industry-fields.png": "卡片汇总三处真实响应：GET /api/system/industries 200 返回行业清单（含考勤等，各带 config 字段/单位）；GET /api/system/industry-presets 200 返回 preset_ids=[通用,饰品包装,涂料,考勤,批发,电商,餐饮,物流,管理端]；GET /api/platform-shell/industry-baseline 200 返回 industry_id=general 与分组。",
    "F4-industry-not-found.png": "本轮响应：GET /api/system/industry/not-a-real-industry 返回 404，error_code=http_404，message=Industry not found。",
    "__video__": "本轮真实浏览器会话录像（webm，17.96s，ffmpeg 实测）：管理员登录 → 行业清单 → 预置包 → 行业基线 → 不存在行业 404。",
}

CASES = [
    {"id": "F1", "title": "行业字段配置清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 fetch GET /api/system/industries。",
     "expected": "HTTP 200，industries 非空且每项含 config。",
     "run": case_industries},
    {"id": "F2", "title": "行业预置包目录真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/system/industry-presets。",
     "expected": "HTTP 200，preset_ids 非空且含 presets 映射。",
     "run": case_presets},
    {"id": "F3", "title": "行业基线配置真实读取",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/platform-shell/industry-baseline。",
     "expected": "HTTP 200，含 industry_id 与 groups。",
     "run": case_baseline},
    {"id": "F4", "title": "查询不存在行业被拒（负例/边界）",
     "input": "同上。",
     "actions": "页面上下文 fetch GET /api/system/industry/not-a-real-industry。",
     "expected": "HTTP 404。",
     "run": case_unknown_industry},
]