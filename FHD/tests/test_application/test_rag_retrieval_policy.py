"""RAG 检索策略：top-K、相关性阈值与提示词预算。"""

from __future__ import annotations

import pytest

from app.application.user_memory_vector_app_service import UserMemoryRagApplicationService
from app.infrastructure.memory.mem0_backend import format_recalled_memories
from app.infrastructure.rag.citation_tracker import CitationTracker
from app.infrastructure.rag.hybrid_retriever import HybridRetriever, RetrievedChunk
from app.infrastructure.rag.rag_service import RagService


def _embedder(text: str) -> list[float]:
    return [1.0, 0.0] if "alpha" in text else [0.0, 1.0]


def _chunk(text: str, index: int, embedding: list[float]) -> RetrievedChunk:
    return RetrievedChunk(
        text=text, score=0.0, chunk_index=index, metadata={"_embedding": embedding}
    )


def test_hybrid_retriever_respects_top_k_and_vector_threshold() -> None:
    retriever = HybridRetriever(embedder=_embedder)
    retriever.index(
        [
            _chunk("alpha 订单", 0, [1.0, 0.0]),
            _chunk("beta 客户", 1, [0.3, 0.953939]),
        ]
    )

    without_floor = retriever.retrieve("alpha", top_k=5, min_vector_score=0.0)
    assert {item.chunk_index for item in without_floor} == {0, 1}

    filtered = retriever.retrieve("alpha", top_k=5, min_vector_score=0.5)
    assert [item.chunk_index for item in filtered] == [0]


def test_hybrid_retriever_limits_result_count() -> None:
    retriever = HybridRetriever(embedder=_embedder)
    retriever.index([_chunk(f"alpha {index}", index, [1.0, 0.0]) for index in range(5)])
    assert len(retriever.retrieve("alpha", top_k=2)) == 2


def test_citation_prompt_stays_within_char_budget() -> None:
    chunks = [
        RetrievedChunk(text="很长的资料" * 100, score=1.0, chunk_index=index) for index in range(6)
    ]
    prompt = CitationTracker(chunks).format_for_prompt(max_chars=200)
    assert len(prompt) <= 200
    assert prompt.count("[") >= 1


def test_rag_service_honours_top_k() -> None:
    service = RagService(embedder=None, prompt_char_budget=1200)
    result = service.answer(
        user_message="alpha",
        knowledge_text="alpha 第一段。\n\nbeta 第二段。\n\ngamma 第三段。",
        llm_call=lambda message, context: "答复 [1]",
        top_k=1,
    )
    assert len(result["chunks"]) == 1
    assert result["answer"] == "答复"


def test_user_memory_prompt_respects_budget() -> None:
    hits = [
        {
            "content": "记忆内容" * 200,
            "score": 0.9,
            "metadata": {"source": "chat", "last_used": "2026-01-01"},
        }
        for _ in range(5)
    ]
    service = UserMemoryRagApplicationService.__new__(UserMemoryRagApplicationService)
    service._recall_validator = lambda hits: (
        hits
    )  # Isolate formatting budgets from authority checks.
    prompt = service.format_for_prompt("u1", "query", hits, max_hits=5, max_chars=300)
    assert len(prompt) <= 300


@pytest.mark.parametrize("budget", [0, 1, 55, 140, 200])
@pytest.mark.parametrize("has_hits", [False, True])
def test_prompt_budgets_include_newlines_headers_and_footer(budget, has_hits):
    hits = [{"content": "alpha" * 40, "score": 0.9}] if has_hits else []
    service = UserMemoryRagApplicationService.__new__(UserMemoryRagApplicationService)
    service._recall_validator = lambda hits: (
        hits
    )  # Isolate formatting budgets from authority checks.
    prompts = (
        format_recalled_memories(hits, max_chars=budget),
        service.format_for_prompt("u1", "query", hits, max_chars=budget),
        CitationTracker([_chunk(hit["content"], 0, [1.0, 0.0]) for hit in hits]).format_for_prompt(
            max_chars=budget
        ),
    )
    assert all(len(prompt) <= budget for prompt in prompts)
