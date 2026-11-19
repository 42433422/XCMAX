"""Hybrid retriever: vector KNN + BM25 keyword search with RRF fusion.

When ``MODSTORE_RAG_RETRIEVAL_MODE=hybrid``, the ``retrieve()`` function in
``rag_service`` delegates to this module to combine dense-vector similarity
with sparse BM25 ranking via Reciprocal Rank Fusion (RRF).

BM25 is powered by ``bm25s``; if unavailable the
retriever gracefully degrades to vector-only search.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from dataclasses import replace
from typing import TYPE_CHECKING, List, Optional, Protocol, SupportsFloat

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.rag_service import RetrievedChunk

logger = logging.getLogger(__name__)

_RRF_K = int(os.environ.get("MODSTORE_RAG_RRF_K", "60"))


class _BM25Index(Protocol):
    def index(self, corpus: list[list[str]], *, show_progress: bool) -> None: ...

    def get_scores(self, query_tokens: list[str]) -> Iterable[SupportsFloat]: ...


class _BM25Module(Protocol):
    def BM25(self, *, method: str) -> _BM25Index: ...


def _load_bm25s() -> _BM25Module:
    # BM25S has no typing metadata; retain its optional static runtime import.
    if TYPE_CHECKING:
        module: _BM25Module
    else:
        import bm25s as module
    return module


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + CJK character tokenizer."""
    tokens: List[str] = []
    for part in re.split(r"\s+", text):
        if not part:
            continue
        buf = ""
        for ch in part:
            if "\u4e00" <= ch <= "\u9fff":
                if buf:
                    tokens.append(buf.lower())
                    buf = ""
                tokens.append(ch)
            else:
                buf += ch
        if buf:
            tokens.append(buf.lower())
    return tokens


def _bm25_available() -> bool:
    try:
        _load_bm25s()

        return True
    except ImportError:
        return False


class HybridRetriever:
    """Combine vector and BM25 results using Reciprocal Rank Fusion."""

    def __init__(self, rrf_k: int = _RRF_K):
        self.rrf_k = rrf_k

    def fuse(
        self,
        vector_results: List[RetrievedChunk],
        query: str,
        corpus: Optional[List[RetrievedChunk] | List[str]] = None,
        *,
        bm25_top_k: int = 10,
        final_top_k: int = 6,
    ) -> List[RetrievedChunk]:
        """Fuse independent candidates, retaining metadata for keyword-only hits.

        A full chunk corpus allows new sparse hits. Legacy text-only corpora
        remain supported for reranking the supplied vector results. Hybrid
        result scores are RRF scores, not distances or raw BM25 scores.
        """
        if not corpus or not _bm25_available():
            return vector_results[:final_top_k]

        try:
            return self._fuse_with_bm25(vector_results, query, corpus, bm25_top_k, final_top_k)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("HybridRetriever: BM25 fusion failed, using vector only: %s", exc)
            return vector_results[:final_top_k]

    def _fuse_with_bm25(
        self,
        vector_results: List[RetrievedChunk],
        query: str,
        corpus: List[RetrievedChunk] | List[str],
        bm25_top_k: int,
        final_top_k: int,
    ) -> List[RetrievedChunk]:
        bm25s = _load_bm25s()

        by_text = {chunk.content: chunk for chunk in vector_results}
        documents: List[RetrievedChunk] = []
        for item in corpus:
            chunk = item if isinstance(item, RetrievedChunk) else by_text.get(item)
            if chunk is not None:
                documents.append(chunk)
        tokenized_corpus = [_tokenize(chunk.content) for chunk in documents]
        tokenized_query = _tokenize(query)
        if not any(tokenized_corpus) or not tokenized_query:
            return vector_results[:final_top_k]
        bm25 = bm25s.BM25(method="lucene")
        bm25.index(tokenized_corpus, show_progress=False)
        bm25_scores = [float(score) for score in bm25.get_scores(tokenized_query)]
        bm25_ranked = sorted(
            (i for i, score in enumerate(bm25_scores) if score > 0),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )[:bm25_top_k]

        records = {(chunk.collection_id, chunk.chunk_id): chunk for chunk in documents}
        records.update({(chunk.collection_id, chunk.chunk_id): chunk for chunk in vector_results})
        rrf_scores: dict[tuple[int, str], float] = {}
        for ranking in (vector_results, [documents[i] for i in bm25_ranked]):
            keys = dict.fromkeys((chunk.collection_id, chunk.chunk_id) for chunk in ranking)
            for rank, key in enumerate(keys):
                rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (self.rrf_k + rank + 1)
        return [
            replace(records[key], score=rrf_scores[key])
            for key in sorted(rrf_scores, key=lambda key: -rrf_scores[key])[:final_top_k]
        ]


def get_hybrid_retriever() -> HybridRetriever:
    return HybridRetriever()
