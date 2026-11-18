"""知识库流式答案：事件顺序、拒答、无模型回退与 SSE 路由。"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService


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


async def _events(service: DatasetRagApplicationService, query: str, **kwargs):
    return [
        event
        async for event in service.stream_answer(
            dataset_id="kb",
            query=query,
            tenant_id="t1",
            access_context=_ctx(),
            **kwargs,
        )
    ]


class FakeViews:
    async def stream_answer(self, dataset_id, request, payload):
        yield {"event": "meta", "data": {"query": payload.query}}
        yield {"event": "delta", "data": {"text": "退"}}
        yield {"event": "done", "data": {"answer": "退款"}}

    def status_all(self, request):
        return {}


async def _tokens(_query: str, _prompt: str):
    yield "退款"
    yield "流程"


@pytest.mark.asyncio
async def test_stream_answer_emits_deltas_and_done(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="退款.md",
        text="退款流程需要审核退款申请并核对金额，审核后原路退回。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    events = await _events(service, "退款流程", llm_stream=_tokens)

    assert [event["event"] for event in events] == ["meta", "delta", "delta", "done"]
    assert events[0]["data"]["chunk_count"] >= 1
    assert events[1]["data"]["text"] == "退款"
    assert events[3]["data"]["answer"]


@pytest.mark.asyncio
async def test_stream_answer_refuses_out_of_domain(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="退款.md",
        text="退款流程需要审核退款申请并核对金额。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    events = await _events(service, "红烧肉怎么做")

    assert [event["event"] for event in events] == ["meta", "delta", "done"]
    assert events[2]["data"]["no_answer"] is True
    assert events[2]["data"]["citations"] == []


@pytest.mark.asyncio
async def test_stream_answer_falls_back_without_model(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="退款.md",
        text="退款流程需要审核退款申请并核对金额。",
        tenant_id="t1",
        access_context=_ctx(),
    )

    async def _empty(_query: str, _prompt: str):
        if False:
            yield ""

    events = await _events(service, "退款流程", llm_stream=_empty)

    deltas = [event["data"]["text"] for event in events if event["event"] == "delta"]
    assert deltas
    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["answer"]


def test_stream_route_emits_sse() -> None:
    from app.fastapi_routes.knowledge.view_routes import DatasetViewRoutes

    routes = DatasetViewRoutes(views=lambda: FakeViews())
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/datasets/kb/query/stream", json={"query": "退款"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: meta" in body
    assert "event: done" in body
    blocks = [block for block in body.split("\n\n") if block.strip()]
    done_block = next(block for block in blocks if block.startswith("event: done"))
    done_data = json.loads(
        next(line for line in done_block.splitlines() if line.startswith("data: "))[6:]
    )
    assert done_data["answer"] == "退款"


def test_stream_route_redacts_internal_errors_and_logs_for_operators(caplog) -> None:
    from app.fastapi_routes.knowledge.view_routes import DatasetViewRoutes

    class FailedViews(FakeViews):
        async def stream_answer(self, *_args):
            yield {"event": "meta", "data": {}}
            raise RuntimeError("upstream secret-key at /private/customer.sqlite")

    app = FastAPI()
    app.include_router(DatasetViewRoutes(views=lambda: FailedViews()).router)
    with TestClient(app) as client:
        response = client.post("/datasets/kb/query/stream", json={"query": "退款"})
    assert response.status_code == 200 and "event: error" in response.text
    assert "请稍后重试" in response.text
    assert "secret-key" not in response.text and "/private/" not in response.text
    assert "Knowledge answer stream failed" in caplog.text
