"""统一 Agent Runtime 主链路四接缝实现。

接缝与调用方：
- ``recall_knowledge_context``：agent_orchestrator ``_plan``（pre-plan 知识库召回）
- ``meter_llm_call`` / ``completion_usage``：planner_llm_gateway、employee agent_loop、
  其它此前绕过计费的 LLM 调用点（计费不受开关限制，始终生效）
- ``remember_run_outcome``：agent_orchestrator 终态（completed/failed）回写记忆

约定：
- 记忆/RAG hooks 由 ``XCAGI_AGENT_RUNTIME_HOOKS`` 灰度门控（默认关，显式 on 开启）；
- 记忆读写是尽力而为的旁路——任何后端不可用都降级为空结果并记 debug 日志，
  绝不让主链路因旁路失败而中断（与 ``employee_runtime.memory`` 同一约定）。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_ON_VALUES = frozenset({"1", "true", "yes", "on"})

_SHORT_TERM_MAX_CHARS = 4000
_LONG_TERM_MAX_CHARS = 600


def agent_runtime_hooks_enabled() -> bool:
    """主链路 hooks（记忆/RAG 召回与回写）总开关。

    显式 on（``XCAGI_AGENT_RUNTIME_HOOKS=1/true/yes/on``）才启用；
    未配置或其它值默认关闭（灰度门控，与 langgraph legacy 默认门同一惯例）。
    计费计量不经过本开关，始终生效。
    """
    raw = str(os.environ.get("XCAGI_AGENT_RUNTIME_HOOKS", "")).strip().lower()
    return raw in _ON_VALUES


def recall_knowledge_context(
    *,
    query: str,
    dataset_id: str = "",
    top_k: int = 5,
) -> dict[str, Any]:
    """知识库 RAG 召回（dataset 向量索引），返回 RetrievalCall 兼容 dict。

    ``dataset_id`` 为空时跳过（当前无全局知识索引，dataset 由 runtime_context 指定）。
    返回字段与 ``AgentRun.retrieval_calls`` 条目对齐：
    ``{query, retriever, source, top_k, chunks, citations, status, error}``。
    """
    base: dict[str, Any] = {
        "query": str(query or ""),
        "retriever": "dataset_rag",
        "source": str(dataset_id or ""),
        "top_k": max(1, int(top_k)),
        "chunks": [],
        "citations": [],
        "status": "completed",
        "error": "",
    }
    if not str(dataset_id or "").strip():
        base["status"] = "skipped"
        return base
    try:
        from app.application.dataset_rag_app_service_part05 import (
            get_dataset_rag_app_service,
        )

        res = get_dataset_rag_app_service().query(
            dataset_id=str(dataset_id).strip(),
            query=str(query or "").strip(),
            top_k=max(1, int(top_k)),
        )
    except RECOVERABLE_ERRORS:
        logger.debug("knowledge recall skipped (dataset=%s)", dataset_id, exc_info=True)
        base["status"] = "failed"
        base["error"] = "knowledge recall unavailable"
        return base
    if not isinstance(res, dict):
        base["status"] = "failed"
        base["error"] = "knowledge recall returned invalid payload"
        return base
    raw_chunks = res.get("chunks")
    raw_citations = res.get("citations")
    chunks = raw_chunks if isinstance(raw_chunks, list) else []
    citations = raw_citations if isinstance(raw_citations, list) else []
    if res.get("success") is False:
        base["status"] = "failed"
        base["error"] = str(res.get("message") or "knowledge recall failed")[:500]
        return base
    base["chunks"] = [c for c in chunks if isinstance(c, dict)]
    base["citations"] = [c for c in citations if isinstance(c, dict)]
    return base


def completion_usage(completion: Any) -> dict[str, int]:
    """从 OpenAI 兼容 completion 对象/ dict 提取 token 用量。

    缺失字段一律按 0 处理；同时兼容 ``dict``（httpx JSON）与对象属性两种形态。
    """
    usage = getattr(completion, "usage", None)
    if usage is None and isinstance(completion, dict):
        usage = completion.get("usage")

    def _num(holder: Any, key: str) -> int:
        value = getattr(holder, key, None)
        if value is None and isinstance(holder, dict):
            value = holder.get(key)
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    prompt = _num(usage, "prompt_tokens")
    completion_tokens = _num(usage, "completion_tokens")
    total = _num(usage, "total_tokens") or (prompt + completion_tokens)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion_tokens,
        "total_tokens": total,
    }


def meter_llm_call(
    *,
    source: str,
    model: str,
    usage: dict[str, int] | None = None,
    run_id: str = "",
    user_id: str = "",
    provider: str = "",
    provider_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """统一 LLM 计量入口：写 model_usage 账本（best-effort，失败返回 None）。

    计费是主链路的硬性接缝，不经过 ``agent_runtime_hooks_enabled`` 开关。
    """
    tokens = usage or {}
    try:
        from app.infrastructure.billing.model_usage import record_model_usage

        return record_model_usage(
            run_id=str(run_id or ""),
            user_id=str(user_id or ""),
            provider_id=str(provider_id or ""),
            provider=str(provider or ""),
            model=str(model or ""),
            prompt_tokens=int(tokens.get("prompt_tokens") or 0),
            completion_tokens=int(tokens.get("completion_tokens") or 0),
            total_tokens=int(tokens.get("total_tokens") or 0),
            source=str(source or ""),
            metadata=dict(metadata or {}),
        )
    except RECOVERABLE_ERRORS:
        logger.debug("meter_llm_call failed (source=%s)", source, exc_info=True)
        return None


def remember_run_outcome(
    *,
    user_id: str,
    task: str,
    summary: str,
    success: bool = True,
    session_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> bool:
    """run 终态记忆回写：短期会话 SQL + 长期用户向量（与 planner 召回同命名空间）。

    长期内容形如 ``[agent_run] status=...; task=...; outcome=...``，命名空间为
    ``user_id``（planner 的 ``UserMemoryRag.query(user_id=...)`` 可召回）。
    全部 best-effort：任一后端失败只降级，返回整体是否至少写入一条。
    """
    task_text = str(task or "").strip()
    summary_text = str(summary or "").strip()
    if not task_text and not summary_text:
        return False
    wrote = False
    meta = json_dumps_safe({"kind": "agent_run", **(metadata or {})})
    sid = str(session_id or "").strip()
    if sid:
        wrote = (
            _remember_short_term(
                session_id=sid,
                user_id=str(user_id or ""),
                task=task_text,
                summary=summary_text,
                metadata_json=meta,
            )
            or wrote
        )
    wrote = (
        _remember_long_term(
            user_id=str(user_id or ""),
            task=task_text,
            summary=summary_text,
            success=success,
            extra_metadata=dict(metadata or {}),
        )
        or wrote
    )
    return wrote


def _remember_short_term(
    *, session_id: str, user_id: str, task: str, summary: str, metadata_json: str
) -> bool:
    try:
        from app.services.conversation_service import ConversationService

        svc = ConversationService()
        if task:
            svc.save_message(
                session_id, user_id, "user", task[:_SHORT_TERM_MAX_CHARS], metadata=metadata_json
            )
        if summary:
            svc.save_message(
                session_id,
                user_id,
                "assistant",
                summary[:_SHORT_TERM_MAX_CHARS],
                metadata=metadata_json,
            )
        return True
    except RECOVERABLE_ERRORS:
        logger.debug("short-term remember skipped", exc_info=True)
        return False


def _remember_long_term(
    *,
    user_id: str,
    task: str,
    summary: str,
    success: bool,
    extra_metadata: dict[str, Any],
) -> bool:
    if not str(user_id or "").strip():
        return False
    content = (
        f"[agent_run] status={'completed' if success else 'failed'}; "
        f"task={task[:200]}; outcome={summary[:_LONG_TERM_MAX_CHARS]}"
    )
    try:
        from app.application.user_memory_vector_app_service import (
            UserMemoryVectorChunk,
            get_user_memory_vector_ingest_app_service,
        )

        chunk = UserMemoryVectorChunk(
            chunk_id=uuid.uuid4().hex,
            content=content,
            metadata={
                "source": "agent_runtime",
                "success": bool(success),
                **{
                    k: v
                    for k, v in extra_metadata.items()
                    if isinstance(v, (str, int, float, bool))
                },
            },
        )
        res = get_user_memory_vector_ingest_app_service().ingest_chunks(
            str(user_id).strip(), [chunk]
        )
        return bool(isinstance(res, dict) and res.get("success"))
    except RECOVERABLE_ERRORS:
        logger.debug("long-term remember skipped", exc_info=True)
        return False


def json_dumps_safe(payload: dict[str, Any]) -> str:
    try:
        import json

        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return "{}"


__all__ = [
    "agent_runtime_hooks_enabled",
    "completion_usage",
    "json_dumps_safe",
    "meter_llm_call",
    "recall_knowledge_context",
    "remember_run_outcome",
]
