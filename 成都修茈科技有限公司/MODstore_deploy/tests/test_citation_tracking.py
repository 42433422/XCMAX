"""引用溯源集成测试。"""

import pytest

from modstore_server.rag_service import RetrievedChunk, extract_citations, format_retrieved_block


def _make_chunk(chunk_id: str, content: str, filename: str = "test.txt") -> RetrievedChunk:
    return RetrievedChunk(
        collection_id=1,
        collection_name="test",
        owner_kind="user",
        owner_id="1",
        doc_id="doc1",
        chunk_id=chunk_id,
        filename=filename,
        page_no=1,
        content=content,
        distance=0.3,
        score=0.7,
        source_url="",
        char_range=[0, 100],
    )


class TestExtractCitations:
    def test_single_citation(self):
        chunks = [_make_chunk("c1", "Python is great")]
        output = "Python 是一门优秀的语言[1]"
        result = extract_citations(output, chunks)
        assert len(result) == 1
        assert result[0]["ref"] == 1

    def test_multiple_citations(self):
        chunks = [
            _make_chunk("c1", "Python is great"),
            _make_chunk("c2", "Java is also great"),
        ]
        output = "Python[1] 和 Java[2] 都是优秀的语言"
        result = extract_citations(output, chunks)
        assert len(result) == 2
        assert result[0]["ref"] == 1
        assert result[1]["ref"] == 2

    def test_no_citations(self):
        chunks = [_make_chunk("c1", "test")]
        result = extract_citations("没有引用的文本", chunks)
        assert result == []

    def test_out_of_range_citation_ignored(self):
        chunks = [_make_chunk("c1", "test")]
        output = "引用[5]超出范围"
        result = extract_citations(output, chunks)
        assert result == []

    def test_duplicate_citation_counted_once(self):
        chunks = [_make_chunk("c1", "test")]
        output = "引用[1]再次引用[1]"
        result = extract_citations(output, chunks)
        assert len(result) == 1


class TestFormatRetrievedBlock:
    def test_includes_char_range(self):
        chunks = [_make_chunk("c1", "test content")]
        block = format_retrieved_block(chunks)
        assert "字符" in block

    def test_includes_page_info(self):
        chunks = [_make_chunk("c1", "test content")]
        block = format_retrieved_block(chunks)
        assert "第" in block
        assert "页" in block

    def test_empty_chunks(self):
        block = format_retrieved_block([])
        assert block == ""
