"""Persy knowledge API.

This boundary owns governed document ingestion, hybrid retrieval, knowledge
graphs, and user/tenant memory review. Dataset actions continue through the
unified Agent runtime so permissions, audit records, and run telemetry remain
consistent with the rest of XCAGI.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request
from fastapi import File as File
from fastapi import Form as Form
from fastapi import Query as FastAPIQuery  # noqa: F401 -- legacy helper export
from fastapi import UploadFile as UploadFile
from fastapi.responses import JSONResponse

from app.fastapi_routes.dataset_access import (
    require_desktop_knowledge_access,
    require_tenant_knowledge,
)
from app.fastapi_routes.knowledge.access import (
    _dataset_access_context_from_request as _dataset_access_context_from_request,
)
from app.fastapi_routes.knowledge.access import (
    _dataset_access_payload_from_request as _dataset_access_payload_from_request,
)
from app.fastapi_routes.knowledge.access import (
    _dataset_read_tenant_scope as _dataset_read_tenant_scope,
)
from app.fastapi_routes.knowledge.access import (
    _request_tenant_key as _request_tenant_key,
)
from app.fastapi_routes.knowledge.agent import DatasetAgent
from app.fastapi_routes.knowledge.agent import _agent_node_output as _agent_node_output
from app.fastapi_routes.knowledge.agent import _dataset_agent_user_id as _dataset_agent_user_id
from app.fastapi_routes.knowledge.document_routes import DocumentRoutes
from app.fastapi_routes.knowledge.legacy_index import KnowledgeIndex
from app.fastapi_routes.knowledge.legacy_ingest import mirror_legacy_ingest
from app.fastapi_routes.knowledge.legacy_routes import LegacyRoutes
from app.fastapi_routes.knowledge.maintenance_routes import MaintenanceRoutes
from app.fastapi_routes.knowledge.memory import MemoryReview, dataset_error, memory_response
from app.fastapi_routes.knowledge.memory_routes import MemoryReviewRoutes
from app.fastapi_routes.knowledge.overview_routes import OverviewRoutes
from app.fastapi_routes.knowledge.read_views import DatasetViews
from app.fastapi_routes.knowledge.schemas import (
    _DATASET_INLINE_MAX_CHARS as _DATASET_INLINE_MAX_CHARS,
)
from app.fastapi_routes.knowledge.schemas import (
    _DATASET_METADATA_MAX_BYTES as _DATASET_METADATA_MAX_BYTES,
)
from app.fastapi_routes.knowledge.schemas import (
    _DATASET_UPLOAD_EXTENSIONS as _DATASET_UPLOAD_EXTENSIONS,
)
from app.fastapi_routes.knowledge.schemas import (
    _DATASET_UPLOAD_MAX_BYTES as _DATASET_UPLOAD_MAX_BYTES,
)
from app.fastapi_routes.knowledge.schemas import (
    _PERSY_DATASET_ID as _PERSY_DATASET_ID,
)
from app.fastapi_routes.knowledge.schemas import (
    DatasetDocumentIngestRequest as DatasetDocumentIngestRequest,
)
from app.fastapi_routes.knowledge.schemas import (
    DatasetQueryRequest as DatasetQueryRequest,
)
from app.fastapi_routes.knowledge.schemas import (
    DatasetRebuildRequest as DatasetRebuildRequest,
)
from app.fastapi_routes.knowledge.schemas import (
    DatasetRollbackRequest as DatasetRollbackRequest,
)
from app.fastapi_routes.knowledge.schemas import (
    DatasetVersionDiffRequest as DatasetVersionDiffRequest,
)
from app.fastapi_routes.knowledge.schemas import (
    IngestRequest as IngestRequest,
)
from app.fastapi_routes.knowledge.schemas import (
    IngestResponse as IngestResponse,
)
from app.fastapi_routes.knowledge.schemas import (
    PersyMemoryMutationRequest as PersyMemoryMutationRequest,
)
from app.fastapi_routes.knowledge.schemas import (
    PersyMemoryQueryRequest as PersyMemoryQueryRequest,
)
from app.fastapi_routes.knowledge.schemas import (
    QueryRequest as QueryRequest,
)
from app.fastapi_routes.knowledge.schemas import (
    QueryResponse as QueryResponse,
)
from app.fastapi_routes.knowledge.schemas import (
    StatusResponse as StatusResponse,
)
from app.fastapi_routes.knowledge.schemas import (
    _ensure_bounded_metadata as _ensure_bounded_metadata,
)
from app.fastapi_routes.knowledge.serialization import (
    _public_dataset_payload as _public_dataset_payload,
)
from app.fastapi_routes.knowledge.uploads import DocumentUpload
from app.fastapi_routes.knowledge.view_routes import DatasetViewRoutes
from app.infrastructure.rag import (
    HybridRetriever,
    RetrievedChunk,
    SemanticChunker,
    get_default_embedder,
    is_rag_enabled,
)

if TYPE_CHECKING:
    from app.application.dataset_rag_app_service import DatasetRagApplicationService
    from app.application.persy_memory_app_service import PersyMemoryApplicationService


logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/knowledge/v1",
    tags=["knowledge-v1"],
    dependencies=[Depends(require_desktop_knowledge_access)],
)


class _KnowledgeIndex(KnowledgeIndex):
    """Compatibility constructor; all mutable retrieval state belongs to KnowledgeIndex."""

    def __init__(self) -> None:
        super().__init__(
            chunker=SemanticChunker(embedder=get_default_embedder()),
            retriever=HybridRetriever(embedder=get_default_embedder()),
            chunk_factory=RetrievedChunk,
        )


_index = _KnowledgeIndex()


def _dataset_service() -> DatasetRagApplicationService:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    return get_dataset_rag_app_service()


def _persy_memory_service() -> PersyMemoryApplicationService:
    from app.application.persy_memory_app_service import get_persy_memory_app_service

    return get_persy_memory_app_service()


def _views() -> DatasetViews:
    return DatasetViews(
        service=_dataset_service,
        access=_dataset_access_context_from_request,
        tenant_scope=_dataset_read_tenant_scope,
        memories=_persy_memory_service,
        dataset_id=_PERSY_DATASET_ID,
        logger=logger,
    )


def _memories() -> MemoryReview:
    return MemoryReview(
        service=_persy_memory_service,
        access=_dataset_access_context_from_request,
        dataset_error=_persy_dataset_error,
        response=_persy_memory_response,
        dataset_id=_PERSY_DATASET_ID,
    )


def _persy_dataset_error(dataset_id: str) -> JSONResponse | None:
    return dataset_error(dataset_id, _PERSY_DATASET_ID)


def _persy_memory_response(
    payload: dict[str, Any], *, request: Request, action: str
) -> JSONResponse:
    return memory_response(
        payload,
        request=request,
        action=action,
        access_resolver=_dataset_access_context_from_request,
        logger=logger,
    )


def _merge_persy_recall(
    payload: dict[str, Any], *, request: Request, params: dict[str, Any]
) -> dict[str, Any]:
    return _memories().merge_recall(payload, request=request, params=params)


def _run_dataset_rag_agent(
    *, request: Request, action: str, params: dict[str, Any], route_path: str
) -> JSONResponse:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow_registry_app import get_workflow_tool_registry

    return DatasetAgent(
        runtime=AgentOrchestrator,
        registry=get_workflow_tool_registry,
        access_payload=_dataset_access_payload_from_request,
        actor=_dataset_agent_user_id,
        output=_agent_node_output,
        recall=_merge_persy_recall,
    ).run(request=request, action=action, params=params, route_path=route_path)


def _knowledge_runtime_snapshot(request: Request | None = None) -> dict[str, Any]:
    return _views().snapshot(
        request,
        legacy=_index.status(),
        embedder_available=lambda: get_default_embedder() is not None,
        rag_enabled=is_rag_enabled,
    )


def _mirror_ingest_to_persy(
    *,
    text: str,
    source: str,
    chunk_strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    request: Request | None = None,
) -> dict[str, Any]:
    """Dual-write legacy /ingest into governed persy-knowledge dataset."""
    return mirror_legacy_ingest(
        text=text,
        source=source,
        chunk_strategy=chunk_strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        request=request,
        writer=lambda: _dataset_service().ingest_document,
        access_resolver=_dataset_access_context_from_request,
        dataset_id=_PERSY_DATASET_ID,
        logger=logger,
    )


# Dependencies stay on this public router; owners preserve their declaration order.
_legacy_routes = LegacyRoutes(
    index=lambda: _index,
    mirror=lambda: _mirror_ingest_to_persy,
    tenant_key=lambda request: _request_tenant_key(request),
    rag_enabled=lambda: is_rag_enabled(),
    require_tenant=require_tenant_knowledge,
)
_document_routes = DocumentRoutes(
    dispatch=lambda: _run_dataset_rag_agent,
    uploads=lambda directory: DocumentUpload(
        dispatch=_run_dataset_rag_agent,
        directory=directory,
        extensions=_DATASET_UPLOAD_EXTENSIONS,
        max_bytes=_DATASET_UPLOAD_MAX_BYTES,
        logger=logger,
    ),
)
_view_routes = DatasetViewRoutes(views=lambda: _views())
_memory_routes = MemoryReviewRoutes(memories=lambda: _memories())
_maintenance_routes = MaintenanceRoutes(
    dispatch=lambda: _run_dataset_rag_agent, views=lambda: _views()
)
_overview_routes = OverviewRoutes(
    views=lambda: _views(),
    snapshot=lambda: _knowledge_runtime_snapshot,
    rag_enabled=lambda: is_rag_enabled,
)

router.include_router(_legacy_routes.router)
router.include_router(_document_routes.ingestion)
router.include_router(_view_routes.router)
router.include_router(_memory_routes.router)
router.include_router(_maintenance_routes.router)
router.include_router(_document_routes.deletion)
router.include_router(_overview_routes.router)

ingest = _legacy_routes.ingest
query = _legacy_routes.query
ingest_dataset_document = _document_routes.ingest_dataset_document
upload_dataset_document = _document_routes.upload_dataset_document
query_dataset = _document_routes.query_dataset
dataset_status_all = _view_routes.dataset_status_all
dataset_status = _view_routes.dataset_status
dataset_graph = _view_routes.dataset_graph
list_persy_memories = _memory_routes.list_persy_memories
query_persy_memories = _memory_routes.query_persy_memories
confirm_persy_memory = _memory_routes.confirm_persy_memory
reject_persy_memory = _memory_routes.reject_persy_memory
correct_persy_memory = _memory_routes.correct_persy_memory
delete_persy_memory = _memory_routes.delete_persy_memory
diff_dataset_versions = _maintenance_routes.diff_dataset_versions
rollback_dataset_version = _maintenance_routes.rollback_dataset_version
rebuild_dataset_index = _maintenance_routes.rebuild_dataset_index
cancel_dataset_rebuild_job = _maintenance_routes.cancel_dataset_rebuild_job
dataset_rebuild_job = _maintenance_routes.dataset_rebuild_job
delete_dataset_document = _document_routes.delete_dataset_document
status = _overview_routes.status
health = _overview_routes.health
omniscient_overview = _overview_routes.omniscient_overview
omniscient_query = _overview_routes.omniscient_query
