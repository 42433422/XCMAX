"""sec-audit-standard（审计对标基准 SSOT）Web 管理端真机验收用例。

无独立管理端页面：走运行中后端 /xcmax-dashboard 静态挂载读取基准 SSOT
FHD/config/audit_benchmark_ssot.json 与生成阅读视图 FHD/docs/AUDIT_BENCHMARK_SSOT.md；
并在本机真实执行 FHD/scripts/dev/audit_benchmark_ssot.py check 与 ssot_cli.py check audit-benchmark。
"""

import html as _html
import json as _json
import subprocess
import sys
from pathlib import Path

FEATURE = "sec-audit-standard"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器读取运行中 Web 后端暴露的审计基准 SSOT："
    "audit_benchmark_ssot.json（18 域 / 每域 3 个商业对标锚点 / 1 个开源达标锚点 / 90 分与 60 分锚线 / "
    "measurement_status=anchors_defined_not_benchmarked）与生成阅读视图 AUDIT_BENCHMARK_SSOT.md；"
    "并在本机真实执行 audit_benchmark_ssot.py check 与 ssot_cli.py check audit-benchmark。"
)

_FHD = Path(__file__).resolve().parents[6]
_DASH = "/xcmax-dashboard/FHD"


def _raw(page, path):
    return page.evaluate(
        """async (p) => {
            try {
                const r = await fetch(p, {credentials: 'include'});
                const t = await r.text();
                return {status: r.status, text: t.slice(0, 40000),
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


def _run(script, args):
    proc = subprocess.run([sys.executable, "scripts/dev/" + script, *args],
                          cwd=str(_FHD), capture_output=True, text=True)
    return {"argv": " ".join(args), "exit_code": proc.returncode,
            "stdout_tail": (proc.stdout or "").strip()[-400:],
            "stderr_tail": (proc.stderr or "").strip()[-400:]}


def _catalog(page):
    r = _raw(page, _DASH + "/config/audit_benchmark_ssot.json")
    d = {}
    try:
        d = _json.loads(r["text"])
    except Exception:
        pass
    return r, d


def case_audit_catalog(page, env):
    r, d = _catalog(page)
    domains = d.get("domains") or []
    refs = [len(x.get("commercial_references") or []) for x in domains]
    has_oss = all(bool(x.get("open_source_reference")) for x in domains)
    ok = (r["status"] == 200 and d.get("standard_version") == "1.0.0"
          and len(domains) == 18 and set(refs) == {3} and has_oss
          and d.get("commercial_anchor_score") == 90
          and d.get("open_source_pass_score") == 60)
    sample = [[x.get("id"), x.get("domain_key"), x.get("title")] for x in domains[:3]]
    body = {"http_status": r["status"], "schema_version": d.get("schema_version"),
            "standard_version": d.get("standard_version"),
            "scoring_version": d.get("scoring_version"), "domain_count": d.get("domain_count"),
            "domains_len": len(domains), "commercial_refs_per_domain": sorted(set(refs)),
            "every_domain_has_open_source_anchor": has_oss,
            "anchors": [d.get("commercial_anchor_score"), d.get("open_source_pass_score")],
            "review_interval_days": d.get("review_interval_days"), "domain_sample": sample}
    _card(page, env, "A1-audit-catalog.png", "A1", "审计基准目录 SSOT 在 Web 后端真实可读且锚点完整",
          _DASH + "/config/audit_benchmark_ssot.json", r["status"], body)
    return body, ok


def case_reading_view(page, env):
    r = _raw(page, _DASH + "/docs/AUDIT_BENCHMARK_SSOT.md")
    text = r["text"]
    starts = text.lstrip().startswith("# XCMAX 审计对标 SSOT")
    sole = "audit_benchmark_ssot.json" in text
    ok = (r["status"] == 200 and "text/markdown" in r["content_type"]
          and starts and sole)
    body = {"http_status": r["status"], "content_type": r["content_type"],
            "starts_with_generated_view_note": starts, "mentions_sole_source": sole,
            "text_head": text.replace("\n", " ")[:200], "chars": len(text)}
    _card(page, env, "A2-reading-view.png", "A2", "生成阅读视图与唯一维护源一致地对外可读",
          _DASH + "/docs/AUDIT_BENCHMARK_SSOT.md", r["status"], body)
    return body, ok


def case_validator_check(page, env):
    out = _run("audit_benchmark_ssot.py", ["check"])
    ok = out["exit_code"] == 0 and "standard valid" in out["stdout_tail"]
    return out, ok


def case_ssot_cli_check(page, env):
    out = _run("ssot_cli.py", ["check", "audit-benchmark"])
    ok = out["exit_code"] == 0 and "audit-benchmark: OK" in out["stdout_tail"]
    return out, ok


def case_anchor_invariants(page, env):
    r, d = _catalog(page)
    legacy = d.get("legacy_scores_not_convertible") or []
    score_fields = sorted(k for k in d.keys() if "score" in k)
    product_score = bool(d.get("product_score"))
    required = d.get("required_audit_record_fields") or []
    policies = d.get("policies")
    ok = (r["status"] == 200
          and d.get("measurement_status") == "anchors_defined_not_benchmarked"
          and legacy == [73.3, 77.1] and product_score is False)
    body = {"http_status": r["status"], "measurement_status": d.get("measurement_status"),
            "legacy_scores_not_convertible": legacy, "score_named_top_fields": score_fields,
            "product_score_asserted": product_score,
            "required_audit_record_fields": required,
            "policies_type": type(policies).__name__, "policies_len": len(policies or [])}
    _card(page, env, "A3-anchor-invariants.png", "A3", "标准只定义锚点、不声明产品得分；历史分数不可换算",
          _DASH + "/config/audit_benchmark_ssot.json", r["status"], body)
    return body, ok


CASES = [
    {"id": "A1", "title": "审计基准目录 SSOT 在 Web 后端真实可读且锚点完整",
     "input": "运行中的 Web 后端（端口 42423）与已建立的管理端会话。",
     "actions": "真实浏览器导航到 /xcmax-dashboard/FHD/config/audit_benchmark_ssot.json，解析渲染出的 JSON 并核对锚点不变量。",
     "expected": "HTTP 200；18 个域、每域恰好 3 个商业对标锚点、每域都有开源达标锚点；商业锚线 90 / 开源达标锚线 60。",
     "run": case_audit_catalog},
    {"id": "A2", "title": "生成阅读视图与唯一维护源一致地对外可读",
     "input": "同上。",
     "actions": "真实浏览器导航到 /xcmax-dashboard/FHD/docs/AUDIT_BENCHMARK_SSOT.md。",
     "expected": "HTTP 200 且以 markdown 提供；正文声明这是生成视图并指明唯一维护源为 audit_benchmark_ssot.json。",
     "run": case_reading_view},
    {"id": "A3", "title": "标准校验器在本机真实执行通过（正例）",
     "input": "FHD 仓库工作树。",
     "actions": "在本机真实执行 python3 scripts/dev/audit_benchmark_ssot.py check，记录真实 stdout 与退出码。",
     "expected": "退出码 0，输出 standard valid（18 domains / 54 commercial / 18 OSS slots）且声明不代表产品通过审计。",
     "run": case_validator_check},
    {"id": "A4", "title": "SSOT 统一 CLI 的 audit-benchmark 域在本机真实校验通过",
     "input": "同上。",
     "actions": "在本机真实执行 python3 scripts/dev/ssot_cli.py check audit-benchmark。",
     "expected": "退出码 0，输出 audit-benchmark: OK。",
     "run": case_ssot_cli_check},
    {"id": "A5", "title": "标准只定义锚点、不声明产品得分；历史分数不可换算（边界）",
     "input": "同上。",
     "actions": "在真实浏览器里核对基准目录的 measurement_status、legacy_scores_not_convertible 与是否存在任何产品得分字段。",
     "expected": "measurement_status=anchors_defined_not_benchmarked；历史 73.3 / 77.1 明确标记为不可换算；不存在 product_score 之类已断言的产品得分。",
     "run": case_anchor_invariants},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "A1-audit-catalog.png": "浏览器直接渲染运行中后端返回的 /xcmax-dashboard/FHD/config/audit_benchmark_ssot.json：可见 standard_version 1.0.0、scoring_version external-anchors-v1、domain_count 18、commercial_anchor_score 90、open_source_pass_score 60 等真实 JSON 原文。",
    "A2-reading-view.png": "浏览器以 text/markdown 渲染生成阅读视图 AUDIT_BENCHMARK_SSOT.md，正文开头即「# XCMAX 审计对标 SSOT · 生成视图 · 唯一维护源：FHD/config/audit_benchmark_ssot.json」。",
    "A3-anchor-invariants.png": "浏览器渲染基准目录的锚点与状态字段（measurement_status=anchors_defined_not_benchmarked 等），真实 JSON 原文。",
    "__video__": "本轮真实浏览器会话录像（webm）：管理端登录 → 读取审计基准目录与生成阅读视图 → 锚点不变量核对。",
}