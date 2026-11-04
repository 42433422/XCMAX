"""Caller-scoped memory review, confirmation and correction."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi import Query as FastAPIQuery
from fastapi.responses import JSONResponse

from .memory import MemoryReview
from .schemas import PersyMemoryMutationRequest, PersyMemoryQueryRequest


class MemoryReviewRoutes:
    """Caller-scoped memory review, confirmation and correction."""

    def __init__(
        self,
        *,
        memories: Callable[[], MemoryReview],
    ) -> None:
        router = self.router = APIRouter()

        @router.get("/datasets/{dataset_id}/memories")
        def list_persy_memories(
            dataset_id: str,
            request: Request,
            status: str = FastAPIQuery(""),
            memory_type: str = FastAPIQuery(""),
            limit: int = FastAPIQuery(200, ge=1, le=1000),
        ) -> JSONResponse:
            return memories().list_memories(
                dataset_id, request, status=status, memory_type=memory_type, limit=limit
            )

        self.list_persy_memories = list_persy_memories

        @router.post("/datasets/{dataset_id}/memories/query")
        def query_persy_memories(
            dataset_id: str, req: PersyMemoryQueryRequest, request: Request
        ) -> JSONResponse:
            return memories().query(dataset_id, req, request)

        self.query_persy_memories = query_persy_memories

        @router.post("/datasets/{dataset_id}/memories/{memory_id}/confirm")
        def confirm_persy_memory(
            dataset_id: str, memory_id: str, req: PersyMemoryMutationRequest, request: Request
        ) -> JSONResponse:
            return memories().confirm(dataset_id, memory_id, req, request)

        self.confirm_persy_memory = confirm_persy_memory

        @router.post("/datasets/{dataset_id}/memories/{memory_id}/reject")
        def reject_persy_memory(
            dataset_id: str, memory_id: str, req: PersyMemoryMutationRequest, request: Request
        ) -> JSONResponse:
            return memories().reject(dataset_id, memory_id, req, request)

        self.reject_persy_memory = reject_persy_memory

        @router.patch("/datasets/{dataset_id}/memories/{memory_id}")
        def correct_persy_memory(
            dataset_id: str, memory_id: str, req: PersyMemoryMutationRequest, request: Request
        ) -> JSONResponse:
            return memories().correct(dataset_id, memory_id, req, request)

        self.correct_persy_memory = correct_persy_memory

        @router.delete("/datasets/{dataset_id}/memories/{memory_id}")
        def delete_persy_memory(
            dataset_id: str,
            memory_id: str,
            request: Request,
            reason: str = FastAPIQuery("", max_length=500),
        ) -> JSONResponse:
            return memories().delete(dataset_id, memory_id, request, reason=reason)

        self.delete_persy_memory = delete_persy_memory
