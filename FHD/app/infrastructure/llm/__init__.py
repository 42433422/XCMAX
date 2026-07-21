"""LLM infrastructure (Phase 5 facade over app.legacy.llm_config)."""

from .embedding_service import EmbeddingMode, EmbeddingService, get_default_embedding_service

__all__ = [
    "EmbeddingMode",
    "EmbeddingService",
    "get_default_embedding_service",
]
