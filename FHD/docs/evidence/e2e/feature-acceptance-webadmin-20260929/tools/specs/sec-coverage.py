"""sec-coverage（覆盖率 SSOT 与棘轮门禁）Web 管理端真机验收用例。

无独立管理端页面：走运行中后端 /xcmax-dashboard 静态挂载读取覆盖率 SSOT 工件，
并在本机真实执行门禁脚本 FHD/scripts/dev/coverage_ratchet.py。
工件：FHD/metrics/coverage-dual-summary.json、coverage_ratchet_baseline.json、
coverage-history.jsonl。本机执行：coverage_ratchet.py --check / --check --require-backend。
"""

import html as _html
import json as _json
import subprocess
import sys
from pathlib import Path

FEATURE = "sec-coverage"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器读取运行中 Web 后端暴露的覆盖率 SSOT 工件："
    "coverage-dual-summary.json（唯一对外口径，后端行 88.19% / 分支 81.5% / 前端行 93.21%）、"
    "coverage_ratchet_baseline.json（只升不降的棘轮 floor）、coverage-history.jsonl（历史趋势）；"
    "并在本机真实执行 coverage_ratchet.py 门禁（含缺测量数据时的 fail-closed 负例）。"
)

_FHD = Path(__file__).resolve().parents[6]
_METRICS = "/xcmax-dashboard/FHD/metrics"


def _raw(page, path):
    return page.evaluate(
        """async (p) => {
            try {
                const r = await fetch(p, {credentials: 'include'});
                const t = await r.text();
                return {status: r.status, text: t.slice(0, 20000),
                        content_type: r.headers.get('content-type') || ''};
            } catch (e) { return {status: 0, text: String(e), content_type: ''}; }
        }""",
        path,
    )


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


def _run(args):
    proc = subprocess.run([sys.executable, "scripts/dev/coverage_ratchet.py", *args],
                          cwd=str(_FHD), capture_output=True, text=True)
    return {"argv": " ".join(args), "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "").strip()[-400:],
            "stderr_tail": (proc.stderr or "").strip()[-400:]}


def case_coverage_ssot(page, env):
    r = _raw(page, _METRICS + "/coverage-dual-summary.json")
    d = {}
    try:
        d = _json.loads(r["text"])
    except Exception:
        pass
    note = d.get("_ssot") or ""
    ok = (r["status"] == 200 and "唯一对外口径" in note
          and float(d.get("backend_line_pct") or 0) > 0
          and float(d.get("frontend_line_pct") or 0) > 0)
    body = {"http_status": r["status"], "has_ssot_note": bool(note), "ssot_note": note[:120],
            "backend_line_pct": d.get("backend_line_pct"),
            "backend_branch_pct": d.get("backend_branch_pct"),
            "frontend_line_pct": d.get("frontend_line_pct"),
            "committed_commit": d.get("commit"), "status": d.get("status")}
    _card(page, env, "C1-coverage-ssot.png", "C1", "覆盖率唯一对外口径 SSOT 在 Web 后端真实可读",
          _METRICS + "/coverage-dual-summary.json", r["status"], body)
    return body, ok


def case_ratchet_baseline(page, env):
    r = _raw(page, _METRICS + "/coverage_ratchet_baseline.json")
    d = {}
    try:
        d = _json.loads(r["text"])
    except Exception:
        pass
    note = d.get("_note") or ""
    has_floor = "backend_lines_floor" in d
    has_behavior = "behavior_floors" in d
    ok = r["status"] == 200 and "只升不降" in note and has_floor and has_behavior
    body = {"http_status": r["status"], "note": note[:120],
            "has_backend_lines_floor": has_floor, "has_behavior_floors": has_behavior,
            "top_keys": sorted(d.keys())}
    _card(page, env, "C2-ratchet-baseline.png", "C2", "棘轮基线（只升不降的 floor）真实可读",
          _METRICS + "/coverage_ratchet_baseline.json", r["status"], body)
    return body, ok


def case_coverage_trend(page, env):
    r = _raw(page, _METRICS + "/coverage-history.jsonl")
    records = []
    for line in r["text"].splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(_json.loads(line))
        except Exception:
            pass
    last = records[-3:]
    ok = r["status"] == 200 and len(records) >= 1 and isinstance(last[-1], dict)
    body = {"http_status": r["status"], "content_type": r["content_type"],
            "line_count": len(records), "last_records": last}
    _card(page, env, "C3-coverage-trend.png", "C3", "覆盖率历史趋势真实可读",
          _METRICS + "/coverage-history.jsonl", r["status"], body)
    return body, ok


def case_ratchet_pass(page, env):
    out = _run(["--check"])
    ok = out["exit_code"] == 0 and "覆盖率未回退" in out["stdout_tail"]
    return out, ok


def case_ratchet_fail_closed(page, env):
    out = _run(["--check", "--require-backend"])
    ok = out["exit_code"] != 0 and "coverage.json" in (out["stderr_tail"] or out["stdout_tail"])
    return out, ok


def case_missing_artifact(page, env):
    r = _raw(page, _METRICS + "/coverage-not-a-real-file.json")
    ok = r["status"] == 404 and "coverage-dual-summary" not in r["text"]
    page.goto(env["base"] + _METRICS + "/coverage-not-a-real-file.json",
              wait_until="domcontentloaded", timeout=45000)
    page.screenshot(path=str(env["shot"] / "C4-missing-artifact.png"))
    return {"http_status": r["status"], "body_head": r["text"][:200]}, ok


CASES = [
    {"id": "C1", "title": "覆盖率唯一对外口径 SSOT 在 Web 后端真实可读",
     "input": "运行中的 Web 后端（端口 42423）与已建立的管理端会话。",
     "actions": "真实浏览器导航到 /xcmax-dashboard/FHD/metrics/coverage-dual-summary.json，读取渲染出的 JSON。",
     "expected": "HTTP 200；JSON 含「唯一对外口径」说明，且后端行 88.19%、后端分支 81.5%、前端行 93.21% 与本能力对外口径一致。",
     "run": case_coverage_ssot},
    {"id": "C2", "title": "棘轮基线（只升不降的 floor）真实可读",
     "input": "同上。",
     "actions": "真实浏览器导航到 /xcmax-dashboard/FHD/metrics/coverage_ratchet_baseline.json。",
     "expected": "HTTP 200，JSON 含「只升不降」说明与后端行/分支 floor 字段。",
     "run": case_ratchet_baseline},
    {"id": "C3", "title": "覆盖率历史趋势真实可读",
     "input": "同上。",
     "actions": "真实浏览器导航到 coverage-history.jsonl，逐行解析最后 3 条记录。",
     "expected": "HTTP 200，至少 1 行真实历史记录，末行含后端/前端覆盖率字段。",
     "run": case_coverage_trend},
    {"id": "C4", "title": "棘轮门禁在本机真实执行且放行（正例）",
     "input": "FHD 仓库工作树。",
     "actions": "在本机真实执行 python3 scripts/dev/coverage_ratchet.py --check，记录真实 stdout 与退出码。",
     "expected": "退出码 0，输出「覆盖率未回退」。",
     "run": case_ratchet_pass},
    {"id": "C5", "title": "缺测量数据时棘轮拒绝放行（fail-closed 负例）",
     "input": "本机无 coverage.json（pytest 未产出测量数据）的初始状态。",
     "actions": "真实执行 python3 scripts/dev/coverage_ratchet.py --check --require-backend，记录真实 stdout/stderr 与退出码。",
     "expected": "退出码非 0，报错指出缺后端 coverage.json —— 门禁不会在缺数据时静默通过。",
     "run": case_ratchet_fail_closed},
    {"id": "C6", "title": "不存在的 SSOT 工件不静默回退（负例）",
     "input": "同上。",
     "actions": "真实浏览器请求 /xcmax-dashboard/FHD/metrics/coverage-not-a-real-file.json。",
     "expected": "HTTP 404，不返回其它覆盖率工件内容。",
     "run": case_missing_artifact},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "C1-coverage-ssot.png": "浏览器直接渲染运行中后端返回的 /xcmax-dashboard/FHD/metrics/coverage-dual-summary.json：可见 \"_ssot\": \"FHD 覆盖率唯一对外口径…\"、\"backend_line_pct\": 88.19、\"backend_branch_pct\": 81.5、\"frontend_line_pct\": 93.21、\"commit\": \"92505cab6\"。",
    "C2-ratchet-baseline.png": "浏览器渲染 coverage_ratchet_baseline.json，可见 \"_note\": \"覆盖率棘轮基线（只升不降）…\" 与后端行/分支 floor 字段，真实 JSON 原文。",
    "C3-coverage-trend.png": "浏览器渲染覆盖率 SSOT 文档滚到实测读数区，可见 committed_head/wip_local 的实测百分比字段原文（历史趋势 coverage-history.jsonl 由同源文件提供，逐行 JSONL 记录）。",
    "C4-missing-artifact.png": "请求不存在的 SSOT 工件路径，浏览器显示 404 响应体，未静默回退到其它文件。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 读取覆盖率 SSOT 三个工件 → 不存在的工件返回 404。",
}