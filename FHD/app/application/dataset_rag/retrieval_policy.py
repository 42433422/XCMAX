"""Pure tenant/version filters, lexical reranking, and fallback answers."""

from __future__ import annotations

import os
import re
from typing import Any

from app.application.dataset_rag.models import _clean_key
from app.infrastructure.rag import RetrievedChunk
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _filter_chunks(
    chunks: list[RetrievedChunk],
    *,
    tenant_id: str,
    version: str | int,
    metadata_filter: dict[str, Any],
) -> list[RetrievedChunk]:
    selected = list(chunks)
    tenant_key = _clean_key(str(tenant_id or ""), default="") if tenant_id else ""
    if tenant_key:
        selected = [
            chunk
            for chunk in selected
            if str((chunk.metadata or {}).get("tenant_id") or "") == tenant_key
        ]
    if metadata_filter:
        selected = [chunk for chunk in selected if _metadata_matches(chunk, metadata_filter)]
    version_text = str(version or "").strip()
    if not version_text:
        return selected
    if version_text.lower() == "latest":
        latest_by_scope: dict[tuple[str, str], int] = {}
        for chunk in selected:
            metadata = chunk.metadata or {}
            scope = (
                str(metadata.get("tenant_id") or ""),
                str(metadata.get("source") or chunk.source or ""),
            )
            latest_by_scope[scope] = max(
                latest_by_scope.get(scope, 0), int(metadata.get("document_version") or 1)
            )
        return [
            chunk
            for chunk in selected
            if int((chunk.metadata or {}).get("document_version") or 1)
            == latest_by_scope.get(
                (
                    str((chunk.metadata or {}).get("tenant_id") or ""),
                    str((chunk.metadata or {}).get("source") or chunk.source or ""),
                ),
                1,
            )
        ]
    normalized = version_text[1:] if version_text.lower().startswith("v") else version_text
    return [
        chunk
        for chunk in selected
        if str((chunk.metadata or {}).get("document_version") or "") == normalized
        or str((chunk.metadata or {}).get("version_label") or "") == version_text
    ]


def _metadata_matches(chunk: RetrievedChunk, metadata_filter: dict[str, Any]) -> bool:
    metadata = dict(chunk.metadata or {})
    metadata.setdefault("source", chunk.source)
    for key, expected in metadata_filter.items():
        actual = metadata.get(str(key))
        if isinstance(expected, list):
            expected_values = {str(item) for item in expected}
            if str(actual) not in expected_values:
                return False
        elif isinstance(expected, dict):
            if not isinstance(actual, dict):
                return False
            for nested_key, nested_expected in expected.items():
                if str(actual.get(str(nested_key))) != str(nested_expected):
                    return False
        elif str(actual) != str(expected):
            return False
    return True


def _rerank_chunks(query: str, chunks: list[RetrievedChunk], *, top_k: int) -> list[RetrievedChunk]:
    query_terms = set(_tokenize_for_rerank(query))
    if not query_terms:
        return chunks[:top_k]
    reranked: list[RetrievedChunk] = []
    for chunk in chunks:
        chunk_terms = set(_tokenize_for_rerank(chunk.text))
        overlap = len(query_terms & chunk_terms)
        exact_bonus = (
            1.0 if query.strip().lower() and query.strip().lower() in chunk.text.lower() else 0.0
        )
        boost = overlap / max(1, len(query_terms)) + exact_bonus
        reranked.append(
            RetrievedChunk(
                text=chunk.text,
                score=float(chunk.score) + boost,
                source=f"{chunk.source}+rerank" if "rerank" not in chunk.source else chunk.source,
                chunk_index=chunk.chunk_index,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                metadata=chunk.metadata,
                source_url=chunk.source_url,
                page=chunk.page,
            )
        )
    return sorted(reranked, key=lambda item: item.score, reverse=True)[:top_k]


def _semantic_rerank_chunks(
    query: str, chunks: list[RetrievedChunk], *, top_k: int, auto: bool = False
) -> list[RetrievedChunk] | None:
    """用 cross-encoder 精排；未启用或模型不可用时返回 None，由调用方回退词法。"""
    if not chunks:
        return None
    try:
        from app.infrastructure.rag.reranker import get_default_reranker

        reranker = get_default_reranker(auto=True) if auto else get_default_reranker()
        if reranker is None:
            return None
        scores = reranker.score(query, [chunk.text for chunk in chunks])
    except RECOVERABLE_ERRORS:
        return None
    if len(scores) != len(chunks):
        return None
    reranked = [
        RetrievedChunk(
            text=chunk.text,
            score=float(score),
            source=chunk.source if "rerank" in chunk.source else f"{chunk.source}+rerank",
            chunk_index=chunk.chunk_index,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            metadata=chunk.metadata,
            source_url=chunk.source_url,
            page=chunk.page,
        )
        for chunk, score in zip(chunks, scores, strict=True)
    ]
    return sorted(reranked, key=lambda item: item.score, reverse=True)[:top_k]


def _tokenize_for_rerank(text: str) -> list[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [part for part in cleaned.split() if part]


# 问题里常见的疑问/虚词二元组，出现在任何文档里都不代表「命中证据」。
_QUERY_TERM_STOPWORDS = frozenset(
    {
        "怎么",
        "什么",
        "如何",
        "可以",
        "需要",
        "多少",
        "哪些",
        "是否",
        "一下",
        "我们",
        "你们",
        "这个",
        "那个",
        "还是",
        "或者",
        "以及",
        "请问",
        "帮我",
        "推荐",
    }
)
_DEFAULT_MIN_RELEVANCE = 0.1


def _query_terms(text: str) -> set[str]:
    """中文按二元组、英文数字按词的查询词集合（去掉疑问/虚词）。"""
    terms: set[str] = set()
    for part in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", str(text or "").lower()):
        if re.match(r"[\u4e00-\u9fff]", part):
            if len(part) == 1:
                continue
            terms.update(part[index : index + 2] for index in range(len(part) - 1))
        else:
            terms.add(part)
    return terms - _QUERY_TERM_STOPWORDS


def _query_coverage(query: str, text: str) -> float:
    """查询词在候选文本中的覆盖率；无可用查询词时按 1.0 处理。"""
    query_terms = _query_terms(query)
    if not query_terms:
        return 1.0
    return len(query_terms & _query_terms(text)) / len(query_terms)


def evidence_grounding(query: str, chunks: list[RetrievedChunk]) -> float:
    """取前若干候选里最高的查询覆盖率，作为「有证据」的保守判据。"""
    candidates = chunks[:5]
    return max((_query_coverage(query, chunk.text) for chunk in candidates), default=0.0)


def default_min_relevance() -> float:
    raw = os.environ.get("XCAGI_KB_MIN_RELEVANCE", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_MIN_RELEVANCE
    return max(0.0, min(value, 1.0))


def resolve_min_relevance(requested: float | None) -> float:
    if requested is None or requested <= 0:
        return default_min_relevance()
    return max(0.0, min(float(requested), 1.0))


def _deterministic_answer(query: str, chunks: list[RetrievedChunk]) -> str:
    """Customer-facing fallback when no LLM is wired (知识库 / 智能对话 tone)."""
    if not chunks:
        return ""
    excerpt = chunks[0].text.strip().replace("\n", " ")
    if len(excerpt) > 320:
        excerpt = excerpt[:317].rstrip() + "..."
    # Align with Chinese product UX (智能对话 / Persy 知识库); keep [1] citation marker.
    q = str(query or "").strip()
    prefix = f"根据知识库资料，关于「{q}」：" if q else "根据知识库资料："
    return f"{prefix}{excerpt} [1]"
