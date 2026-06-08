"""Hybrid retriever: vector KNN + BM25 keyword search with RRF fusion.

When ``MODSTORE_RAG_RETRIEVAL_MODE=hybrid``, the ``retrieve()`` function in
``rag_service`` delegates to this module to combine dense-vector similarity
with sparse BM25 ranking via Reciprocal Rank Fusion (RRF).

BM25 is powered by the lightweight ``rank_bm25`` library; if unavailable the
retriever gracefully degrades to vector-only search.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence

from modstore_server.rag_service import RetrievedChunk

logger = logging.getLogger(__name__)

_RRF_K = int(os.environ.get("MODSTORE_RAG_RRF_K", "60"))


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
        from rank_bm25 import BM25Okapi  # noqa: F401

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
        corpus: Optional[List[str]] = None,
        *,
        bm25_top_k: int = 10,
        final_top_k: int = 6,
    ) -> List[RetrievedChunk]:
        """Fuse vector results with BM25 ranking of *corpus*.

        If *corpus* is ``None`` or BM25 is unavailable, returns vector results
        unchanged (graceful degradation).

        Parameters
        ----------
        vector_results:
            Results from dense-vector KNN search, already sorted by distance.
        query:
            The original user query string.
        corpus:
            Optional list of text chunks to build the BM25 index from.
            When provided, BM25 ranking is computed and fused with vector
            results.  When ``None``, only vector results are returned.
        bm25_top_k:
            Number of BM25 results to consider.
        final_top_k:
            Maximum number of results after fusion.
        """
        if not vector_results:
            return []

        if not corpus or not _bm25_available():
            return vector_results[:final_top_k]

        try:
            return self._fuse_with_bm25(vector_results, query, corpus, bm25_top_k, final_top_k)
        except Exception as exc:
            logger.warning("HybridRetriever: BM25 fusion failed, using vector only: %s", exc)
            return vector_results[:final_top_k]

    def _fuse_with_bm25(
        self,
        vector_results: List[RetrievedChunk],
        query: str,
        corpus: List[str],
        bm25_top_k: int,
        final_top_k: int,
    ) -> List[RetrievedChunk]:
        from rank_bm25 import BM25Okapi

        tokenized_corpus = [_tokenize(doc) for doc in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = _tokenize(query)
        bm25_scores = bm25.get_scores(tokenized_query)

        bm25_ranked = sorted(
            range(len(bm25_scores)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )[:bm25_top_k]

        chunk_id_to_chunk: Dict[str, RetrievedChunk] = {}
        for c in vector_results:
            chunk_id_to_chunk[c.chunk_id] = c

        vector_rank: Dict[str, int] = {}
        for rank, c in enumerate(vector_results):
            vector_rank[c.chunk_id] = rank

        bm25_rank: Dict[int, int] = {}
        for rank, idx in enumerate(bm25_ranked):
            bm25_rank[idx] = rank

        rrf_scores: Dict[str, float] = {}

        for c in vector_results:
            v_rank = vector_rank.get(c.chunk_id, 999)
            rrf_scores[c.chunk_id] = 1.0 / (self.rrf_k + v_rank + 1)

        corpus_chunk_map: Dict[int, str] = {}
        for idx in bm25_ranked:
            if idx < len(corpus):
                content = corpus[idx]
                for c in vector_results:
                    if c.content == content:
                        corpus_chunk_map[idx] = c.chunk_id
                        break

        for idx, rank in bm25_rank.items():
            cid = corpus_chunk_map.get(idx)
            if cid:
                existing = rrf_scores.get(cid, 0.0)
                rrf_scores[cid] = existing + 1.0 / (self.rrf_k + rank + 1)
            else:
                pseudo_id = f"bm25_{idx}"
                rrf_scores[pseudo_id] = 1.0 / (self.rrf_k + rank + 1)

        sorted_ids = sorted(rrf_scores, key=lambda k: -rrf_scores[k])

        result: List[RetrievedChunk] = []
        for cid in sorted_ids:
            if cid in chunk_id_to_chunk:
                result.append(chunk_id_to_chunk[cid])
            if len(result) >= final_top_k:
                break

        return result


def get_hybrid_retriever() -> HybridRetriever:
    return HybridRetriever()
