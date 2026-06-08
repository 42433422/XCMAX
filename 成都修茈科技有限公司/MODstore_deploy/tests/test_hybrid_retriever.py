"""混合检索器单元测试。"""

import pytest

from modstore_server.hybrid_retriever import HybridRetriever, _tokenize
from modstore_server.rag_service import RetrievedChunk


class TestTokenize:
    def test_english(self):
        tokens = _tokenize("hello world")
        assert tokens == ["hello", "world"]

    def test_chinese(self):
        tokens = _tokenize("你好世界")
        assert "你" in tokens
        assert "好" in tokens

    def test_mixed(self):
        tokens = _tokenize("hello 你好 world")
        assert "hello" in tokens
        assert "你" in tokens

    def test_empty(self):
        assert _tokenize("") == []


def _make_chunk(chunk_id: str, content: str, distance: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        collection_id=1,
        collection_name="test",
        owner_kind="user",
        owner_id="1",
        doc_id="doc1",
        chunk_id=chunk_id,
        filename="test.txt",
        page_no=None,
        content=content,
        distance=distance,
        score=1.0 - distance,
    )


class TestHybridRetriever:
    def test_fuse_empty_returns_empty(self):
        retriever = HybridRetriever()
        assert retriever.fuse([], "test") == []

    def test_fuse_vector_only_when_no_corpus(self):
        retriever = HybridRetriever()
        chunks = [_make_chunk("c1", "hello world", 0.3)]
        result = retriever.fuse(chunks, "test", corpus=None)
        assert len(result) == 1

    def test_fuse_with_corpus(self):
        retriever = HybridRetriever()
        chunks = [
            _make_chunk("c1", "Python is a programming language", 0.2),
            _make_chunk("c2", "Java is also a programming language", 0.4),
            _make_chunk("c3", "The weather is nice today", 0.8),
        ]
        corpus = [c.content for c in chunks]
        result = retriever.fuse(chunks, "programming language", corpus=corpus, final_top_k=3)
        assert len(result) > 0

    def test_fuse_degrades_gracefully_without_bm25(self):
        retriever = HybridRetriever()
        chunks = [_make_chunk("c1", "test content", 0.3)]
        import modstore_server.hybrid_retriever as hr

        original = hr._bm25_available
        hr._bm25_available = lambda: False
        try:
            result = retriever.fuse(chunks, "test", corpus=["test content"])
            assert len(result) == 1
        finally:
            hr._bm25_available = original
