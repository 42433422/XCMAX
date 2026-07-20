"""LLM infrastructure (Phase 5 facade over app.legacy.llm_config)."""

from __future__ import annotations

from app.infrastructure.llm.embedding_service import (
    EmbeddingMode,
    EmbeddingService,
    get_default_embedding_service,
)

__all__ = [
    "EmbeddingMode",
    "EmbeddingService",
    "get_default_embedding_service",
]
