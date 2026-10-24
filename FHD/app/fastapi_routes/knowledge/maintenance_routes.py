"""Dataset version comparison, rollback and rebuild jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .ports import DatasetAction
from .read_views import DatasetViews
from .schemas import DatasetRebuildRequest, DatasetRollbackRequest, DatasetVersionDiffRequest


class MaintenanceRoutes:
    """Dataset version comparison, rollback and rebuild jobs."""

    def __init__(
        self,
        *,
        dispatch: Callable[[], DatasetAction],
        views: Callable[[], DatasetViews],
    ) -> None:
        router = self.router = APIRouter()

        @router.post("/datasets/{dataset_id}/versions/diff")
        def diff_dataset_versions(
            dataset_id: str, req: DatasetVersionDiffRequest, request: Request
        ) -> JSONResponse:
            return dispatch()(
                request=request,
                action="diff_versions",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/versions/diff",
                params={
                    "dataset_id": dataset_id,
                    "source": req.source,
                    "tenant_id": req.tenant_id,
                    "from_version": req.from_version,
                    "to_version": req.to_version,
                },
            )

        self.diff_dataset_versions = diff_dataset_versions

        @router.post("/datasets/{dataset_id}/versions/rollback")
        def rollback_dataset_version(
            dataset_id: str, req: DatasetRollbackRequest, request: Request
        ) -> JSONResponse:
            return dispatch()(
                request=request,
                action="rollback_version",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/versions/rollback",
                params={
                    "dataset_id": dataset_id,
                    "source": req.source,
                    "tenant_id": req.tenant_id,
                    "target_version": req.target_version,
                    "metadata": req.metadata,
                },
            )

        self.rollback_dataset_version = rollback_dataset_version

        @router.post("/datasets/{dataset_id}/index/rebuild")
        def rebuild_dataset_index(
            dataset_id: str, req: DatasetRebuildRequest, request: Request
        ) -> JSONResponse:
            return dispatch()(
                request=request,
                action="rebuild_index",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/index/rebuild",
                params={
                    "dataset_id": dataset_id,
                    "tenant_id": req.tenant_id,
                    "metadata_filter": req.metadata_filter,
                    "background": req.background,
                    "max_attempts": req.max_attempts,
                },
            )

        self.rebuild_dataset_index = rebuild_dataset_index

        @router.post("/datasets/{dataset_id}/index/rebuild/{job_id}/cancel")
        def cancel_dataset_rebuild_job(
            dataset_id: str, job_id: str, request: Request
        ) -> JSONResponse:
            return dispatch()(
                request=request,
                action="cancel_rebuild",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/index/rebuild/{job_id}/cancel",
                params={"dataset_id": dataset_id, "job_id": job_id},
            )

        self.cancel_dataset_rebuild_job = cancel_dataset_rebuild_job

        @router.get("/datasets/{dataset_id}/index/rebuild/{job_id}")
        def dataset_rebuild_job(dataset_id: str, job_id: str, request: Request) -> dict[str, Any]:
            return views().job(dataset_id, job_id, request)

        self.dataset_rebuild_job = dataset_rebuild_job
