"""语义分块器单元测试。"""

import pytest

from modstore_server.knowledge_ingest import (
    SemanticChunker,
    _get_chunker,
    _split_sentences,
    chunk_text,
)


class TestSplitSentences:
    def test_latin_punctuation(self):
        result = _split_sentences("Hello world. How are you? Fine!")
        assert len(result) >= 2

    def test_cjk_punctuation(self):
        result = _split_sentences("你好世界。今天天气很好！")
        assert len(result) >= 2

    def test_empty_string(self):
        result = _split_sentences("")
        assert result == []

    def test_single_sentence(self):
        result = _split_sentences("Hello world")
        assert len(result) == 1


class TestSemanticChunker:
    def test_chunk_sync_falls_back_to_fixed(self):
        chunker = SemanticChunker()
        text = "这是一段测试文本。" * 50
        result = chunker.chunk_sync(text)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_chunk_with_empty_text(self):
        chunker = SemanticChunker()
        result = chunker.chunk_sync("")
        assert result == []


class TestGetChunker:
    def test_returns_none_for_fixed(self):
        assert _get_chunker("fixed") is None

    def test_returns_chunker_for_semantic(self):
        chunker = _get_chunker("semantic")
        assert isinstance(chunker, SemanticChunker)

    def test_default_strategy(self):
        chunker = _get_chunker(None)
        if chunker is not None:
            assert isinstance(chunker, SemanticChunker)


class TestChunkTextWithMetadata:
    def test_includes_chunk_strategy(self):
        from modstore_server.knowledge_ingest import chunk_text_with_metadata

        text = "Hello world. " * 100
        chunks, metas = chunk_text_with_metadata(text, chunk_strategy="fixed")
        assert len(chunks) > 0
        assert all(m.get("chunk_strategy") == "fixed" for m in metas)

    def test_includes_char_range(self):
        from modstore_server.knowledge_ingest import chunk_text_with_metadata

        text = "Hello world. " * 100
        chunks, metas = chunk_text_with_metadata(text, chunk_strategy="fixed")
        assert len(chunks) > 0
        for m in metas:
            assert "char_range" in m
            assert len(m["char_range"]) == 2
