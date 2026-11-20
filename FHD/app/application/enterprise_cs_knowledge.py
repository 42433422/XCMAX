"""Ground enterprise support answers in the published product knowledge dataset."""

from __future__ import annotations

import asyncio
import logging
import os
from functools import cache
from urllib.parse import urlsplit

from app.application.dataset_rag.models import _dict_to_retrieved_chunk
from app.application.dataset_rag.retrieval_policy import evidence_grounding, resolve_min_relevance
from app.infrastructure.rag.citation_tracker import CitationTracker
from app.infrastructure.rag.hybrid_retriever import HybridRetriever, RetrievedChunk
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_PRODUCT_HOSTS = {"xiu-ci.com", "www.xiu-ci.com", "xcagi.com", "www.xcagi.com"}
# Stable instructions from download.html and the product section of index.html.
# Release values and availability stay on the official pages.
_PUBLIC_PRODUCT_GUIDE = (
    (
        "https://xiu-ci.com/download",
        "下载安装 XCAGI：在官方下载页查看当前版本和平台状态，选择对应安装包。"
        "下载后按系统提示安装，在安装前核对页面显示的 SHA-256。",
    ),
    (
        "https://xiu-ci.com/index.html#product",
        "XCAGI 首次启动：按所选桌面平台的安装说明完成初始化，再按照企业的业务场景安装所需的行业 Mod。",
    ),
    (
        "https://xiu-ci.com/index.html#product",
        "使用 XCAGI 交办任务：在对话中描述想处理的工作，查看任务执行过程和输出，然后复核结果。",
    ),
)


@cache
def _public_guide_retriever() -> HybridRetriever:
    retriever = HybridRetriever(mode="keyword", top_k=3)
    retriever.index(
        [RetrievedChunk(text=text, score=0, source_url=url) for url, text in _PUBLIC_PRODUCT_GUIDE]
    )
    return retriever


def _grounded(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    threshold = resolve_min_relevance(None)
    return [chunk for chunk in chunks if evidence_grounding(query, [chunk]) >= threshold]


def _is_product_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        len(url) <= 512
        and parsed.scheme == "https"
        and parsed.netloc.lower() in _PRODUCT_HOSTS
        and not parsed.query
        and all(char.isprintable() and not char.isspace() and char not in '[]()<>"' for char in url)
        and "\\" not in url
    )


async def retrieve_product_knowledge(query: str) -> CitationTracker:
    """Use a dedicated read-only key; never fall through to a tenant's private data."""
    query = query.strip()[:2000]
    if not query:
        return CitationTracker([])
    key = os.getenv("XCAGI_ENTERPRISE_CS_KB_KEY", "").strip()
    evidence = await asyncio.to_thread(_published_dataset, key, query) if key else None
    return evidence or CitationTracker(_grounded(query, _public_guide_retriever().retrieve(query)))


def _published_dataset(key: str, query: str) -> CitationTracker | None:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    try:
        result = get_dataset_rag_app_service().public_query(
            api_key=key,
            query=query,
            top_k=3,
            metadata_filter={"visibility": "public"},
        )
    except RECOVERABLE_ERRORS:
        logger.warning("Enterprise CS product knowledge unavailable")
        return None
    if result.get("success") is not True or result.get("answer_grounded") is not True:
        return None

    chunks = [
        _dict_to_retrieved_chunk(row)
        for row in result["chunks"]
        if row.get("text")
        and (row.get("metadata") or {}).get("visibility") == "public"
        and _is_product_url(str(row.get("source_url") or ""))
    ]
    grounded = _grounded(query, chunks)
    return CitationTracker(grounded) if grounded else None


def cite_product_reply(reply: str, evidence: CitationTracker) -> str:
    """Append only sources independently resolved from retrieved citation indexes."""
    if "://" in reply or "www." in reply.lower():
        return ""
    clean, citations = evidence.attach_citations(reply)
    indexes = set(CitationTracker.CITE_PATTERN.findall(reply))
    if not clean or not citations or {str(citation.index) for citation in citations} != indexes:
        return ""
    references = dict.fromkeys(citation.source_url for citation in citations)
    answer = f"{clean}\n\n产品资料\n" + "\n".join(references)
    return answer if len(answer) <= 4000 else ""
