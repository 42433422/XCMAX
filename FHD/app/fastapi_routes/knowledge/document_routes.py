"""Governed document ingestion, retrieval and deletion."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.application.knowledge.http_port_contracts import DatasetAction
from app.infrastructure.document_parsing.errors import DocumentSourceError

from .schemas import (
    _DATASET_UPLOAD_EXTENSIONS,
    DatasetDocumentAclRequest,
    DatasetDocumentIngestRequest,
    DatasetMultiQueryRequest,
    DatasetQueryRequest,
)
from .uploads import DocumentUpload, _accepted_input

_LOGGER = logging.getLogger(__name__)


def _source_error(error: Exception, fallback: str) -> JSONResponse:
    _LOGGER.warning("Knowledge source import failed", exc_info=error)
    detail = error.public_detail if isinstance(error, DocumentSourceError) else fallback
    return JSONResponse(status_code=400, content={"detail": detail})


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
            text = req.text
            file_path = req.file_path
            source = req.source
            document_id = req.document_id
            staged_path: Path | None = None
            extra_metadata: dict[str, object] = {}
            if req.url.strip():
                from app.infrastructure.document_parsing.web_fetch import fetch_url_text

                try:
                    page = fetch_url_text(req.url)
                except ValueError as exc:
                    return _source_error(exc, "网页导入失败")
                text = page.text
                source = source or page.title or page.url
                document_id = document_id or page.url
                extra_metadata = {
                    "source_kind": "url",
                    "source_ref": page.url,
                    "source_url": page.url,
                }
            elif req.s3_uri.strip():
                from app.infrastructure.document_parsing.object_store import (
                    fetch_object,
                    parse_s3_uri,
                )

                try:
                    _bucket, key = parse_s3_uri(req.s3_uri)
                    raw_suffix = Path(key).suffix.lower()
                    suffix = next(
                        (
                            allowed
                            for allowed in _DATASET_UPLOAD_EXTENSIONS
                            if allowed == raw_suffix
                        ),
                        None,
                    )
                    if suffix is None:
                        return JSONResponse(
                            status_code=400,
                            content={"detail": f"不支持的对象类型：{raw_suffix or '无扩展名'}"},
                        )
                    fetched = fetch_object(req.s3_uri)
                    from app.utils.path_io.path_utils import get_upload_dir

                    base = Path(get_upload_dir()).resolve()
                    # Dataset identity stays in dispatch params; staging paths are server-owned.
                    upload_dir = (base / "knowledge").resolve()
                    if not upload_dir.is_relative_to(base) or upload_dir == base:
                        raise DocumentSourceError("资料上传目录无效")
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    with NamedTemporaryFile(dir=upload_dir, suffix=suffix, delete=False) as target:
                        staged_path = Path(target.name)
                        target.write(fetched.data)
                except (ValueError, OSError) as exc:
                    if staged_path is not None:
                        staged_path.unlink(missing_ok=True)
                    return _source_error(exc, "对象暂存失败")
                file_path = str(staged_path)
                source = source or fetched.filename
                document_id = document_id or req.s3_uri
                extra_metadata = {"source_kind": "s3", "source_ref": req.s3_uri}
            elif req.confluence_page_id.strip():
                from app.infrastructure.document_parsing.confluence import fetch_page

                try:
                    confluence = fetch_page(req.confluence_page_id)
                except ValueError as exc:
                    return _source_error(exc, "Confluence 导入失败")
                text = confluence.text
                source = source or confluence.title or f"confluence:{confluence.page_id}"
                document_id = document_id or confluence.url
                extra_metadata = {
                    "confluence_page_id": confluence.page_id,
                    "source_kind": "confluence",
                    "source_ref": confluence.page_id,
                    "source_url": confluence.url,
                }
            elif req.feishu_document_id.strip():
                from app.infrastructure.document_parsing.feishu_doc import fetch_document

                try:
                    doc = fetch_document(req.feishu_document_id)
                except ValueError as exc:
                    return _source_error(exc, "飞书文档导入失败")
                text = doc.text
                source = source or doc.title or f"feishu:{doc.document_id}"
                document_id = document_id or doc.url
                extra_metadata = {
                    "feishu_document_id": doc.document_id,
                    "source_kind": "feishu",
                    "source_ref": doc.document_id,
                    "source_url": doc.url,
                }
            elif req.notion_page_id.strip():
                from app.infrastructure.document_parsing.notion import (
                    fetch_page as fetch_notion_page,
                )

                try:
                    notion = fetch_notion_page(req.notion_page_id)
                except ValueError as exc:
                    return _source_error(exc, "Notion 导入失败")
                text = notion.text
                source = source or notion.title or f"notion:{notion.page_id}"
                document_id = document_id or notion.url
                extra_metadata = {
                    "notion_page_id": notion.page_id,
                    "source_kind": "notion",
                    "source_ref": notion.page_id,
                    "source_url": notion.url,
                }
            elif req.yuque_document_ref.strip():
                from app.infrastructure.document_parsing.yuque import (
                    fetch_document as fetch_yuque_doc,
                )

                try:
                    yuque = fetch_yuque_doc(req.yuque_document_ref)
                except ValueError as exc:
                    return _source_error(exc, "语雀文档导入失败")
                text = yuque.text
                source = source or yuque.title or f"yuque:{req.yuque_document_ref}"
                document_id = document_id or yuque.url
                extra_metadata = {
                    "yuque_document_ref": req.yuque_document_ref,
                    "source_kind": "yuque",
                    "source_ref": req.yuque_document_ref,
                    "source_url": yuque.url,
                }
            metadata = dict(req.metadata)
            metadata.update(extra_metadata)
            if req.tags:
                metadata["tags"] = list(req.tags)
            if extra_metadata:
                metadata.setdefault("chunk_strategy", req.chunk_strategy)
                metadata.setdefault("chunk_size", req.chunk_size)
                metadata.setdefault("chunk_overlap", req.chunk_overlap)
            if req.acl:
                metadata["acl"] = req.acl
            retained = False
            try:
                response = dispatch()(
                    request=request,
                    action="ingest_document",
                    route_path="/api/knowledge/v1/datasets/{dataset_id}/documents",
                    params={
                        "dataset_id": dataset_id,
                        "source": source,
                        "text": text,
                        "file_path": file_path,
                        "document_id": document_id,
                        "chunk_strategy": req.chunk_strategy,
                        "chunk_size": req.chunk_size,
                        "chunk_overlap": req.chunk_overlap,
                        "metadata": metadata,
                        "tenant_id": req.tenant_id,
                        "version": req.version,
                        "version_label": req.version_label,
                        "allow_duplicate": req.allow_duplicate,
                    },
                )
                retained = _accepted_input(response)
                return response
            finally:
                if staged_path is not None and not retained:
                    staged_path.unlink(missing_ok=True)

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
                    "tags": req.tags,
                    "rerank": req.rerank,
                    "retrieval_mode": req.retrieval_mode,
                    "vector_weight": req.vector_weight,
                    "keyword_weight": req.keyword_weight,
                    "mmr_lambda": req.mmr_lambda,
                    "context_window": req.context_window,
                    "expand_section": req.expand_section,
                    "history": req.history,
                    "min_relevance": req.min_relevance,
                    "max_context_chars": req.max_context_chars,
                },
            )

        self.query_dataset = query_dataset

        @router.post("/datasets/multi-query")
        def multi_query_datasets(req: DatasetMultiQueryRequest, request: Request) -> JSONResponse:
            return dispatch()(
                request=request,
                action="multi_query",
                route_path="/api/knowledge/v1/datasets/multi-query",
                params={
                    "dataset_ids": req.dataset_ids,
                    "query": req.query,
                    "top_k": req.top_k,
                    "include_answer": req.include_answer,
                    "tenant_id": req.tenant_id,
                    "version": req.version,
                    "metadata_filter": req.metadata_filter,
                    "tags": req.tags,
                    "rerank": req.rerank,
                    "retrieval_mode": req.retrieval_mode,
                    "vector_weight": req.vector_weight,
                    "keyword_weight": req.keyword_weight,
                    "mmr_lambda": req.mmr_lambda,
                    "context_window": req.context_window,
                    "expand_section": req.expand_section,
                    "history": req.history,
                    "min_relevance": req.min_relevance,
                    "max_context_chars": req.max_context_chars,
                },
            )

        self.multi_query_datasets = multi_query_datasets

        @router.post("/datasets/{dataset_id}/documents/refresh")
        def refresh_dataset_documents(
            dataset_id: str, request: Request, limit: int = 50, max_age_hours: float = 0
        ) -> JSONResponse:
            return dispatch()(
                request=request,
                action="refresh_documents",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/refresh",
                params={
                    "dataset_id": dataset_id,
                    "limit": max(1, min(int(limit), 200)),
                    "max_age_hours": max(0.0, float(max_age_hours)),
                },
            )

        self.refresh_dataset_documents = refresh_dataset_documents

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

        @router.post("/datasets/{dataset_id}/documents/{document_id}/acl")
        def update_dataset_document_acl(
            dataset_id: str,
            document_id: str,
            req: DatasetDocumentAclRequest,
            request: Request,
        ) -> JSONResponse:
            return dispatch()(
                request=request,
                action="update_document_acl",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/{document_id}/acl",
                params={"dataset_id": dataset_id, "document_id": document_id, "acl": req.acl},
            )

        self.update_dataset_document_acl = update_dataset_document_acl

        @router.post("/datasets/{dataset_id}/documents/{document_id}/refresh")
        def refresh_dataset_document(
            dataset_id: str, document_id: str, request: Request
        ) -> JSONResponse:
            return dispatch()(
                request=request,
                action="refresh_document",
                route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/{document_id}/refresh",
                params={"dataset_id": dataset_id, "document_id": document_id},
            )

        self.refresh_dataset_document = refresh_dataset_document
