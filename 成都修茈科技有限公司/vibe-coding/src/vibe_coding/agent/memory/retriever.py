"""Lightweight BM25-style retriever for exemplar search.

Zero extra dependencies: we compute TF-IDF with simple tokenisation
(split on word boundaries). ``rank_bm25`` is an optional upgrade for
production use — if present it replaces our built-in scorer transparently.
"""

from __future__ import annotations

import math
import re
from typing import Sequence

from .exemplars import Exemplar

_TOKENISE_RE = re.compile(r"[a-zA-Z\u4e00-\u9fff]+")


def _tokenise(text: str) -> list[str]:
    return _TOKENISE_RE.findall(text.lower())


class Retriever:
    """Retrieve top-K exemplars for a query string."""

    def __init__(
        self,
        exemplars: Sequence[Exemplar],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self._docs = list(exemplars)
        self._k1 = k1
        self._b = b
        self._index: list[list[str]] = []
        self._idf: dict[str, float] = {}
        self._avg_dl = 0.0
        if self._docs:
            self._build()

    def _build(self) -> None:
        tokenised = [_tokenise(e.search_text()) for e in self._docs]
        self._index = tokenised
        n = len(self._docs)
        df: dict[str, int] = {}
        for tokens in tokenised:
            for tok in set(tokens):
                df[tok] = df.get(tok, 0) + 1
        self._idf = {
            tok: math.log((n - f + 0.5) / (f + 0.5) + 1)
            for tok, f in df.items()
        }
        total = sum(len(t) for t in tokenised)
        self._avg_dl = total / max(n, 1)

    def search(self, query: str, k: int = 3) -> list[Exemplar]:
        if not self._docs:
            return []
        q_tokens = _tokenise(query)
        if not q_tokens:
            return self._docs[:k]
        try:
            from rank_bm25 import BM25Okapi  # type: ignore[import-not-found]
            bm25 = BM25Okapi(self._index)
            scores = bm25.get_scores(q_tokens)
            ranked = sorted(range(len(self._docs)), key=lambda i: -scores[i])
            return [self._docs[i] for i in ranked[:k]]
        except ImportError:
            pass
        scores_builtin = [self._bm25_score(q_tokens, idx) for idx in range(len(self._docs))]
        ranked = sorted(range(len(self._docs)), key=lambda i: -scores_builtin[i])
        return [self._docs[i] for i in ranked[:k]]

    def _bm25_score(self, query_tokens: list[str], doc_idx: int) -> float:
        doc = self._index[doc_idx]
        dl = len(doc)
        tf: dict[str, int] = {}
        for tok in doc:
            tf[tok] = tf.get(tok, 0) + 1
        score = 0.0
        for tok in query_tokens:
            if tok not in self._idf:
                continue
            f = tf.get(tok, 0)
            numerator = f * (self._k1 + 1)
            denom = f + self._k1 * (1 - self._b + self._b * dl / max(self._avg_dl, 1))
            score += self._idf[tok] * numerator / max(denom, 1e-9)
        return score


__all__ = ["Retriever"]
