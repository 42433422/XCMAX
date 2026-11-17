"""跨知识库联合检索（multi-dataset query）测试。

覆盖：
- 多数据集结果按 RRF 融合并标注来源 dataset_id
- 空 dataset_ids 明确失败
- ACL / 权限收窄在跨库时仍然生效（融合不会放大可见范围）
- 联合问答复用引用合成
- HTTP 路由参数校验与动作分发
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_REFUND = "退款政策：签收后七天内可以申请退款，审核通过后原路退回。" * 12
_INVOICE = "发票规则：支持开具电子发票，红冲需要提供原发票号码。" * 12


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx(
    actor: str = "alice", *, permissions: frozenset[str] | None = None
) -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id=actor,
        tenant_id="t1",
        permissions=(
            frozenset({"dataset.read", "dataset.write"}) if permissions is None else permissions
        ),
        is_admin=False,
    )


def _seed(service: DatasetRagApplicationService, *, acl: dict | None = None) -> None:
    metadata = {"acl": acl} if acl else {}
    service.ingest_document(
        dataset_id="kb-refund",
        source="退款.md",
        text=_REFUND,
        tenant_id="t1",
        chunk_strategy="fixed",
        metadata=metadata,
        access_context=_ctx(),
    )
    service.ingest_document(
        dataset_id="kb-invoice",
        source="发票.md",
        text=_INVOICE,
        tenant_id="t1",
        chunk_strategy="fixed",
        metadata=metadata,
        access_context=_ctx(),
    )


def test_multi_query_fuses_results_from_each_dataset(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    result = service.multi_query(
        dataset_ids=["kb-refund", "kb-invoice"],
        query="退款和发票怎么处理",
        top_k=4,
        tenant_id="t1",
        access_context=_ctx(),
    )

    assert result["success"] is True
    assert {row["dataset_id"] for row in result["chunks"]} == {"kb-refund", "kb-invoice"}
    assert [row["score"] for row in result["chunks"]] == sorted(
        (row["score"] for row in result["chunks"]), reverse=True
    )
    assert [item["dataset_id"] for item in result["datasets"]] == ["kb-refund", "kb-invoice"]


def test_multi_query_deduplicates_dataset_ids(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    result = service.multi_query(
        dataset_ids=["kb-refund", "kb-refund"],
        query="退款",
        tenant_id="t1",
        access_context=_ctx(),
    )

    assert result["dataset_ids"] == ["kb-refund"]
    assert [item["dataset_id"] for item in result["datasets"]] == ["kb-refund"]


def test_multi_query_requires_dataset_ids(tmp_path) -> None:
    result = _service(tmp_path).multi_query(dataset_ids=[], query="退款", access_context=_ctx())

    assert result["success"] is False
    assert result["message"] == "dataset_ids is required"


def test_multi_query_keeps_acl_scope_per_dataset(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service, acl={"allow_actors": ["alice"]})

    result = service.multi_query(
        dataset_ids=["kb-refund", "kb-invoice"],
        query="退款和发票怎么处理",
        top_k=4,
        tenant_id="t1",
        access_context=_ctx("bob"),
    )

    assert result["success"] is True
    assert result["chunks"] == []


def test_multi_query_denied_context_fails_without_leaking(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    result = service.multi_query(
        dataset_ids=["kb-refund", "kb-invoice"],
        query="退款",
        tenant_id="t1",
        access_context=_ctx(permissions=frozenset()),
    )

    assert result["success"] is False
    assert result["chunks"] == []
    assert {item["dataset_id"] for item in result["failed_datasets"]} == {
        "kb-refund",
        "kb-invoice",
    }


def test_multi_answer_synthesizes_citations_across_datasets(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)

    result = service.multi_answer(
        dataset_ids=["kb-refund", "kb-invoice"],
        query="退款和发票怎么处理",
        top_k=4,
        tenant_id="t1",
        access_context=_ctx(),
        llm_call=lambda _question, _prompt: "退款七天内可申请，发票可开电子票 [1]。",
    )

    assert result["success"] is True
    assert "退款" in result["answer"]
    assert result["citations"] and result["citations"][0]["index"] == 1


def test_multi_query_route_validates_and_dispatches() -> None:
    from fastapi.responses import JSONResponse

    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return JSONResponse({"success": True})

    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/datasets/multi-query",
        json={"dataset_ids": ["kb-a", "kb-b", "kb-a"], "query": "退款", "top_k": 3},
    )
    empty = client.post("/datasets/multi-query", json={"dataset_ids": [], "query": "退款"})
    too_many = client.post(
        "/datasets/multi-query",
        json={"dataset_ids": [f"kb-{index}" for index in range(11)], "query": "退款"},
    )

    assert response.status_code == 200
    assert calls[0]["action"] == "multi_query"
    assert calls[0]["params"]["dataset_ids"] == ["kb-a", "kb-b"]
    assert calls[0]["params"]["query"] == "退款"
    assert empty.status_code == 422
    assert too_many.status_code == 422
