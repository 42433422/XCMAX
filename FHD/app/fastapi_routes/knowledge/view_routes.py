"""Dataset counts, document status and graph visibility."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi import Query as FastAPIQuery
from fastapi.responses import StreamingResponse

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .read_views import DatasetViews
from .schemas import (
    DatasetApiKeyRequest,
    DatasetFeedbackRequest,
    DatasetImportRequest,
    DatasetQaPairsRequest,
    DatasetQueryRequest,
    DatasetSynonymsRequest,
)

_LOGGER = logging.getLogger(__name__)


def _sse(event: dict[str, Any]) -> bytes:
    payload = json.dumps(event.get("data") or {}, ensure_ascii=False)
    return f"event: {event.get('event', 'message')}\ndata: {payload}\n\n".encode()


class DatasetViewRoutes:
    """Dataset counts, document status and graph visibility."""

    def __init__(
        self,
        *,
        views: Callable[[], DatasetViews],
    ) -> None:
        router = self.router = APIRouter()

        @router.post("/datasets/{dataset_id}/query/stream")
        def stream_dataset_answer(
            dataset_id: str, req: DatasetQueryRequest, request: Request
        ) -> StreamingResponse:
            async def _events() -> AsyncIterator[bytes]:
                try:
                    async for event in views().stream_answer(dataset_id, request, req):
                        yield _sse(event)
                except RECOVERABLE_ERRORS:
                    _LOGGER.exception("Knowledge answer stream failed")
                    yield _sse(
                        {"event": "error", "data": {"message": "知识库回答暂时不可用，请稍后重试"}}
                    )

            return StreamingResponse(
                _events(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        self.stream_dataset_answer = stream_dataset_answer

        @router.get("/datasets")
        def dataset_status_all(request: Request) -> dict[str, Any]:
            return views().status_all(request)

        self.dataset_status_all = dataset_status_all

        @router.get("/datasets/{dataset_id}/status")
        def dataset_status(
            dataset_id: str,
            request: Request,
            include_documents: bool = FastAPIQuery(
                True,
                description="When false, omit document rows (counts/index only) for lighter graph HUD loads",
            ),
        ) -> dict[str, Any]:
            return views().status(dataset_id, request, include_documents=include_documents)

        self.dataset_status = dataset_status

        @router.get("/datasets/{dataset_id}/documents/{document_id}/chunks")
        def dataset_document_chunks(
            dataset_id: str,
            document_id: str,
            request: Request,
            offset: int = FastAPIQuery(0, ge=0),
            limit: int = FastAPIQuery(50, ge=1, le=200),
        ) -> dict[str, Any]:
            return views().document_chunks(
                dataset_id, document_id, request, offset=offset, limit=limit
            )

        self.dataset_document_chunks = dataset_document_chunks

        @router.post("/datasets/{dataset_id}/feedback")
        def dataset_feedback(
            dataset_id: str, req: DatasetFeedbackRequest, request: Request
        ) -> dict[str, Any]:
            return views().record_feedback(dataset_id, request, req)

        self.dataset_feedback = dataset_feedback

        @router.get("/datasets/{dataset_id}/feedback")
        def dataset_feedback_summary(
            dataset_id: str,
            request: Request,
            limit: int = FastAPIQuery(20, ge=1, le=100),
        ) -> dict[str, Any]:
            return views().feedback_summary(dataset_id, request, limit=limit)

        self.dataset_feedback_summary = dataset_feedback_summary

        @router.get("/datasets/{dataset_id}/synonyms")
        def dataset_synonyms(dataset_id: str, request: Request) -> dict[str, Any]:
            return views().synonyms(dataset_id, request)

        self.dataset_synonyms = dataset_synonyms

        @router.put("/datasets/{dataset_id}/synonyms")
        def update_dataset_synonyms(
            dataset_id: str, req: DatasetSynonymsRequest, request: Request
        ) -> dict[str, Any]:
            return views().update_synonyms(dataset_id, request, req)

        self.update_dataset_synonyms = update_dataset_synonyms

        @router.get("/datasets/{dataset_id}/qa-pairs")
        def dataset_qa_pairs(dataset_id: str, request: Request) -> dict[str, Any]:
            return views().qa_pairs(dataset_id, request)

        self.dataset_qa_pairs = dataset_qa_pairs

        @router.put("/datasets/{dataset_id}/qa-pairs")
        def update_dataset_qa_pairs(
            dataset_id: str, req: DatasetQaPairsRequest, request: Request
        ) -> dict[str, Any]:
            return views().update_qa_pairs(dataset_id, request, req)

        self.update_dataset_qa_pairs = update_dataset_qa_pairs

        @router.delete("/datasets/{dataset_id}/qa-pairs")
        def delete_dataset_qa_pairs(dataset_id: str, request: Request) -> dict[str, Any]:
            return views().delete_qa_pairs(dataset_id, request)

        self.delete_dataset_qa_pairs = delete_dataset_qa_pairs

        @router.get("/datasets/{dataset_id}/query-gaps")
        def dataset_query_gaps(
            dataset_id: str,
            request: Request,
            limit: int = FastAPIQuery(20, ge=1, le=100),
        ) -> dict[str, Any]:
            return views().query_gaps(dataset_id, request, limit=limit)

        self.dataset_query_gaps = dataset_query_gaps

        @router.delete("/datasets/{dataset_id}/query-gaps")
        def clear_dataset_query_gaps(dataset_id: str, request: Request) -> dict[str, Any]:
            return views().clear_query_gaps(dataset_id, request)

        self.clear_dataset_query_gaps = clear_dataset_query_gaps

        @router.get("/datasets/{dataset_id}/export")
        def export_dataset(dataset_id: str, request: Request) -> dict[str, Any]:
            return views().export_dataset(dataset_id, request)

        self.export_dataset = export_dataset

        @router.post("/datasets/{dataset_id}/import")
        def import_dataset(
            dataset_id: str, req: DatasetImportRequest, request: Request
        ) -> dict[str, Any]:
            return views().import_dataset(dataset_id, request, req)

        self.import_dataset = import_dataset

        @router.post("/datasets/{dataset_id}/api-keys")
        def create_dataset_api_key(
            dataset_id: str, req: DatasetApiKeyRequest, request: Request
        ) -> dict[str, Any]:
            return views().create_api_key(dataset_id, request, req)

        self.create_dataset_api_key = create_dataset_api_key

        @router.get("/datasets/{dataset_id}/api-keys")
        def list_dataset_api_keys(dataset_id: str, request: Request) -> dict[str, Any]:
            return views().list_api_keys(dataset_id, request)

        self.list_dataset_api_keys = list_dataset_api_keys

        @router.delete("/datasets/{dataset_id}/api-keys/{token_id}")
        def revoke_dataset_api_key(
            dataset_id: str, token_id: str, request: Request
        ) -> dict[str, Any]:
            return views().revoke_api_key(dataset_id, token_id, request)

        self.revoke_dataset_api_key = revoke_dataset_api_key

        @router.get("/datasets/{dataset_id}/graph")
        def dataset_graph(
            dataset_id: str, request: Request, limit: int = FastAPIQuery(80, ge=20, le=240)
        ) -> dict[str, Any]:
            return views().graph(dataset_id, request, limit=limit)

        self.dataset_graph = dataset_graph
