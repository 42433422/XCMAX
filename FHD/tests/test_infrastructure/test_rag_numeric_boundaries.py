"""Numeric contracts at the untyped BM25S and embedding-provider boundaries."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.infrastructure.rag.hybrid_retriever import BM25
from app.infrastructure.rag.rag_service import get_default_embedder


def test_real_bm25_returns_float_list_in_document_order():
    retriever = BM25()
    retriever.fit(["blue blue paint", "red paint"])
    scores = retriever.score("blue")
    assert type(scores) is list
    assert all(type(value) is float for value in scores)
    assert len(scores) == 2
    assert scores[0] > scores[1] == 0.0
    assert retriever.score("") == [0.0, 0.0]
    retriever.fit([])
    assert retriever.score("blue") == []


def test_default_embedder_normalizes_vector_without_batch_call(monkeypatch):
    from app.infrastructure import llm

    query = Mock(return_value=(1, 0.5))
    service = SimpleNamespace(embed_query=query)
    monkeypatch.setattr(llm, "get_default_embedding_service", lambda: service)
    embed = get_default_embedder()
    assert embed is not None
    vector = embed("synthetic query")
    assert vector == [1.0, 0.5]
    assert all(type(value) is float for value in vector)
    query.assert_called_once_with("synthetic query")
    query.return_value = []
    assert embed("empty") == []


@pytest.mark.parametrize("error_type", [OSError, ValueError])
def test_default_embedder_preserves_provider_exception(monkeypatch, error_type):
    from app.infrastructure import llm

    error = error_type("synthetic provider failure")
    service = SimpleNamespace(embed_query=Mock(side_effect=error))
    monkeypatch.setattr(llm, "get_default_embedding_service", lambda: service)
    embed = get_default_embedder()
    assert embed is not None
    with pytest.raises(error_type) as raised:
        embed("query")
    assert raised.value is error


def test_invalid_vector_is_not_silently_accepted(monkeypatch):
    from app.infrastructure import llm

    service = SimpleNamespace(embed_query=Mock(return_value=["not a number"]))
    monkeypatch.setattr(llm, "get_default_embedding_service", lambda: service)
    embed = get_default_embedder()
    assert embed is not None
    with pytest.raises(ValueError):
        embed("query")
