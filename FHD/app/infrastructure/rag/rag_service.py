"""RAG 服务聚合入口（语义分块 + 混合检索 + 引用溯源 + 注入 LLM）。"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .citation_tracker import CitationTracker
from .hybrid_retriever import HybridRetriever, RetrievedChunk
from .semantic_chunker import Chunk, SemanticChunker

logger = logging.getLogger(__name__)


@dataclass
class RagQuery:
    user_message: str
    knowledge_text: str  # 知识库全文（已分块前）
    embedder: Callable[[str], list[float]] | None = None
    top_k: int = 5
    chunk_strategy: str = "semantic"  # semantic | fixed
    chunk_size: int = 500
    chunk_overlap: int = 50


class RagService:
    """
    RAG 三件套聚合：chunker → retriever → citation tracker。
    """

    def __init__(
        self,
        embedder: Callable[[str], list[float]] | None = None,
        chunk_threshold: float = 0.5,
    ) -> None:
        self._embedder = embedder
        self._chunker = SemanticChunker(embedder=embedder, threshold=chunk_threshold)
        self._retriever = HybridRetriever(embedder=embedder)

    def answer(
        self,
        *,
        user_message: str,
        knowledge_text: str,
        llm_call: Callable[[str, str], str],
        top_k: int = 5,
        chunk_strategy: str = "semantic",
    ) -> dict[str, Any]:
        """
        1) 切分 knowledge_text
        2) 混合检索
        3) 拼 prompt → LLM
        4) 解析引用

        返回：{"answer": str, "citations": [...], "chunks": [...], "raw": str}
        """
        chunks: list[Chunk]
        if chunk_strategy == "semantic" and self._embedder is not None:
            chunks = self._chunker.split_by_semantic(knowledge_text)
        else:
            chunks = self._chunker.split_by_fixed(knowledge_text)

        retrieved_chunks: list[RetrievedChunk] = [
            RetrievedChunk(
                text=c.text,
                score=0.0,
                chunk_index=c.chunk_index,
                char_start=c.char_start,
                char_end=c.char_end,
                metadata=c.metadata,
            )
            for c in chunks
        ]
        self._retriever.index(retrieved_chunks)
        top = self._retriever.retrieve(user_message)
        if not top:
            return {
                "answer": llm_call(user_message, ""),
                "citations": [],
                "chunks": [],
                "raw": "",
            }

        tracker = CitationTracker(retrieved_chunks=top)
        cite_prompt = tracker.format_for_prompt()
        llm_output = llm_call(user_message, cite_prompt)
        clean_answer, citations = tracker.attach_citations(llm_output)

        return {
            "answer": clean_answer,
            "citations": [
                {
                    "index": c.index,
                    "text": c.text,
                    "source": c.source,
                    "chunk_index": c.chunk_index,
                    "char_range": list(c.char_range),
                }
                for c in citations
            ],
            "chunks": [
                {"chunk_index": c.chunk_index, "text": c.text, "score": c.score} for c in top
            ],
            "raw": llm_output,
        }


def get_default_embedder() -> Callable[[str], list[float]] | None:
    """
    默认 embedder：尝试用 app.infrastructure.ai 提供的 embedding。
    返回 None 时调用方需自带 embedder。
    """
    try:
        from app.infrastructure.llm import get_default_embedding_service  # type: ignore

        svc = get_default_embedding_service()
        return lambda text: svc.embed(text)
    except RECOVERABLE_ERRORS as e:
        logger.debug("默认 embedder 不可用: %s", e)
        return None


def is_rag_enabled() -> bool:
    """环境变量开关。"""
    return str(os.environ.get("XCAGI_RAG_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
