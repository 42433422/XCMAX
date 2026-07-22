"""LLM infrastructure (Phase 5 facade over app.legacy.llm_config)."""

from __future__ import annotations


def __getattr__(name):
    if name in {"EmbeddingMode", "EmbeddingService", "get_default_embedding_service"}:
        from .embedding_service import (
            EmbeddingMode as _EmbeddingMode,
            EmbeddingService as _EmbeddingService,
            get_default_embedding_service as _get_default_embedding_service,
        )

        if name == "EmbeddingMode":
            return _EmbeddingMode
        if name == "EmbeddingService":
            return _EmbeddingService
        return _get_default_embedding_service

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return [
        "EmbeddingMode",
        "EmbeddingService",
        "get_default_embedding_service",
    ]


__all__ = [
    "EmbeddingMode",
    "EmbeddingService",
    "get_default_embedding_service",
]
