"""Dataset counts, document status and graph visibility."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi import Query as FastAPIQuery

from .read_views import DatasetViews


class DatasetViewRoutes:
    """Dataset counts, document status and graph visibility."""

    def __init__(
        self,
        *,
        views: Callable[[], DatasetViews],
    ) -> None:
        router = self.router = APIRouter()

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

        @router.get("/datasets/{dataset_id}/graph")
        def dataset_graph(
            dataset_id: str, request: Request, limit: int = FastAPIQuery(80, ge=20, le=240)
        ) -> dict[str, Any]:
            return views().graph(dataset_id, request, limit=limit)

        self.dataset_graph = dataset_graph
