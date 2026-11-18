"""低置信拒答（grounding）测试。

覆盖：
- 域内问题有证据时正常作答并返回 grounding
- 域外问题被拒答：no_answer=True、citations 为空、给出明确提示
- 请求级 min_relevance 与服务端环境默认值可收紧/放宽门槛
- 跨库问答同样拒绝域外问题
- HTTP schema 校验 min_relevance 范围
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_REFUND = "退款政策：客户在签收后七天内可申请无理由退款，退款原路退回。" * 8
_INVOICE = "开票规则：增值税专用发票需要客户提供税号、开户行和地址。" * 8
_OOD = "红烧肉怎么做才好吃"


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
    for dataset_id, source, text in (
        ("kb", "退款.md", _REFUND),
        ("kb-2", "发票.md", _INVOICE),
    ):
        result = service.ingest_document(
            dataset_id=dataset_id,
            source=source,
            text=text,
            tenant_id="t1",
            chunk_strategy="fixed",
            access_context=_ctx(),
        )
        assert result["success"] is True


def _answer(service, query: str, **kwargs):
    return service.answer(
        dataset_id="kb", query=query, top_k=5, tenant_id="t1", access_context=_ctx(), **kwargs
    )


def test_in_domain_question_is_answered_with_grounding(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    result = _answer(service, "退款几天内可以申请？")

    assert result["success"] is True
    assert result["answer_grounded"] is True
    assert result["chunks"]
    assert result["answer"]
    assert not result.get("no_answer")
    assert result["grounding"] >= result["min_relevance"]


def test_out_of_domain_question_is_refused(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    result = _answer(service, _OOD)

    assert result["success"] is True
    assert result["answer_grounded"] is False
    assert result["no_answer"] is True
    assert result["answer"] == "知识库中没有找到与该问题足够相关的内容，请补充资料或换个问法。"
    assert result["citations"] == []
    assert result["grounding"] < result["min_relevance"]


def test_request_min_relevance_can_force_refusal(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    strict = _answer(service, "退款几天内可以申请？", min_relevance=1.0)
    relaxed = _answer(service, "退款几天内可以申请？", min_relevance=0.001)

    assert strict["answer_grounded"] is False
    assert strict["no_answer"] is True
    assert relaxed["answer_grounded"] is True
    assert not relaxed.get("no_answer")


def test_environment_default_min_relevance(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    _seed(service)
    monkeypatch.setenv("XCAGI_KB_MIN_RELEVANCE", "1.0")

    result = _answer(service, "退款几天内可以申请？")

    assert result["min_relevance"] == 1.0
    assert result["answer_grounded"] is False


def test_multi_answer_refuses_out_of_domain(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    result = service.multi_answer(
        dataset_ids=["kb", "kb-2"],
        query=_OOD,
        top_k=5,
        tenant_id="t1",
        access_context=_ctx(),
    )

    assert result["answer_grounded"] is False
    assert result["no_answer"] is True
    assert result["citations"] == []


def test_query_endpoint_validates_min_relevance() -> None:
    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    routes = DocumentRoutes(dispatch=lambda: lambda **_: None, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    too_high = client.post("/datasets/kb/query", json={"query": "退款", "min_relevance": 1.5})
    negative = client.post("/datasets/kb/query", json={"query": "退款", "min_relevance": -0.1})

    assert too_high.status_code == 422
    assert negative.status_code == 422
