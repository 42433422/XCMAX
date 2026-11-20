"""Ground enterprise support answers in the published product knowledge dataset."""

from __future__ import annotations

from functools import cache
from urllib.parse import urlsplit

from app.infrastructure.rag.citation_tracker import CitationTracker
from app.infrastructure.rag.hybrid_retriever import HybridRetriever, RetrievedChunk

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


def is_product_url(url: str) -> bool:
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


def retrieve_public_product_guide(query: str) -> list[RetrievedChunk]:
    return _public_guide_retriever().retrieve(query)


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
