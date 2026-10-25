"""Governed document ingestion, retrieval and deletion."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.application.knowledge.http_port_contracts import DatasetAction
from .schemas import DatasetDocumentIngestRequest, DatasetQueryRequest
from .uploads import DocumentUpload


class DocumentRoutes:
    """Governed document ingestion, retrieval and deletion."""

    def __init__(
        self,
        *,
        dispatch: Callable[[], DatasetAction],
        uploads: Callable[[Callable[[], str | Path]], DocumentUpload],
    ) -> None:
        router = self.ingestion = APIRouter()

        @router.post("/datasets/{dataset_id}/documents")
        def ingest_dataset_document(
            dataset_id: str, req: DatasetDocumentIngestRequest, request: Request
        ) -> JSONResponse:
            return dispatch()(
                request=request,
                action="ingest_document",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/documents",
                params={
                    "dataset_id": dataset_id,
                    "source": req.source,
                    "text": req.text,
                    "file_path": req.file_path,
                    "document_id": req.document_id,
                    "chunk_strategy": req.chunk_strategy,
                    "chunk_size": req.chunk_size,
                    "chunk_overlap": req.chunk_overlap,
                    "metadata": req.metadata,
                    "tenant_id": req.tenant_id,
                    "version": req.version,
                    "version_label": req.version_label,
                },
            )

        self.ingest_dataset_document = ingest_dataset_document

        @router.post("/datasets/{dataset_id}/documents/upload")
        async def upload_dataset_document(
            dataset_id: str,
            request: Request,
            file: UploadFile = File(...),
            source: str = Form(""),
            tenant_id: str = Form(""),
            version: str = Form(""),
            version_label: str = Form(""),
            chunk_strategy: str = Form("semantic"),
        ) -> JSONResponse:
            from app.utils.path_io.path_utils import get_upload_dir

            upload = uploads(get_upload_dir)
            return await upload.ingest(
                dataset_id,
                request,
                file=file,
                source=source,
                tenant_id=tenant_id,
                version=version,
                version_label=version_label,
                chunk_strategy=chunk_strategy,
            )

        self.upload_dataset_document = upload_dataset_document

        @router.post("/datasets/{dataset_id}/query")
        def query_dataset(
            dataset_id: str, req: DatasetQueryRequest, request: Request
        ) -> JSONResponse:
            return dispatch()(
                request=request,
                action="query",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/query",
                params={
                    "dataset_id": dataset_id,
                    "query": req.query,
                    "top_k": req.top_k,
                    "include_answer": req.include_answer,
                    "tenant_id": req.tenant_id,
                    "version": req.version,
                    "metadata_filter": req.metadata_filter,
                    "rerank": req.rerank,
                },
            )

        self.query_dataset = query_dataset

        router = self.deletion = APIRouter()

        @router.delete("/datasets/{dataset_id}/documents/{document_id}")
        def delete_dataset_document(
            dataset_id: str, document_id: str, request: Request
        ) -> JSONResponse:
            return dispatch()(
                request=request,
                action="delete_document",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/{document_id}",
                params={"dataset_id": dataset_id, "document_id": document_id},
            )

        self.delete_dataset_document = delete_dataset_document
