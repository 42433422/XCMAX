"""入库自动问题（Q&A 索引增强）：开关、解析、入库写入、BM25 与证据覆盖。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag.retrieval_policy import evidence_grounding
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.infrastructure.llm import question_gen
from app.infrastructure.rag import RetrievedChunk


def _ctx() -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id="t1",
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=False,
    )


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def test_parse_questions_strips_numbering_and_dedupes() -> None:
    raw = "1. 退款怎么申请？\n- 退款怎么申请？\n* 发票开错了怎么办？\n说明文字"

    assert question_gen._parse_questions(raw, 3) == ["退款怎么申请？", "发票开错了怎么办？"]
    assert question_gen._parse_questions(raw, 1) == ["退款怎么申请？"]


def test_generator_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_AUTO_QUESTIONS", raising=False)
    assert question_gen.get_question_llm_call() is None

    monkeypatch.setenv("XCAGI_KB_AUTO_QUESTIONS", "1")
    with patch("app.infrastructure.llm.knowledge_answer.platform_provider", return_value=None):
        assert question_gen.get_question_llm_call() is None


def test_ingest_writes_auto_questions_and_limits_chunks(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XCAGI_KB_AUTO_QUESTIONS", "1")
    monkeypatch.setenv("XCAGI_KB_AUTO_QUESTIONS_MAX_CHUNKS", "1")
    calls: list[str] = []

    def _fake_call(text: str) -> list[str]:
        calls.append(text)
        return ["来料检验怎么做？"]

    monkeypatch.setattr(question_gen, "get_question_llm_call", lambda: _fake_call)
    service = _service(tmp_path)
    result = service.ingest_document(
        dataset_id="kb",
        source="质检.md",
        text="质检流程说明。" * 40,
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=100,
        chunk_overlap=0,
        access_context=_ctx(),
    )

    assert result["success"] is True
    assert len(calls) == 1
    rows = service.query(
        dataset_id="kb", query="质检流程", top_k=10, tenant_id="t1", access_context=_ctx()
    )["chunks"]
    tagged = [row for row in rows if (row.get("metadata") or {}).get("auto_questions")]
    assert len(tagged) == 1
    assert tagged[0]["metadata"]["auto_questions"] == ["来料检验怎么做？"]


def test_generated_questions_are_searchable(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_KB_AUTO_QUESTIONS", "1")
    monkeypatch.setattr(
        question_gen,
        "get_question_llm_call",
        lambda: lambda _text: ["来料检验怎么做？"],
    )
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="质检.md",
        text="质量说明文本。" * 20,
        tenant_id="t1",
        chunk_strategy="fixed",
        access_context=_ctx(),
    )

    result = service.query(
        dataset_id="kb", query="来料检验", top_k=5, tenant_id="t1", access_context=_ctx()
    )

    assert result["chunks"]
    assert "来料检验" in str(result["chunks"][0]["metadata"].get("auto_questions"))


def test_grounding_counts_generated_questions() -> None:
    chunk = RetrievedChunk(
        text="质量说明文本。",
        score=0.1,
        metadata={"auto_questions": ["来料检验怎么做？"]},
    )

    assert evidence_grounding("来料检验", [chunk]) > 0.9
    assert evidence_grounding("红烧肉怎么做", [chunk]) == 0.0
