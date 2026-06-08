"""混合检索（向量 + BM25 + RRF 融合）。

不依赖 rank_bm25 库（环境可能没有），用纯 Python 实现 BM25，保证 0 依赖。
"""

from __future__ import annotations

from app.utils.operational_errors import OPERATIONAL_ERRORS
import logging
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """检索结果。"""

    text: str
    score: float
    source: str = "hybrid"  # vector / bm25 / hybrid
    chunk_index: int = 0
    char_start: int = 0
    char_end: int = 0
    metadata: dict[str, Any] | None = None
    source_url: str = ""
    page: int | None = None


class BM25:
    """
    轻量 BM25（无第三方依赖）。

    score(q, d) = Σ_{t∈q∩d} IDF(t) · (tf(t,d)·(k1+1)) / (tf(t,d) + k1·(1-b+b·|d|/avgdl))
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: list[list[str]] = []
        self._doc_lens: list[int] = []
        self._avgdl: float = 0.0
        self._df: Counter = Counter()
        self._idf: dict[str, float] = {}
        self._n_docs: int = 0

    def fit(self, docs: list[str]) -> None:
        tokenized = [self._tokenize(d) for d in docs]
        self._docs = tokenized
        self._doc_lens = [len(t) for t in tokenized]
        self._n_docs = len(tokenized)
        self._avgdl = (sum(self._doc_lens) / self._n_docs) if self._n_docs else 0.0
        self._df = Counter()
        for toks in tokenized:
            for term in set(toks):
                self._df[term] += 1
        self._idf = {
            t: math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1.0) for t, df in self._df.items()
        }

    def score(self, query: str) -> list[float]:
        q_tokens = self._tokenize(query)
        scores: list[float] = []
        for i, doc in enumerate(self._docs):
            s = 0.0
            dl = self._doc_lens[i] or 1
            tf = Counter(doc)
            for t in q_tokens:
                if t not in tf:
                    continue
                idf = self._idf.get(t, 0.0)
                num = tf[t] * (self.k1 + 1.0)
                den = tf[t] + self.k1 * (1.0 - self.b + self.b * dl / (self._avgdl or 1.0))
                s += idf * (num / (den or 1.0))
            scores.append(s)
        return scores

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        if not text:
            return []
        # 支持中英：英文按词、中文按字
        tokens: list[str] = []
        for part in re.split(r"([\u4e00-\u9fff])", text):
            if not part:
                continue
            if re.match(r"[\u4e00-\u9fff]", part):
                tokens.extend(list(part))
            else:
                tokens.extend(re.findall(r"[A-Za-z0-9]+", part.lower()))
        return [t for t in tokens if t]


class HybridRetriever:
    """
    向量 + BM25 + RRF 融合检索器。

    流程：
      1) 向量检索：embedder + cosine，取 top_k_v
      2) 关键词检索：BM25 取 top_k_b
      3) RRF 融合：score(d) = Σ 1 / (k + rank_i(d))
      4) 取 top_k
    """

    DEFAULT_K = 60  # RRF 常数
    DEFAULT_TOP_K_VECTOR = 10
    DEFAULT_TOP_K_BM25 = 10
    DEFAULT_TOP_K = 5

    def __init__(
        self,
        embedder: Callable[[str], list[float]] | None = None,
        *,
        k: int = DEFAULT_K,
        top_k_vector: int = DEFAULT_TOP_K_VECTOR,
        top_k_bm25: int = DEFAULT_TOP_K_BM25,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self._embedder = embedder
        self._k = k
        self._top_k_vector = top_k_vector
        self._top_k_bm25 = top_k_bm25
        self._top_k = top_k
        self._chunks: list[RetrievedChunk] = []
        self._chunk_texts: list[str] = []
        self._bm25 = BM25()
        self._embeddings: list[list[float]] = []

    def index(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = list(chunks)
        self._chunk_texts = [c.text for c in chunks]
        self._bm25.fit(self._chunk_texts)
        if self._embedder is not None:
            try:
                self._embeddings = [self._embedder(c.text) for c in chunks]
            except OPERATIONAL_ERRORS as e:
                logger.warning("embedder 计算失败，混合检索降级为 BM25: %s", e)
                self._embeddings = []
        else:
            self._embeddings = []

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        if not self._chunks:
            return []

        # 1) BM25
        bm25_scores = self._bm25.score(query)
        bm25_ranked = sorted(
            range(len(self._chunks)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )[: self._top_k_bm25]

        # 2) Vector
        vector_ranked: list[int] = []
        if self._embedder is not None and self._embeddings:
            try:
                q_vec = self._embedder(query)
                sims = [self._cosine(q_vec, e) for e in self._embeddings]
                vector_ranked = sorted(
                    range(len(self._chunks)),
                    key=lambda i: sims[i],
                    reverse=True,
                )[: self._top_k_vector]
            except OPERATIONAL_ERRORS as e:
                logger.warning("向量检索失败: %s", e)

        # 3) RRF
        scores: dict[int, float] = {}
        for rank, idx in enumerate(vector_ranked):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (self._k + rank + 1)
        for rank, idx in enumerate(bm25_ranked):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (self._k + rank + 1)

        # 4) 取 top_k
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[: self._top_k]
        results: list[RetrievedChunk] = []
        for idx, score in ranked:
            c = self._chunks[idx]
            results.append(
                RetrievedChunk(
                    text=c.text,
                    score=float(score),
                    source="hybrid"
                    if (idx in vector_ranked and idx in bm25_ranked)
                    else ("vector" if idx in vector_ranked else "bm25"),
                    chunk_index=c.chunk_index,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    metadata=c.metadata,
                    source_url=c.source_url,
                    page=c.page,
                )
            )
        return results

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
