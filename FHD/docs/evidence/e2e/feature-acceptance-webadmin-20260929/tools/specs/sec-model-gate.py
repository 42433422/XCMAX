"""sec-model-gate（真实模型门禁信号）Web 管理端真机验收用例。

impl 参考：/api/health 的 cognition.llm_port_available 门禁信号、
FHD/app/fastapi_routes/desktop_models_routes.py（/api/desktop/models、/api/desktop/models/download）。
"""

import html as _html
import json as _json

FEATURE = "sec-model-gate"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在管理端页面上下文核验真实模型门禁："
    "GET /api/health 返回 cognition.llm_port_available 真实模型可用性门禁信号与构建 SHA → "
    "GET /api/desktop/models 返回模型清单 → "
    "缺少必填字段的模型下载请求被 422 拒绝（边界）。"
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


def case_llm_gate_signal(page, env):
    r = _api(page, "/api/health")
    d = r.get("body") or {}
    cog = ((d.get("neuro") or {}).get("cognition")) or d.get("cognition") or {}
    avail = cog.get("llm_port_available")
    ok = r["status"] == 200 and isinstance(avail, bool)
    body = {"status": r["status"], "llm_port_available": avail,
            "degraded_reasons": d.get("degradedReasons") or d.get("degraded_reasons"),
            "build_git_sha": ((d.get("build") or {}).get("git_sha"))}
    _card(page, env, "M1-llm-gate-signal.png", "M1", "真实模型可用性门禁信号可观察",
          "GET /api/health → cognition.llm_port_available", r["status"], body)
    return body, ok


def case_model_registry(page, env):
    r = _api(page, "/api/desktop/models")
    d = r.get("body") or {}
    models = d.get("models")
    ok = r["status"] == 200 and isinstance(models, list)
    _card(page, env, "M2-model-registry.png", "M2", "模型清单真实读取",
          "GET /api/desktop/models", r["status"],
          {"status": r["status"], "models_count": len(models) if isinstance(models, list) else None})
    return {"status": r["status"],
            "models_count": len(models) if isinstance(models, list) else None}, ok


def case_download_validation(page, env):
    r = _api(page, "/api/desktop/models/download", "POST", {})
    d = r.get("body") or {}
    fields = [e.get("loc", [None])[-1] for e in (d.get("detail") or [])] if isinstance(d.get("detail"), list) else []
    missing = sorted({"body." + f for f in fields if f})
    ok = r["status"] == 422 and {"body.name", "body.version", "body.url", "body.sha256"} <= set(missing)
    _card(page, env, "M3-download-validation.png", "M3", "模型下载缺必填字段被拒",
          "POST /api/desktop/models/download (empty body)", r["status"],
          {"status": r["status"], "missing_fields": missing})
    return {"status": r["status"], "missing_fields": missing}, ok


CASES = [
    {"id": "M1", "title": "真实模型可用性门禁信号可观察",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/health，读取 neuro.cognition.llm_port_available。",
     "expected": "200 且 llm_port_available 为布尔值。",
     "run": case_llm_gate_signal},
    {"id": "M2", "title": "模型清单真实读取",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/desktop/models。",
     "expected": "200 且返回 models 数组。",
     "run": case_model_registry},
    {"id": "M3", "title": "模型下载缺必填字段被拒（边界）",
     "input": "空对象。",
     "actions": "页面上下文 POST /api/desktop/models/download。",
     "expected": "422 且提示 name/version/url/sha256 缺失。",
     "run": case_download_validation},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页（管理员登录，账号 admin）。",
    "M1-llm-gate-signal.png": "GET /api/health 200：build.git_sha=8d1fd8f6…、cognition.llm_port_available=false、degradedReasons=[LLM_RUNTIME_UNAVAILABLE]（真实模型端口不可用，门禁信号可见）。",
    "M2-model-registry.png": "GET /api/desktop/models 200 body.models=[]（当前无已登记模型）。",
    "M3-download-validation.png": "POST /api/desktop/models/download 空 body → 422 validation_error，缺 body.name/version/url/sha256。",
    "__video__": "录像（webm，11.44s）：模型门禁信号 → 模型清单 → 下载缺参拒绝。",
}