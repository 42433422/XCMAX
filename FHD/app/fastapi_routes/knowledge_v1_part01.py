# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.knowledge_v1")


from app.fastapi_routes.knowledge_v1_part01_part01 import (
    DatasetDocumentIngestRequest as DatasetDocumentIngestRequest,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    DatasetQueryRequest as DatasetQueryRequest,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    DatasetRebuildRequest as DatasetRebuildRequest,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    DatasetRollbackRequest as DatasetRollbackRequest,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    DatasetVersionDiffRequest as DatasetVersionDiffRequest,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    IngestRequest as IngestRequest,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    IngestResponse as IngestResponse,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    PersyMemoryMutationRequest as PersyMemoryMutationRequest,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    PersyMemoryQueryRequest as PersyMemoryQueryRequest,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    QueryRequest as QueryRequest,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    QueryResponse as QueryResponse,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    StatusResponse as StatusResponse,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    _dataset_access_context_from_request as _dataset_access_context_from_request,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    _dataset_access_payload_from_request as _dataset_access_payload_from_request,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    _dataset_read_tenant_scope as _dataset_read_tenant_scope,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    _ensure_bounded_metadata as _ensure_bounded_metadata,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    _KnowledgeIndex as _KnowledgeIndex,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    _persy_dataset_error as _persy_dataset_error,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    _persy_memory_service as _persy_memory_service,
)
from app.fastapi_routes.knowledge_v1_part01_part01 import (
    _public_dataset_payload as _public_dataset_payload,
)
from app.fastapi_routes.knowledge_v1_part01_part02 import (
    _agent_node_output as _agent_node_output,
)
from app.fastapi_routes.knowledge_v1_part01_part02 import (
    _dataset_agent_user_id as _dataset_agent_user_id,
)
from app.fastapi_routes.knowledge_v1_part01_part02 import (
    _merge_persy_recall as _merge_persy_recall,
)
from app.fastapi_routes.knowledge_v1_part01_part02 import (
    _mirror_ingest_to_persy as _mirror_ingest_to_persy,
)
from app.fastapi_routes.knowledge_v1_part01_part02 import (
    _persy_memory_response as _persy_memory_response,
)
from app.fastapi_routes.knowledge_v1_part01_part02 import (
    _run_dataset_rag_agent as _run_dataset_rag_agent,
)
