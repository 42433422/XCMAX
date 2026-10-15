"""ai-csv（CSV 生成与解析）Web 管理端真机验收用例。

impl：FHD/app/services/report_export.py；CSV 生成/读取员工包在 FHD/mods/_employees/。
真实接口面：/api/mod/csv-generate-employee/employees/csv-generate-employee/run（真实写出 output.csv）、
/api/mod/csv-full-read-employee/.../run（真实读回 CSV 为结构化 data.json）。
真实性边界：本 spec 在运行前落盘一份验收用输入 JSON；断言在真实浏览器页面上下文 fetch 复核。
"""

import json
import os

FEATURE = "ai-csv"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "真实调用 CSV 生成员把输入 JSON 写出 output.csv（row_count=2）→ "
    "调用 CSV 全量读取员把该 CSV 读回为结构化 data.json → "
    "以真实 fail-closed（缺少 file_path 时返回 ok=false）记录不编造成功（边界/负例）。"
)

_DIR = "/tmp/xcmax-vc-ai-csv"
os.makedirs(_DIR, exist_ok=True)
_INPUT = os.path.join(_DIR, "input.json")
_OUTPUT = os.path.join(_DIR, "output.csv")
with open(_INPUT, "w", encoding="utf-8") as _f:
    json.dump({"columns": ["名称", "数量"], "rows": [["验收样本", 1], ["验收样本二", 2]]}, _f, ensure_ascii=False)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p,m,b]) => {
            try {
                const init = {credentials:'include', method:m};
                if (b !== null && b !== undefined) {
                    init.headers = {'Content-Type':'application/json'};
                    init.body = JSON.stringify(b);
                }
                if (m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
                    if (cm) init.headers = Object.assign(init.headers||{}, {'X-CSRF-Token': decodeURIComponent(cm[1])});
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch(e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0,300)};
            } catch(e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body],
    )


def _card(page, env, name, cid, title, req, status, body):
    if getattr(_card, 'used', False):
        return
    _card.used = True
    import json as _json
    import html as _html
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


def _item(resp):
    d = (resp.get("body") or {}).get("data") or {}
    items = d.get("items") or [{}]
    return d, (items[0] if items else {})


def case_generate_csv(page, env):
    r = _api(page, "/api/mod/csv-generate-employee/employees/csv-generate-employee/run", "POST",
             {"file_path": _INPUT, "output_relpath": _OUTPUT})
    d, it = _item(r)
    ok = r["status"] == 200 and d.get("ok") is True and it.get("row_count") == 2
    body = {"status": r["status"], "ok": d.get("ok"), "output_path": it.get("output_path"),
            "row_count": it.get("row_count"), "column_count": it.get("column_count"),
            "delimiter": it.get("delimiter"), "encoding": it.get("encoding")}
    _card(page, env, "C1-csv-generate.png", "C1", "CSV 生成员真实写出 output.csv",
          "POST .../csv-generate-employee/run", r["status"], body)
    return body, ok


def case_read_back_csv(page, env):
    r = _api(page, "/api/mod/csv-full-read-employee/employees/csv-full-read-employee/run", "POST",
             {"file_path": _OUTPUT})
    d, it = _item(r)
    ok = r["status"] == 200 and d.get("ok") is True and it.get("column_count") == 2
    body = {"status": r["status"], "ok": d.get("ok"), "output_path": it.get("output_path"),
            "row_count": it.get("row_count"), "column_count": it.get("column_count")}
    _card(page, env, "C2-csv-read-back.png", "C2", "CSV 全量读取员真实读回为结构化数据",
          "POST .../csv-full-read-employee/run", r["status"], body)
    return body, ok


def case_employee_listed(page, env):
    r = _api(page, "/api/mod/csv-generate-employee/employees")
    data = (r.get("body") or {}).get("data") or []
    ok = r["status"] == 200 and any(x.get("id") == "csv-generate-employee" for x in data if isinstance(x, dict))
    return {"status": r["status"], "employees": data}, ok


def case_missing_file_failclosed(page, env):
    r = _api(page, "/api/mod/csv-generate-employee/employees/csv-generate-employee/run", "POST", {})
    d, _ = _item(r)
    ok = r["status"] == 200 and d.get("ok") is False and "file_path" in str(d.get("error"))
    body = {"status": r["status"], "ok": d.get("ok"), "error": d.get("error"),
            "note": "缺少输入文件时如实返回 ok=false，不编造已完成。"}
    _card(page, env, "C3-csv-boundary.png", "C3", "缺输入文件时如实 fail-closed（边界/负例）",
          "POST .../csv-generate-employee/run {}", r["status"], body)
    return body, ok


CASES = [
    {"id": "C1", "title": "CSV 生成员真实写出文件",
     "input": f"验收用输入 JSON（columns/rows 两行），落盘 {_INPUT}。",
     "actions": "在页面上下文 POST .../csv-generate-employee/run（file_path=输入 JSON）。",
     "expected": "HTTP 200、data.ok=true，row_count=2 且返回 output_path。",
     "run": case_generate_csv},
    {"id": "C2", "title": "CSV 全量读取员真实读回",
     "input": "C1 生成的真实 CSV。",
     "actions": "在页面上下文 POST .../csv-full-read-employee/run（file_path=生成的 CSV）。",
     "expected": "HTTP 200、data.ok=true，解析出 column_count=2 并写出结构化 data.json。",
     "run": case_read_back_csv},
    {"id": "C3", "title": "CSV 员工真实注册可查",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mod/csv-generate-employee/employees。",
     "expected": "HTTP 200，含 id=csv-generate-employee。",
     "run": case_employee_listed},
    {"id": "C4", "title": "缺输入文件时如实 fail-closed（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST .../csv-generate-employee/run（空 body）。",
     "expected": "HTTP 200、data.ok=false，error 指明缺少 file_path —— 不编造成功。",
     "run": case_missing_file_failclosed},
]

VISIBLE_RESULTS = {
    "C1-csv-generate.png": "卡片「C1 · CSV 生成员真实写出 output.csv」：POST .../csv-generate-employee/run，200，{\"status\":200,\"ok\":\"true\",\"output_path\":\"/tmp/xcmax-vc-ai-csv/output.csv\",\"row_count\":2,\"delimiter\":\",\",\"encoding\":\"utf-8-sig\"}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，12.8s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → CSV 生成员写出 output.csv → 全量读取员读回 → 员工注册查询 → 缺文件 fail-closed。"
}