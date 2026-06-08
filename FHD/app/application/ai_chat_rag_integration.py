"""AI 聊天 RAG 集成（Phase 3.3）。

开关：`XCAGI_RAG_ENABLED=1`

行为：
  - 拦截 AI 聊天调用
  - 若 RAG 启用：先从知识库检索 → 拼 prompt → 注入 [1][2] 引用
  - 响应中加 `citations` 字段

降级：
  - 若 RAG 不可用（无知识库 / embedder 异常），fallback 到无 RAG 模式
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.infrastructure.rag import (
    RagService,
    get_default_embedder,
    is_rag_enabled,
)

logger = logging.getLogger(__name__)

_rag_service: RagService | None = None


def get_rag_service() -> RagService | None:
    """获取（或惰性初始化）RagService 单例。"""
    global _rag_service
    if _rag_service is None and is_rag_enabled():
        try:
            embedder = get_default_embedder()
            _rag_service = RagService(embedder=embedder)
            logger.info("RagService 初始化成功 (embedder=%s)", embedder is not None)
        except (ImportError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("RagService 初始化失败（不阻断主流程）: %s", e)
            _rag_service = None
    return _rag_service


def augment_chat_with_rag(
    *,
    user_message: str,
    knowledge_text: str,
    llm_call: Callable[[str, str], str],
    top_k: int = 5,
) -> dict[str, Any]:
    """
    RAG 增强的聊天调用。

    返回：{
      "answer": str,
      "citations": [...],
      "rag_enabled": bool,
      "chunks": [...],
    }
    """
    rag = get_rag_service()
    if rag is None:
        # RAG 未启用或初始化失败 → 直接调 LLM
        return {
            "answer": llm_call(user_message, ""),
            "citations": [],
            "rag_enabled": False,
            "chunks": [],
        }

    try:
        result = rag.answer(
            user_message=user_message,
            knowledge_text=knowledge_text,
            llm_call=llm_call,
            top_k=top_k,
        )
        result["rag_enabled"] = True
        return result
    except (ValueError, TypeError, KeyError) as e:
        logger.warning("RAG 调用异常，降级无 RAG 模式: %s", e)
        return {
            "answer": llm_call(user_message, ""),
            "citations": [],
            "rag_enabled": False,
            "chunks": [],
            "rag_error": str(e),
        }


def get_rag_status() -> dict[str, Any]:
    """供 /api/rag/status 健康检查用。"""
    enabled = is_rag_enabled()
    service = get_rag_service() if enabled else None
    return {
        "enabled": enabled,
        "service_available": service is not None,
        "embedder_available": get_default_embedder() is not None,
    }
