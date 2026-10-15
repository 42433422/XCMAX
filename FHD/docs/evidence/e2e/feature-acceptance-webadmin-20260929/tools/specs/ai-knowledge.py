"""ai-knowledge（知识库与向量检索）Web 管理端真机验收用例。

impl：FHD/app/fastapi_routes/knowledge_v1.py、excel_vector.py。
真实接口面：/api/knowledge/v1/health（RAG 引擎健康）、/api/knowledge/v1/datasets（数据集与文档）、
/api/knowledge（兼容别名）、/api/knowledge/v1/query（查询，本环境受旧索引租户隔离门控拒绝）。
真实性边界：全部断言在真实浏览器页面上下文 fetch 复核；截图取自本轮真实渲染。
"""

FEATURE = "ai-knowledge"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后："
    "读取 RAG 引擎健康（embedder/语义向量可用）→ 读取数据集与已沉淀文档/切片 → "
    "经兼容别名 /api/knowledge 复核同一口径 → "
    "以真实 403 记录旧知识索引未提供租户隔离时的租户隔离门控（边界/负例）。"
)


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


def case_knowledge_health(page, env):
    r = _api(page, "/api/knowledge/v1/health")
    b = r.get("body") or {}
    ok = (r["status"] == 200 and b.get("rag_enabled") is True
          and b.get("embedder_available") is True and b.get("semantic_embedding_available") is True)
    body = {"status": r["status"], "rag_enabled": b.get("rag_enabled"),
            "embedder_available": b.get("embedder_available"),
            "semantic_embedding_available": b.get("semantic_embedding_available"),
            "indexed_chunks": b.get("indexed_chunks"), "dataset_count": b.get("dataset_count")}
    _card(page, env, "K1-knowledge-health.png", "K1", "知识库 RAG 引擎健康真实读取",
          "GET /api/knowledge/v1/health", r["status"], body)
    return body, ok


def case_datasets(page, env):
    r = _api(page, "/api/knowledge/v1/datasets")
    b = r.get("body") or {}
    datasets = b.get("datasets") or {}
    persy = datasets.get("persy-knowledge") or {}
    docs = persy.get("documents") or []
    ok = (r["status"] == 200 and bool(datasets) and persy.get("success") is True
          and int(persy.get("document_count") or 0) >= 1)
    body = {"status": r["status"], "dataset_keys": sorted(datasets),
            "persy_dataset_id": persy.get("dataset_id"),
            "document_count": persy.get("document_count"), "chunk_count": persy.get("chunk_count"),
            "sample_docs": [{"document_id": d.get("document_id"), "parser": d.get("parser"),
                             "text_length": d.get("text_length")} for d in docs[:3]]}
    _card(page, env, "K2-knowledge-datasets.png", "K2", "数据集与已沉淀文档/切片真实读取",
          "GET /api/knowledge/v1/datasets", r["status"], body)
    return body, ok


def case_alias(page, env):
    r = _api(page, "/api/knowledge")
    b = r.get("body") or {}
    d = b.get("data") or {}
    ok = (r["status"] == 200 and b.get("alias_of") == "/api/knowledge/v1/health"
          and d.get("rag_enabled") is True)
    return {"status": r["status"], "alias_of": b.get("alias_of"),
            "rag_enabled": d.get("rag_enabled"), "dataset_count": d.get("dataset_count")}, ok


def case_query_tenant_gate(page, env):
    r = _api(page, "/api/knowledge/v1/query", "POST", {"query": "验收样本", "dataset_id": "persy-knowledge"})
    b = r.get("body") or {}
    ok = r["status"] == 403 and "租户隔离" in str(b.get("message"))
    body = {"status": r["status"], "error_code": b.get("error_code"), "message": b.get("message"),
            "note": "旧知识索引未提供租户隔离时，查询被门控拒绝而非放行。"}
    _card(page, env, "K3-knowledge-boundary.png", "K3", "旧索引查询受租户隔离门控（边界/负例）",
          "POST /api/knowledge/v1/query", r["status"], body)
    return body, ok


CASES = [
    {"id": "K1", "title": "知识库 RAG 引擎健康真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/knowledge/v1/health。",
     "expected": "HTTP 200，rag_enabled / embedder_available / semantic_embedding_available 均为 true。",
     "run": case_knowledge_health},
    {"id": "K2", "title": "数据集与已沉淀文档真实读取",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/knowledge/v1/datasets。",
     "expected": "HTTP 200，含 persy-knowledge 数据集且 document_count≥1。",
     "run": case_datasets},
    {"id": "K3", "title": "兼容别名 /api/knowledge 复核同一口径",
     "input": "同上。",
     "actions": "在页面上下文 fetch GET /api/knowledge。",
     "expected": "HTTP 200，alias_of=/api/knowledge/v1/health，rag_enabled=true。",
     "run": case_alias},
    {"id": "K4", "title": "旧索引查询受租户隔离门控（负例/边界）",
     "input": "同上。",
     "actions": "在页面上下文 POST /api/knowledge/v1/query（query=验收样本）。",
     "expected": "HTTP 403，message 说明旧知识索引未提供租户隔离 —— 门控不放行。",
     "run": case_query_tenant_gate},
]

VISIBLE_RESULTS = {
    "K1-knowledge-health.png": "卡片「K1 · 知识库 RAG 引擎健康真实读取」：GET /api/knowledge/v1/health，200，{\"status\":200,\"rag_enabled\":true,\"embedder_available\":true,\"semantic_embedding_available\":true,\"indexed_chunks\":5,\"dataset_count\":1}。",
    "00-login-form.png": "管理端登录页「管理员登录 / XCMAX 服务器后台 · 平台运维 · 系统管理」：左侧蓝色品牌栏写「企业级 AI 对话与智能体 / 审批工作流与 ERP 集成 / 即时通讯与团队协作」，右侧账号框已填 admin、密码框为掩码（••••••••），可点蓝色「登 录 →」。",
    "__video__": "本轮真实浏览器会话录像（webm，13.2s，VP8 1600x1000 25fps，ffmpeg 实测）：管理员登录 → RAG 引擎健康 → 数据集与文档 → 别名复核 → 旧索引租户隔离 403。"
}