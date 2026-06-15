"""Phase 2: semantic_chunker 单元测试。"""

from __future__ import annotations

from app.infrastructure.rag.semantic_chunker import Chunk, SemanticChunker


class TestSemanticChunker:
    def test_empty_text_returns_empty(self):
        chunker = SemanticChunker()
        assert chunker.split_by_semantic("") == []
        assert chunker.split_by_semantic("   ") == []

    def test_fixed_fallback_without_embedder(self):
        chunker = SemanticChunker(embedder=None, max_chunk_chars=50)
        text = "第一句。第二句！第三句？"
        chunks = chunker.split_by_fixed(text)
        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)
        assert chunks[0].strategy == "fixed"

    def test_split_sentences_chinese_punctuation(self):
        chunker = SemanticChunker()
        sents = chunker._split_sentences("你好。世界！测试？")
        assert len(sents) >= 2

    def test_split_by_semantic_single_sentence(self):
        chunker = SemanticChunker(embedder=lambda t: [1.0, 0.0])
        chunks = chunker.split_by_semantic("只有一句。")
        assert len(chunks) == 1
        assert chunks[0].text == "只有一句。"

    def test_cosine_identical(self):
        chunker = SemanticChunker()
        sim = chunker._cosine([1.0, 0.0], [1.0, 0.0])
        assert abs(sim - 1.0) < 0.001

    def test_cosine_orthogonal(self):
        chunker = SemanticChunker()
        sim = chunker._cosine([1.0, 0.0], [0.0, 1.0])
        assert abs(sim) < 0.001

    def test_semantic_split_with_embedder(self):
        def embed(text: str) -> list[float]:
            if "A" in text:
                return [1.0, 0.0]
            if "B" in text:
                return [0.9, 0.1]
            return [0.0, 1.0]

        chunker = SemanticChunker(embedder=embed, threshold=0.5, min_chunk_chars=1, max_chunk_chars=200)
        text = "A。B。C。"
        chunks = chunker.split_by_semantic(text)
        assert len(chunks) >= 1
