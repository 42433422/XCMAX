"""Persy knowledge API.

This boundary owns governed document ingestion, hybrid retrieval, knowledge
graphs, and user/tenant memory review. Dataset actions continue through the
unified Agent runtime so permissions, audit records, and run telemetry remain
consistent with the rest of XCAGI.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi import Query as FastAPIQuery
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from app.application.workflow.types import normalize_workflow_risk
from app.infrastructure.rag import (
    HybridRetriever,
    RetrievedChunk,
    SemanticChunker,
    get_default_embedder,
    is_rag_enabled,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/knowledge/v1", tags=["knowledge-v1"])

_DATASET_UPLOAD_EXTENSIONS = frozenset(
    {".pdf", ".docx", ".xlsx", ".xls", ".txt", ".md", ".csv", ".json", ".log"}
)
_DATASET_UPLOAD_MAX_BYTES = 25 * 1024 * 1024
_DATASET_INLINE_MAX_CHARS = 5_000_000
_DATASET_METADATA_MAX_BYTES = 64 * 1024
_PERSY_DATASET_ID = "persy-knowledge"


from app.fastapi_routes.knowledge_v1_part01 import (
    DatasetDocumentIngestRequest as DatasetDocumentIngestRequest,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    DatasetQueryRequest as DatasetQueryRequest,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    DatasetRebuildRequest as DatasetRebuildRequest,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    DatasetRollbackRequest as DatasetRollbackRequest,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    DatasetVersionDiffRequest as DatasetVersionDiffRequest,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    IngestRequest as IngestRequest,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    IngestResponse as IngestResponse,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    PersyMemoryMutationRequest as PersyMemoryMutationRequest,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    PersyMemoryQueryRequest as PersyMemoryQueryRequest,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    QueryRequest as QueryRequest,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    QueryResponse as QueryResponse,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    StatusResponse as StatusResponse,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _agent_node_output as _agent_node_output,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _dataset_access_context_from_request as _dataset_access_context_from_request,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _dataset_access_payload_from_request as _dataset_access_payload_from_request,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _dataset_agent_user_id as _dataset_agent_user_id,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _dataset_read_tenant_scope as _dataset_read_tenant_scope,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _ensure_bounded_metadata as _ensure_bounded_metadata,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _KnowledgeIndex as _KnowledgeIndex,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _merge_persy_recall as _merge_persy_recall,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _mirror_ingest_to_persy as _mirror_ingest_to_persy,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _persy_dataset_error as _persy_dataset_error,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _persy_memory_response as _persy_memory_response,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _persy_memory_service as _persy_memory_service,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _public_dataset_payload as _public_dataset_payload,
)
from app.fastapi_routes.knowledge_v1_part01 import (
    _run_dataset_rag_agent as _run_dataset_rag_agent,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    _knowledge_runtime_snapshot as _knowledge_runtime_snapshot,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    cancel_dataset_rebuild_job as cancel_dataset_rebuild_job,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    confirm_persy_memory as confirm_persy_memory,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    correct_persy_memory as correct_persy_memory,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    dataset_graph as dataset_graph,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    dataset_rebuild_job as dataset_rebuild_job,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    dataset_status as dataset_status,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    dataset_status_all as dataset_status_all,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    delete_dataset_document as delete_dataset_document,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    delete_persy_memory as delete_persy_memory,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    diff_dataset_versions as diff_dataset_versions,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    health as health,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    ingest as ingest,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    ingest_dataset_document as ingest_dataset_document,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    list_persy_memories as list_persy_memories,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    omniscient_overview as omniscient_overview,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    omniscient_query as omniscient_query,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    query as query,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    query_dataset as query_dataset,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    query_persy_memories as query_persy_memories,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    rebuild_dataset_index as rebuild_dataset_index,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    reject_persy_memory as reject_persy_memory,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    rollback_dataset_version as rollback_dataset_version,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    status as status,
)
from app.fastapi_routes.knowledge_v1_part02 import (
    upload_dataset_document as upload_dataset_document,
)

# ruff: noqa: F401

_index = _KnowledgeIndex()
