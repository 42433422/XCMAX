"""问答上下文预算：提示词证据按预算截断，避免超出平台模型上下文。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

_LONG_TEXT = "退款政策：签收后七天内可以申请退款，审核通过后原路退回。" * 90


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx() -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id="t1",
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=False,
    )


def _seed(service: DatasetRagApplicationService) -> None:
    result = service.ingest_document(
        dataset_id="kb",
        source="退款.md",
        text=_LONG_TEXT,
        tenant_id="t1",
        chunk_strategy="fixed",
        chunk_size=400,
        chunk_overlap=0,
        access_context=_ctx(),
    )
    assert result["success"] is True


def test_answer_truncates_prompt_to_budget(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    prompts: list[str] = []

    def _llm(_query: str, prompt: str) -> str:
        prompts.append(prompt)
        return "七天内可退款 [1]"

    result = service.answer(
        dataset_id="kb",
        query="退款几天内可以申请？",
        top_k=5,
        tenant_id="t1",
        access_context=_ctx(),
        llm_call=_llm,
        max_context_chars=800,
    )

    assert result["success"] is True
    assert result["context_truncated"] is True
    assert 0 < result["context_chars"] <= 800
    assert prompts and len(prompts[0]) < len(_LONG_TEXT)

    relaxed = service.answer(
        dataset_id="kb",
        query="退款几天内可以申请？",
        top_k=5,
        tenant_id="t1",
        access_context=_ctx(),
        llm_call=_llm,
        max_context_chars=200_000,
    )
    assert relaxed["context_truncated"] is False
    assert relaxed["context_chars"] > result["context_chars"]


def test_environment_default_budget(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    _seed(service)
    monkeypatch.setenv("XCAGI_KB_MAX_CONTEXT_CHARS", "600")

    result = service.answer(
        dataset_id="kb",
        query="退款几天内可以申请？",
        top_k=5,
        tenant_id="t1",
        access_context=_ctx(),
        llm_call=lambda _q, _p: "七天内可退款 [1]",
    )

    assert result["context_chars"] <= 600
    assert result["context_truncated"] is True


def test_multi_answer_honours_budget(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    result = service.multi_answer(
        dataset_ids=["kb"],
        query="退款几天内可以申请？",
        top_k=5,
        tenant_id="t1",
        access_context=_ctx(),
        llm_call=lambda _q, _p: "七天内可退款 [1]",
        max_context_chars=700,
    )

    assert result["context_chars"] <= 700
    assert result["context_truncated"] is True


def test_route_forwards_budget_and_validates_range() -> None:
    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    accepted = client.post("/datasets/kb/query", json={"query": "退款", "max_context_chars": 1200})
    rejected = client.post(
        "/datasets/kb/query", json={"query": "退款", "max_context_chars": 300_000}
    )

    assert accepted.status_code == 200
    assert calls[0]["params"]["max_context_chars"] == 1200
    assert rejected.status_code == 422
