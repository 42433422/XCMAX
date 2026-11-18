"""章节标题与相邻块上下文（small-to-big）检索。"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.application.dataset_rag.chunk_context import (
    expanded_context,
    section_title,
)
from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.infrastructure.rag import RetrievedChunk

_MARKDOWN = (
    "# 退款政策\n"
    "退款政策第一段：签收后七天内可申请无理由退款，原路退回。\n"
    "## 到账时间\n"
    "退款到账时间：审核通过后三到五个工作日到账。\n"
    "## 例外\n"
    "例外说明：生鲜商品不支持无理由退款。\n"
)


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=lambda text: [float(len(text)), 1.0],
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx(actor: str = "alice", *, admin: bool = False) -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id=actor,
        tenant_id="t1",
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=admin,
    )


def test_section_title_returns_nearest_heading() -> None:
    first = _MARKDOWN.index("退款政策第一段")
    at_time = _MARKDOWN.index("退款到账时间")
    assert section_title(_MARKDOWN, first) == "退款政策"
    assert section_title(_MARKDOWN, at_time) == "到账时间"
    assert section_title("没有标题的纯文本", 3) == ""


def test_heading_whitespace_cannot_trigger_backtracking_or_cross_lines() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.application.dataset_rag.chunk_context import section_title; "
            "title = 'a' + '\\t' * 200000 + 'b'; text = '# ' + title + '\\r\\nbody'; "
            "assert section_title(text, len(text)) == title[:200]",
        ],
        check=True,
        timeout=5,
    )
    assert section_title("# \nbody without heading", 30) == ""
    assert section_title("###\tTitle  \r\nbody", 30) == "Title"
    assert section_title("####### invalid\nbody", 30) == ""


def test_expanded_context_stays_inside_same_document() -> None:
    def chunk(index: int, text: str, document_id: str = "doc") -> RetrievedChunk:
        return RetrievedChunk(
            text=text,
            score=0.0,
            chunk_index=index,
            char_start=index * 10,
            char_end=index * 10 + len(text),
            metadata={"document_id": document_id, "document_version": 1},
        )

    siblings = [
        chunk(0, "第一段内容。"),
        chunk(1, "第二段命中。"),
        chunk(2, "第三段内容。"),
        chunk(3, "另一文档内容。", document_id="other"),
    ]
    context = expanded_context(siblings[1], siblings)
    assert "第一段内容" in context and "第二段命中" in context and "第三段内容" in context
    assert "另一文档" not in context


def test_query_attaches_section_and_context_window(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="refund.md",
        text=_MARKDOWN,
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=60,
        chunk_overlap=0,
        access_context=_ctx(),
    )

    plain = service.query(
        dataset_id="kb", query="退款到账时间", tenant_id="t1", access_context=_ctx(), top_k=1
    )
    expanded = service.query(
        dataset_id="kb",
        query="退款到账时间",
        tenant_id="t1",
        access_context=_ctx(),
        top_k=1,
        context_window=1,
    )

    plain_meta = plain["chunks"][0]["metadata"]
    expanded_meta = expanded["chunks"][0]["metadata"]
    assert plain_meta.get("section") == "到账时间"
    assert "context" not in plain_meta
    assert expanded_meta["context"] != expanded["chunks"][0]["text"]
    assert any(marker in expanded_meta["context"] for marker in ("签收后七天", "生鲜商品"))


def test_context_window_respects_acl_boundaries(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="public.md",
        text="蓝鲸项目公开段落：进度正常。" * 4,
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=40,
        access_context=_ctx("alice"),
    )
    service.ingest_document(
        dataset_id="kb",
        source="secret.md",
        text="机密榴莲预算：仅限指定成员查看。" * 4,
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=40,
        metadata={"acl": {"allow_actors": ["alice"]}},
        access_context=_ctx("alice"),
    )

    result = service.query(
        dataset_id="kb",
        query="段落",
        tenant_id="t1",
        access_context=_ctx("bob"),
        top_k=5,
        context_window=1,
    )

    assert result["chunks"]
    for row in result["chunks"]:
        assert "机密榴莲" not in row["text"]
        assert "机密榴莲" not in ((row.get("metadata") or {}).get("context") or "")


def test_answer_prompt_uses_expanded_context(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="refund.md",
        text=_MARKDOWN,
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=60,
        chunk_overlap=0,
        access_context=_ctx(),
    )
    seen: dict[str, str] = {}

    def _capture(_query: str, prompt: str) -> str:
        seen["prompt"] = prompt
        return "按资料回答"

    service.answer(
        dataset_id="kb",
        query="退款到账时间",
        tenant_id="t1",
        access_context=_ctx(),
        top_k=1,
        llm_call=_capture,
    )

    assert "签收后七天" in seen["prompt"] or "生鲜商品" in seen["prompt"]


@pytest.mark.parametrize("window", [3, -1])
def test_context_window_is_bounded(window: int) -> None:
    from pydantic import ValidationError

    from app.fastapi_routes.knowledge.schemas import DatasetQueryRequest

    with pytest.raises(ValidationError):
        DatasetQueryRequest(query="x", context_window=window)


def test_fixed_chunking_clamps_overlap_above_window() -> None:
    from app.infrastructure.rag.semantic_chunker import SemanticChunker

    text = "权限说明。" * 40
    chunks = SemanticChunker().split_by_fixed(text, chunk_size=40, chunk_overlap=50)
    assert chunks
    assert chunks[-1].char_end == len(text)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
