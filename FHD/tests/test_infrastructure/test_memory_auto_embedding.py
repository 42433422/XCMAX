"""Default embedding selects a stable provisioned vector space."""

from unittest.mock import patch

from app.infrastructure.llm.embedding_service import EmbeddingService


def test_auto_embedding_prefers_provisioned_model(monkeypatch):
    monkeypatch.delenv("FHD_EMBEDDING_MODE", raising=False)
    monkeypatch.delenv("XCAGI_RAG_ENABLED", raising=False)
    model = object()
    with patch(
        "app.infrastructure.llm.embedding_service._cached_fastembed",
        return_value=(model, 384),
    ):
        service = EmbeddingService()
    assert service.mode == "fastembed"
    assert service.dim() == 384
    assert service.is_semantic()


def test_auto_embedding_fallback_has_stable_hash_identity(monkeypatch):
    monkeypatch.setenv("FHD_EMBEDDING_MODE", "auto")
    monkeypatch.delenv("XCAGI_RAG_ENABLED", raising=False)
    with patch(
        "app.infrastructure.llm.embedding_service._cached_fastembed", return_value=None
    ):
        service = EmbeddingService()
    assert service.mode == "hash"
    assert len(service.embed_one("测试")) == 192
    assert service.embedding_fingerprint == EmbeddingService("hash").embedding_fingerprint


def test_disabled_never_loads_optional_model(monkeypatch):
    monkeypatch.setenv("XCAGI_RAG_ENABLED", "0")
    monkeypatch.delenv("FHD_EMBEDDING_MODE", raising=False)
    with patch("app.infrastructure.llm.embedding_service._cached_fastembed") as load:
        service = EmbeddingService()
    load.assert_not_called()
    assert not service.is_available()
