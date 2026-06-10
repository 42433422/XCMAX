"""Embedding interfaces for cross-project knowledge retrieval.

The :class:`Embedder` Protocol exposes a tiny method (``embed``) so
callers can plug in any vendor (OpenAI / Qwen DashScope / Cohere /
local sentence-transformers / a hash-based fallback for tests). The
default :class:`HashingEmbedder` produces deterministic vectors using
the Python stdlib only — perfect for unit tests and as a graceful
fallback when no vendor is configured.

Three reference implementations ship in tree:

- :class:`HashingEmbedder` — feature hashing (no deps). Fast,
  deterministic, surprisingly good for short briefs.
- :class:`OpenAIEmbedder` — wraps an OpenAI-compatible
  ``/v1/embeddings`` endpoint (Qwen / DeepSeek / Zhipu also expose
  this contract). Uses :class:`vibe_coding.nl.providers.OpenAICompatibleLLM`'s
  HTTP plumbing under the hood.
- :class:`SentenceTransformerEmbedder` — opt-in; uses the
  ``sentence-transformers`` package when installed.

Vectors are returned as ``list[float]``. Cosine similarity is the
expected scoring function — :func:`cosine_similarity` in
:mod:`knowledge_base` does that.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence, runtime_checkable

DEFAULT_DIM = 256


@runtime_checkable
class Embedder(Protocol):
    """Protocol every embedding backend must satisfy."""

    @property
    def dim(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


# ----------------------------------------------------- hashing fallback


class HashingEmbedder:
    """Hash-based embedding — deterministic, zero dependencies.

    Uses SHA-256 to hash each token then folds the bytes into a
    fixed-size float vector. Surprisingly effective for short briefs
    when paired with cosine similarity. Recommended as the **default**
    fallback so tests / offline runs always have a working embedder.
    """

    def __init__(self, dim: int = DEFAULT_DIM, *, normalise: bool = True) -> None:
        if dim < 8:
            raise ValueError("dim must be ≥ 8")
        self._dim = int(dim)
        self.normalise = bool(normalise)

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text or "") for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for token in _tokenise(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for i in range(self._dim):
                # 8-bit hash byte → signed contribution in [-1, 1].
                byte = digest[i % len(digest)]
                vec[i] += (byte - 128) / 128.0
        if self.normalise:
            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 0:
                vec = [x / norm for x in vec]
        return vec


def _tokenise(text: str) -> list[str]:
    import re

    return re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]+", text.lower())


# ----------------------------------------------------- vendor-backed


@dataclass
class OpenAIEmbedder:
    """Wrap any OpenAI-compatible ``/v1/embeddings`` endpoint.

    Defaults work with the public OpenAI API; pass ``base_url`` for
    Qwen / DeepSeek / Zhipu (or a self-hosted Ollama / vLLM / LMStudio
    server). API keys come from the constructor or
    ``OPENAI_API_KEY`` / ``DASHSCOPE_API_KEY`` / ``ZHIPUAI_API_KEY``
    env vars in that priority order.

    Falls back to :class:`HashingEmbedder` when the embedding call
    fails so a transient outage doesn't break a memory write.
    """

    api_key: str = ""
    model: str = "text-embedding-3-small"
    base_url: str = "https://api.openai.com/v1"
    timeout_s: float = 30.0
    dim_override: int | None = None
    _fallback_dim: int = DEFAULT_DIM

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = (
                os.environ.get("OPENAI_API_KEY")
                or os.environ.get("DASHSCOPE_API_KEY")
                or os.environ.get("ZHIPUAI_API_KEY")
                or ""
            )
        self._fallback = HashingEmbedder(self._fallback_dim)

    @property
    def dim(self) -> int:
        return int(self.dim_override or self._fallback_dim)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.api_key:
            return self._fallback.embed(texts)
        try:
            return self._embed_remote(list(texts))
        except Exception:  # noqa: BLE001
            return self._fallback.embed(texts)

    def _embed_remote(self, texts: list[str]) -> list[list[float]]:
        url = self.base_url.rstrip("/") + "/embeddings"
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        data = payload.get("data") or []
        return [list(item.get("embedding") or []) for item in data]


# ----------------------------------------------------- sentence-transformers


class SentenceTransformerEmbedder:
    """Wrap a local ``sentence-transformers`` model.

    Lazily imports the library so it stays optional. Falls back to
    :class:`HashingEmbedder` when the import fails.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        *,
        fallback_dim: int = DEFAULT_DIM,
        device: str = "cpu",
    ) -> None:
        self.model_name = model_name
        self._device = device
        self._fallback = HashingEmbedder(fallback_dim)
        self._model = None

    @property
    def dim(self) -> int:
        try:
            self._ensure_model()
        except Exception:  # noqa: BLE001
            return self._fallback.dim
        if self._model is None:
            return self._fallback.dim
        try:
            return int(self._model.get_sentence_embedding_dimension())  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            return self._fallback.dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            self._ensure_model()
        except Exception:  # noqa: BLE001
            return self._fallback.embed(texts)
        if self._model is None:
            return self._fallback.embed(texts)
        try:
            vectors = self._model.encode(list(texts), convert_to_numpy=False)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            return self._fallback.embed(texts)
        return [list(map(float, v)) for v in vectors]

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError:
            self._model = None
            return
        self._model = SentenceTransformer(self.model_name, device=self._device)


# ----------------------------------------------------- helpers


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    a_list = list(a)
    b_list = list(b)
    if not a_list or not b_list:
        return 0.0
    n = min(len(a_list), len(b_list))
    a_list = a_list[:n]
    b_list = b_list[:n]
    dot = sum(x * y for x, y in zip(a_list, b_list))
    na = math.sqrt(sum(x * x for x in a_list))
    nb = math.sqrt(sum(x * x for x in b_list))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


__all__ = [
    "DEFAULT_DIM",
    "Embedder",
    "HashingEmbedder",
    "OpenAIEmbedder",
    "SentenceTransformerEmbedder",
    "cosine_similarity",
]
