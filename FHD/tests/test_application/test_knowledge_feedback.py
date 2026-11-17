"""知识库答案反馈（满意/不满意）测试。

覆盖：
- 记录反馈后汇总按 up/down 统计
- 租户隔离：非管理员只看到自己租户的反馈
- 非法 rating 明确失败
- 缺少 dataset.read 权限被拒
- HTTP 路由校验与转发
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.fastapi_routes.knowledge.view_routes import DatasetViewRoutes


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx(tenant: str = "t1", *, permissions: frozenset[str] | None = None) -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id=tenant,
        permissions=frozenset({"dataset.read"}) if permissions is None else permissions,
        is_admin=False,
    )


def _record(
    service: DatasetRagApplicationService,
    rating: str,
    *,
    tenant: str = "t1",
    query: str = "退款怎么处理",
    comment: str = "",
) -> dict:
    return service.record_feedback(
        dataset_id="kb-refund",
        rating=rating,
        query=query,
        answer="签收后七天内可申请退款。",
        comment=comment,
        citations=[{"source": "退款.md", "chunk_index": 0, "score": 0.91}],
        access_context=_ctx(tenant),
    )


def test_feedback_records_and_summarizes(tmp_path) -> None:
    service = _service(tmp_path)

    first = _record(service, "up")
    _record(service, "up", query="发票怎么开")
    _record(service, "down", comment="答非所问")
    summary = service.feedback_summary("kb-refund", access_context=_ctx())

    assert first["success"] is True
    assert first["feedback"]["rating"] == "up"
    assert first["feedback"]["citations"][0]["source"] == "退款.md"
    assert summary["total"] == 3
    assert summary["up"] == 2
    assert summary["down"] == 1
    assert summary["satisfaction"] == round(2 / 3, 4)
    assert summary["latest"][0]["comment"] == "答非所问"


def test_feedback_is_tenant_scoped(tmp_path) -> None:
    service = _service(tmp_path)
    _record(service, "up", tenant="t1")
    _record(service, "down", tenant="t2")

    t1 = service.feedback_summary("kb-refund", access_context=_ctx("t1"))
    t2 = service.feedback_summary("kb-refund", access_context=_ctx("t2"))

    assert (t1["total"], t1["up"], t1["down"]) == (1, 1, 0)
    assert (t2["total"], t2["up"], t2["down"]) == (1, 0, 1)


def test_feedback_rejects_unknown_rating(tmp_path) -> None:
    result = _record(_service(tmp_path), "meh")

    assert result["success"] is False
    assert "rating" in result["message"]


def test_feedback_requires_read_permission(tmp_path) -> None:
    service = _service(tmp_path)
    result = _record(service, "up")
    denied = service.record_feedback(
        dataset_id="kb-refund",
        rating="up",
        access_context=_ctx(permissions=frozenset()),
    )

    assert result["success"] is True
    assert denied["success"] is False
    assert denied["error_code"] == "dataset_permission_denied"


def test_feedback_routes_validate_and_forward() -> None:
    calls: list[tuple[str, object]] = []

    class _Views:
        def record_feedback(self, dataset_id: str, request: Request, payload) -> dict:
            calls.append(("post", payload))
            return {"success": True, "dataset_id": dataset_id, "rating": payload.rating}

        def feedback_summary(self, dataset_id: str, request: Request, *, limit: int = 20) -> dict:
            calls.append(("get", limit))
            return {"success": True, "dataset_id": dataset_id, "total": 0}

    routes = DatasetViewRoutes(views=lambda: _Views())
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    saved = client.post(
        "/datasets/kb-refund/feedback",
        json={"rating": "down", "query": "退款", "citations": [{"source": "退款.md"}]},
    )
    invalid = client.post("/datasets/kb-refund/feedback", json={"rating": "meh"})
    summary = client.get("/datasets/kb-refund/feedback", params={"limit": 5})

    assert saved.status_code == 200
    assert saved.json()["rating"] == "down"
    assert calls[0][1].citations[0]["source"] == "退款.md"
    assert invalid.status_code == 422
    assert summary.status_code == 200
    assert calls[-1] == ("get", 5)
