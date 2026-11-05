"""ai-vector-rag（知识库向量检索 / RAG 工具链）Web 管理端真机验收用例。

impl 参考：FHD/app/services/tools_workflow_memory_rag.py（dataset_rag / memory_v2 工作流路由）。
真实验证面：知识库向量引擎健康（/api/knowledge/v1/health）、真实入库切片
（POST /api/knowledge/v1/ingest）、语义召回命中本轮入库内容（POST /api/knowledge/v1/query），
以及缺参被拒的边界（/api/knowledge/v1/query、/api/excel/vector/query）。
管理端 UI：/admin/persy/knowledge（全知知识网络：文档/切片/召回）。
"""

import time

FEATURE = "ai-vector-rag"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，真实鼠标键盘）在自托管 Web 管理端建立管理员会话后："
    "读取 RAG 引擎健康（embedder/语义向量可用）→ 真实入库一段唯一标记文本 → "
    "语义召回该唯一标记（chunks 命中）→ 缺 query 被 422、缺 index_id 被 400；"
    "并真实渲染全知知识网络页。"
)

_TOKEN = "验收RAG样本-" + time.strftime("%H%M%S")


def _api(page, path, method="GET", body=None):
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


def case_rag_health(page, env):
    r = _api(page, "/api/knowledge/v1/health")
    b = r.get("body") or {}
    ok = (r["status"] == 200 and b.get("rag_enabled") is True
          and b.get("embedder_available") is True and b.get("semantic_embedding_available") is True)
    return {"status": r["status"], "rag_enabled": b.get("rag_enabled"),
            "embedder_available": b.get("embedder_available"),
            "semantic_embedding_available": b.get("semantic_embedding_available"),
            "indexed_sources": b.get("indexed_sources"), "indexed_chunks": b.get("indexed_chunks"),
            "dataset_count": b.get("dataset_count")}, ok


def case_rag_ingest(page, env):
    r = _api(page, "/api/knowledge/v1/ingest", "POST",
             {"text": _TOKEN, "dataset_id": "verify-accept"})
    b = r.get("body") or {}
    ok = r["status"] == 200 and b.get("success") is True and int(b.get("chunk_count") or 0) >= 1
    return {"status": r["status"], "success": b.get("success"),
            "chunk_count": b.get("chunk_count"), "strategy": b.get("strategy"),
            "source": b.get("source"), "message": b.get("message"),
            "ingested_text": _TOKEN}, ok


def case_rag_query_hit(page, env):
    r = _api(page, "/api/knowledge/v1/query", "POST", {"query": _TOKEN})
    b = r.get("body") or {}
    chunks = b.get("chunks") or []
    texts = [c.get("text") for c in chunks if isinstance(c, dict)]
    ok = (r["status"] == 200 and b.get("success") is True
          and any(_TOKEN in str(t) for t in texts))
    return {"status": r["status"], "success": b.get("success"), "rag_enabled": b.get("rag_enabled"),
            "chunk_count": len(chunks), "chunks_sample": chunks[:3],
            "hit_token": any(_TOKEN in str(t) for t in texts)}, ok


def case_rag_query_missing_denied(page, env):
    r = _api(page, "/api/knowledge/v1/query", "POST", {})
    b = r.get("body") or {}
    fields = [e.get("field") for e in (b.get("errors") or []) if isinstance(e, dict)]
    ok = r["status"] == 422 and b.get("error_code") == "validation_error" and "body.query" in fields
    return {"status": r["status"], "error_code": b.get("error_code"), "fields": fields}, ok


def case_excel_vector_missing_index_denied(page, env):
    r = _api(page, "/api/excel/vector/query", "POST", {"query": "验收样本"})
    b = r.get("body") or {}
    ok = (r["status"] == 400 and b.get("error_code") == "schema_validation_failed"
          and "index_id" in str(b.get("message")))
    return {"status": r["status"], "error_code": b.get("error_code"),
            "message": b.get("message")}, ok


def case_persy_knowledge_page(page, env):
    page.goto(env["base"] + "/admin/persy/knowledge", wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(10):
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or ""
        if "知识" in text and "召回" in text:
            break
    page.screenshot(path=str(env["shot"] / "V-persy-knowledge.png"))
    ok = "全知知识网络" in text or ("知识" in text and "召回" in text)
    return {"final_url": page.url, "has_omniscient": "全知知识网络" in text,
            "has_recall": "召回" in text, "text_head": text.replace("\n", " ")[:220]}, ok


CASES = [
    {"id": "V1", "title": "RAG 引擎与向量后端健康",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/knowledge/v1/health。",
     "expected": "HTTP 200，rag_enabled / embedder_available / semantic_embedding_available 均为 true。",
     "run": case_rag_health},
    {"id": "V2", "title": "知识入库真实写入切片",
     "input": "已建立的管理员会话与一段唯一标记文本。",
     "actions": "在页面上下文 POST /api/knowledge/v1/ingest（text=唯一标记, dataset_id=verify-accept）。",
     "expected": "HTTP 200、success=true，chunk_count>=1。",
     "run": case_rag_ingest},
    {"id": "V3", "title": "语义召回命中本轮入库内容",
     "input": "V2 入库的唯一标记文本。",
     "actions": "在页面上下文 POST /api/knowledge/v1/query（query=唯一标记）。",
     "expected": "HTTP 200、success=true，chunks 非空且包含本轮入库的唯一标记。",
     "run": case_rag_query_hit},
    {"id": "V4", "title": "缺 query 被拒（负例/边界）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/knowledge/v1/query（空 body）。",
     "expected": "HTTP 422、error_code=validation_error，缺失字段 body.query。",
     "run": case_rag_query_missing_denied},
    {"id": "V5", "title": "Excel 向量查询缺 index_id 被拒（负例/边界）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 POST /api/excel/vector/query（仅 query）。",
     "expected": "HTTP 400、error_code=schema_validation_failed，提示缺少字段 index_id。",
     "run": case_excel_vector_missing_index_denied},
    {"id": "V6", "title": "全知知识网络页真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航 /admin/persy/knowledge，等待渲染知识网络。",
     "expected": "页面渲染「全知知识网络」及知识/召回相关内容。",
     "run": case_persy_knowledge_page},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「管理员登录」：左侧蓝色品牌栏「XCMAX 服务器后台 · 平台运维 / 服务器后台与自动化治理」；右侧账号框已填 admin、密码框为掩码，可点「登 录」。",
    "V-persy-knowledge.png": "登录后进入「知识库 / OMNISCIENT CONSOLE 全知知识网络」：空间显示 persy-knowledge，视图切换「图谱/记忆/卡片/来源」与「关键词召回」及导入入口；画布显示 Persy 节点与「粘贴知识/对话记忆/导入资料」，右侧为节点/召回面板，底部为「问 Persy」提问框。",
    "__video__": "本轮真实浏览器会话录像（webm，13.96s，1600x1000，ffmpeg 实测）：管理员登录 → 引擎健康 → 入库唯一标记 → 语义召回命中 → 缺参被拒 → 知识网络页渲染。",
}