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
from typing import Any, Literal, cast

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi import Query as FastAPIQuery
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from app.infrastructure.rag import (
    HybridRetriever,
    RetrievedChunk,
    SemanticChunker,
    get_default_embedder,
    is_rag_enabled,
)
from app.utils.agent_route_status import restore_agent_domain_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge/v1", tags=["knowledge-v1"])

_DATASET_UPLOAD_EXTENSIONS = frozenset(
    {".pdf", ".docx", ".xlsx", ".xls", ".txt", ".md", ".csv", ".json", ".log"}
)
_DATASET_UPLOAD_MAX_BYTES = 25 * 1024 * 1024
_DATASET_INLINE_MAX_CHARS = 5_000_000
_DATASET_METADATA_MAX_BYTES = 64 * 1024
_PERSY_DATASET_ID = "persy-knowledge"
_PUBLIC_KNOWLEDGE_TENANT_ID = "public"


def _ensure_bounded_metadata(value: Any, *, max_bytes: int = _DATASET_METADATA_MAX_BYTES) -> None:
    def walk(item: Any, depth: int = 0) -> None:
        if depth > 8:
            raise ValueError("metadata nesting exceeds 8 levels")
        if isinstance(item, dict):
            if len(item) > 200:
                raise ValueError("metadata has too many fields")
            for key, child in item.items():
                if len(str(key)) > 200:
                    raise ValueError("metadata key is too long")
                walk(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            if len(item) > 1000:
                raise ValueError("metadata list is too long")
            for child in item:
                walk(child, depth + 1)

    walk(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must be JSON serializable") from exc
    if len(encoded) > max_bytes:
        raise ValueError(f"metadata cannot exceed {max_bytes} bytes")


def _public_dataset_payload(value: Any) -> Any:
    """Remove local storage details from HTTP responses without changing service internals."""

    if isinstance(value, dict):
        return {
            str(key): _public_dataset_payload(item)
            for key, item in value.items()
            if not str(key).startswith("_")
            and str(key) not in {"storage_path", "file_path", "vector_index_path"}
        }
    if isinstance(value, list):
        return [_public_dataset_payload(item) for item in value]
    return value


class IngestRequest(BaseModel):
    text: str = Field(
        ..., min_length=1, max_length=_DATASET_INLINE_MAX_CHARS, description="待入库文本"
    )
    source: str = Field("default", max_length=300, description="来源标识")
    chunk_strategy: str = Field(
        "semantic", pattern="^(semantic|fixed)$", description="semantic | fixed"
    )
    chunk_size: int = Field(500, ge=50, le=5000)
    chunk_overlap: int = Field(50, ge=0, le=500)

    @model_validator(mode="after")
    def validate_chunk_window(self):
        if self.chunk_strategy == "fixed" and self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="查询文本")
    top_k: int = Field(5, ge=1, le=50)
    include_citations: bool = Field(True, description="是否返回 [1][2] 引用")


class IngestResponse(BaseModel):
    success: bool
    chunk_count: int
    source: str
    strategy: str
    message: str = ""


class QueryResponse(BaseModel):
    success: bool
    query: str
    chunks: list[dict[str, Any]]
    citations: list[dict[str, Any]] = []
    rag_enabled: bool


class StatusResponse(BaseModel):
    rag_enabled: bool
    embedder_available: bool
    indexed_sources: int
    indexed_chunks: int
    dataset_count: int = 0
    dataset_document_count: int = 0
    dataset_chunk_count: int = 0
    semantic_embedding_available: bool = False
    recommended_dataset_id: str = _PERSY_DATASET_ID


class DatasetDocumentIngestRequest(BaseModel):
    text: str = Field("", max_length=_DATASET_INLINE_MAX_CHARS, description="inline document text")
    file_path: str = Field("", max_length=4096, description="allowed local file path")
    source: str = Field("", max_length=300, description="source label")
    document_id: str = Field("", max_length=200, description="optional stable document id")
    tenant_id: str = Field("", max_length=160, description="tenant/user isolation key")
    version: str = Field(
        "", max_length=80, description="document version number, vN, or empty for auto increment"
    )
    version_label: str = Field("", max_length=120, description="optional display version label")
    chunk_strategy: str = Field(
        "semantic", pattern="^(semantic|fixed)$", description="semantic | fixed"
    )
    chunk_size: int = Field(500, ge=50, le=5000)
    chunk_overlap: int = Field(50, ge=0, le=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _ensure_bounded_metadata(value)
        return value

    @model_validator(mode="after")
    def validate_document_input(self):
        if not self.text.strip() and not self.file_path.strip():
            raise ValueError("text or file_path is required")
        if self.chunk_strategy == "fixed" and self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class DatasetQueryRequest(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=2000, description="question or retrieval query"
    )
    top_k: int = Field(5, ge=1, le=50)
    include_answer: bool = Field(True, description="return deterministic answer with citations")
    tenant_id: str = Field("", max_length=160, description="tenant/user isolation key")
    version: str = Field(
        "", max_length=80, description="document version number, vN, latest, or empty"
    )
    metadata_filter: dict[str, Any] = Field(default_factory=dict)
    rerank: bool = Field(False, description="apply cross-encoder reranking with safe fallback")
    include_public: bool = Field(
        True,
        description="include published public knowledge with the caller tenant scope",
    )

    @field_validator("metadata_filter")
    @classmethod
    def validate_metadata_filter(cls, value: dict[str, Any]) -> dict[str, Any]:
        _ensure_bounded_metadata(value)
        return value


class DatasetPublicationRequest(BaseModel):
    status: Literal["draft", "published", "archived"]
    reason: str = Field(..., min_length=4, max_length=500)
    expected_status: Literal["draft", "published", "archived"] | None = None


class DatasetVersionDiffRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=300, description="document source label")
    tenant_id: str = Field("", max_length=160, description="tenant/user isolation key")
    from_version: str = Field(
        ..., min_length=1, max_length=120, description="source version number, vN, or label"
    )
    to_version: str = Field(
        "latest", max_length=120, description="target version number, vN, label, or latest"
    )


class DatasetRollbackRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=300, description="document source label")
    tenant_id: str = Field("", max_length=160, description="tenant/user isolation key")
    target_version: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="version to restore into a new latest version",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _ensure_bounded_metadata(value)
        return value


class DatasetRebuildRequest(BaseModel):
    tenant_id: str = Field("", max_length=160, description="tenant/user isolation key")
    metadata_filter: dict[str, Any] = Field(default_factory=dict)
    background: bool = Field(True, description="run index rebuild in a background thread")
    max_attempts: int = Field(1, ge=1, le=5)

    @field_validator("metadata_filter")
    @classmethod
    def validate_metadata_filter(cls, value: dict[str, Any]) -> dict[str, Any]:
        _ensure_bounded_metadata(value)
        return value


class PersyMemoryQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)
    reinforce: bool = Field(True)


class PersyMemoryMutationRequest(BaseModel):
    key: str | None = Field(None, max_length=160)
    value: Any = None
    memory_type: str | None = Field(None, max_length=32)
    confidence: float | None = Field(None, ge=0, le=1)
    reason: str = Field("", max_length=500)

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: Any) -> Any:
        if value is not None:
            _ensure_bounded_metadata(value, max_bytes=16 * 1024)
        return value


class _KnowledgeIndex:
    """进程内单例：保存所有 chunk + 检索器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chunker = SemanticChunker(embedder=get_default_embedder())
        self._retriever = HybridRetriever(embedder=get_default_embedder())
        self._chunks: list[RetrievedChunk] = []
        self._sources: set[str] = set()
        self._rebuild_needed: bool = True

    def ingest(
        self, text: str, source: str, strategy: str, chunk_size: int, chunk_overlap: int
    ) -> int:
        with self._lock:
            if strategy == "semantic":
                chunks = self._chunker.split_by_semantic(text)
            else:
                chunks = self._chunker.split_by_fixed(
                    text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
                )
            base = len(self._chunks)
            for i, c in enumerate(chunks):
                self._chunks.append(
                    RetrievedChunk(
                        text=c.text,
                        score=0.0,
                        source=source,
                        chunk_index=base + i,
                        char_start=c.char_start,
                        char_end=c.char_end,
                        metadata={"source": source, "strategy": c.strategy},
                    )
                )
            self._sources.add(source)
            self._rebuild_needed = True
            return len(chunks)

    def query(self, q: str, top_k: int) -> list[RetrievedChunk]:
        with self._lock:
            if self._rebuild_needed:
                self._retriever.index(self._chunks)
                self._rebuild_needed = False
            return cast("list[Any]", self._retriever.retrieve(q))

    def status(self) -> dict[str, int]:
        with self._lock:
            return {
                "sources": len(self._sources),
                "chunks": len(self._chunks),
            }


_index = _KnowledgeIndex()


def _dataset_access_context_from_request(request: Request) -> Any | None:
    from app.fastapi_routes.dataset_access import dataset_access_context_from_request

    return dataset_access_context_from_request(request)


def _dataset_access_payload_from_request(request: Request) -> dict[str, Any]:
    from app.fastapi_routes.dataset_access import dataset_access_payload_from_request

    return dataset_access_payload_from_request(request)


def _dataset_read_tenant_scope(access: Any | None) -> str:
    """Tenant filter for per-dataset status/graph reads.

    Omniscient overview counts all tenants inside each dataset for admins. Per-dataset
    status/graph must use the same scope; otherwise admin console shows e.g. 1013 docs
    in the strip while the active space graph stays empty (filtered by admin's
    synthetic ``platform`` tenant).
    """

    if access is None:
        return _PUBLIC_KNOWLEDGE_TENANT_ID
    if bool(getattr(access, "is_admin", False)):
        return ""
    permissions = getattr(access, "permissions", None) or ()
    try:
        from app.application.dataset_rag_app_service import DATASET_ADMIN_PERMISSION

        if DATASET_ADMIN_PERMISSION in permissions:
            return ""
    except Exception:  # noqa: BLE001 - keep read path resilient
        pass
    return str(getattr(access, "tenant_id", "") or "")


def _dataset_admin_access(access: Any | None) -> bool:
    if access is None:
        return False
    if bool(getattr(access, "is_admin", False)):
        return True
    permissions = getattr(access, "permissions", None) or ()
    return "dataset.admin" in permissions or "*" in permissions


def _private_scope_requires_auth(tenant_id: str, access: Any | None) -> JSONResponse | None:
    requested = str(tenant_id or "").strip()
    if access is not None or not requested or requested == _PUBLIC_KNOWLEDGE_TENANT_ID:
        return None
    return JSONResponse(
        {
            "success": False,
            "error_code": "dataset_auth_required",
            "message": "企业私有知识需要登录后访问",
        },
        status_code=401,
    )


def _persy_memory_service():
    from app.application.persy_memory_app_service import get_persy_memory_app_service

    return get_persy_memory_app_service()


def _persy_dataset_error(dataset_id: str) -> JSONResponse | None:
    if str(dataset_id or "").strip() == _PERSY_DATASET_ID:
        return None
    return JSONResponse(
        {
            "success": False,
            "message": "Persy memory is only available for the Persy knowledge dataset",
            "error_code": "persy_dataset_required",
        },
        status_code=404,
    )


def _persy_memory_response(
    payload: dict[str, Any],
    *,
    request: Request,
    action: str,
) -> JSONResponse:
    success = bool(payload.get("success"))
    code = str(payload.get("error_code") or "")
    status_code = 200 if success else 400
    if code in {"dataset_permission_denied", "persy_memory_scope_missing"}:
        status_code = 403
    elif code == "persy_memory_not_found":
        status_code = 404
    try:
        from app.utils import audit_logger

        access = _dataset_access_context_from_request(request)
        audit_logger.audit_log(
            f"persy_memory_{action}",
            getattr(access, "actor_id", "") if access is not None else "",
            str(getattr(getattr(request, "client", None), "host", "") or ""),
            {
                "success": success,
                "memory_id": str(
                    (payload.get("memory") or {}).get("memory_id")
                    if isinstance(payload.get("memory"), dict)
                    else ""
                ),
                "error_code": code,
            },
            success=success,
        )
    except Exception:  # noqa: BLE001 - audit must never break a user mutation
        logger.debug("Persy memory audit unavailable", exc_info=True)
    return JSONResponse(payload, status_code=status_code)


def _merge_persy_recall(
    payload: dict[str, Any],
    *,
    request: Request,
    params: dict[str, Any],
) -> dict[str, Any]:
    from app.application.erp_domain_ontology import (
        query_erp_ontology,
        summarize_erp_ontology_chunks,
    )

    if str(params.get("dataset_id") or "") != _PERSY_DATASET_ID or not payload.get("success"):
        return payload
    query_text = str(params.get("query") or "").strip()
    if not query_text:
        return payload
    memory_result = _persy_memory_service().query(
        access_context=_dataset_access_context_from_request(request),
        query=query_text,
        top_k=max(1, min(int(params.get("top_k") or 5), 20)),
        reinforce=True,
    )
    result = dict(payload)
    result["persy_memory"] = {
        "available": bool(memory_result.get("success")),
        "count": len(memory_result.get("chunks") or []),
        "retriever": str(memory_result.get("retriever") or ""),
    }
    if not memory_result.get("success"):
        result["persy_memory"]["error_code"] = str(memory_result.get("error_code") or "")
        memory_chunks: list[dict[str, Any]] = []
    else:
        memory_chunks = [
            dict(chunk) for chunk in memory_result.get("chunks", []) if isinstance(chunk, dict)
        ]

    knowledge_chunks = [
        dict(chunk) for chunk in payload.get("chunks", []) if isinstance(chunk, dict)
    ]
    erp_result = query_erp_ontology(
        query_text,
        top_k=max(1, min(int(params.get("top_k") or 5), 12)),
    )
    erp_chunks = [dict(chunk) for chunk in erp_result.get("chunks", []) if isinstance(chunk, dict)]
    result["erp_ontology"] = {
        "available": bool(erp_result.get("success")),
        "count": len(erp_chunks),
        "retriever": str(erp_result.get("retriever") or ""),
        "ontology_version": str(erp_result.get("ontology_version") or ""),
    }
    seen: set[str] = set()
    merged_chunks: list[dict[str, Any]] = []
    for chunk in sorted(
        [*memory_chunks, *erp_chunks, *knowledge_chunks],
        key=lambda item: float(item.get("score") or 0.0),
        reverse=True,
    ):
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        fingerprint = str(
            metadata.get("memory_id")
            or metadata.get("erp_ontology_id")
            or metadata.get("document_id")
            or f"{chunk.get('source')}:{chunk.get('chunk_index')}:{chunk.get('text')}"
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        merged_chunks.append(chunk)
    result["chunks"] = merged_chunks[: max(2, min(int(params.get("top_k") or 5) * 2, 40))]

    citations = [
        dict(citation) for citation in payload.get("citations", []) if isinstance(citation, dict)
    ]
    for chunk in memory_chunks:
        memory_metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        citations.append(
            {
                "index": len(citations) + 1,
                "source": "对话记忆",
                "text": str(chunk.get("text") or ""),
                "score": chunk.get("score"),
                "memory_id": memory_metadata.get("memory_id"),
            }
        )
    for chunk in erp_chunks:
        erp_metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        citations.append(
            {
                "index": len(citations) + 1,
                "source": "ERP 领域本体",
                "text": str(chunk.get("text") or ""),
                "score": chunk.get("score"),
                "erp_ontology_id": erp_metadata.get("erp_ontology_id"),
                "symbolic_expression": erp_metadata.get("symbolic_expression"),
            }
        )
    result["citations"] = citations

    if (memory_chunks or erp_chunks) and params.get("include_answer", True):
        memory_summary = "；".join(
            str(chunk.get("text") or "").strip()[:180]
            for chunk in memory_chunks[:3]
            if str(chunk.get("text") or "").strip()
        )
        erp_summary = summarize_erp_ontology_chunks(erp_chunks)
        knowledge_answer = str(payload.get("answer") or "").strip()
        memory_answer = f"已确认的长期记忆：{memory_summary}。" if memory_summary else ""
        erp_answer = f"ERP 领域规则：{erp_summary}。" if erp_summary else ""
        result["answer"] = "\n\n".join(
            part for part in (erp_answer, memory_answer, knowledge_answer) if part
        )
    return result


def _agent_node_output(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success") and getattr(run, "error", "") and not output.get("message"):
        output["message"] = getattr(run, "error", "")
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return restore_agent_domain_error(cast("dict[str, Any]", _public_dataset_payload(output)))


def _dataset_agent_user_id(request: Request, params: dict[str, Any]) -> str:
    access_context = (
        params.get("access_context") if isinstance(params.get("access_context"), dict) else {}
    )
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or access_context.get("actor_id")
        or params.get("actor_id")
        or params.get("user_id")
        or params.get("tenant_id")
        or "dataset-rag-route"
    ).strip()


def _run_dataset_rag_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> JSONResponse:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry

    data = dict(params or {})
    access_payload = _dataset_access_payload_from_request(request)
    if not access_payload:
        if action == "query":
            requested_tenant = str(data.get("tenant_id") or "").strip()
            if requested_tenant and requested_tenant != _PUBLIC_KNOWLEDGE_TENANT_ID:
                return JSONResponse(
                    {
                        "success": False,
                        "error_code": "dataset_auth_required",
                        "message": "企业私有知识需要登录后访问",
                    },
                    status_code=401,
                )
            data["tenant_id"] = _PUBLIC_KNOWLEDGE_TENANT_ID
            data["include_public"] = False
            metadata_filter = (
                dict(data.get("metadata_filter"))
                if isinstance(data.get("metadata_filter"), dict)
                else {}
            )
            metadata_filter["publication_status"] = "published"
            data["metadata_filter"] = metadata_filter
        else:
            return JSONResponse(
                {
                    "success": False,
                    "error_code": "dataset_auth_required",
                    "message": "知识库写入和治理需要登录",
                },
                status_code=401,
            )
    if access_payload:
        data["access_context"] = access_payload
        if access_payload.get("tenant_id"):
            if not str(data.get("tenant_id") or "").strip():
                data["tenant_id"] = access_payload["tenant_id"]
    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("dataset_rag") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return JSONResponse(
            {"success": False, "message": f"未注册的 Dataset/RAG 动作: {action}"},
            status_code=400,
        )

    node_id = f"dataset_rag_{action}"
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 dataset_rag.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="dataset_rag",
                action=action,
                params=data,
                risk=str(action_meta.get("risk") or "medium"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute dataset_rag.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "medium"),
        metadata={"source": "dataset_rag_route", "route": route_path},
    )
    user_id = _dataset_agent_user_id(request, data)
    runtime_context = {
        "source": "dataset_rag_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
    }
    if access_payload:
        runtime_context["dataset_access_context"] = access_payload
        if access_payload.get("tenant_id"):
            runtime_context["dataset_tenant_id"] = access_payload["tenant_id"]
        runtime_context["dataset_permissions"] = list(access_payload.get("permissions") or [])
        runtime_context["dataset_admin"] = bool(access_payload.get("is_admin"))

    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(data.get("message") or f"Dataset/RAG {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "dataset-rag-route",
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued

    payload = _agent_node_output(run, node_id)
    if action == "query":
        payload = _merge_persy_recall(payload, request=request, params=data)
    if run.status in {"waiting_user", "blocked"}:
        status_code = 202
    elif payload.get("error_code") == "tool_exception":
        status_code = 500
    else:
        # Keep the established Dataset/RAG route contract: domain-level
        # failures are returned as a 200 payload with success=false.  Several
        # desktop clients already branch on error_code instead of HTTP status.
        status_code = 200
    return JSONResponse(payload, status_code=status_code)


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
    try:
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        access = _dataset_access_context_from_request(request) if request is not None else None
        return cast(
            "dict[str, Any]",
            get_dataset_rag_app_service().ingest_document(
                dataset_id=_PERSY_DATASET_ID,
                source=source or "legacy-ingest",
                text=text,
                chunk_strategy=chunk_strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                metadata={"entrypoint": "legacy_ingest_mirror"},
                access_context=access,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - mirror must not break legacy contract
        logger.warning("mirror ingest to persy-knowledge failed: %s", exc)
        return {"success": False, "message": str(exc)}


def _knowledge_runtime_snapshot(request: Request | None = None) -> dict[str, Any]:
    legacy = _index.status()
    dataset_count = 0
    dataset_docs = 0
    dataset_chunks = 0
    recommended = _PERSY_DATASET_ID
    try:
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        access = _dataset_access_context_from_request(request) if request is not None else None
        overview = get_dataset_rag_app_service().status(access_context=access)
        datasets = overview.get("datasets") if isinstance(overview, dict) else {}
        if isinstance(datasets, dict):
            dataset_count = len(datasets)
            dataset_docs = int(overview.get("document_count") or 0)
            dataset_chunks = int(overview.get("chunk_count") or 0)
            nonempty = [
                (key, int((val or {}).get("document_count") or 0))
                for key, val in datasets.items()
                if isinstance(val, dict)
            ]
            nonempty.sort(key=lambda item: item[1], reverse=True)
            persy_docs = next((n for key, n in nonempty if key == _PERSY_DATASET_ID), 0)
            if persy_docs <= 0 and nonempty and nonempty[0][1] > 0:
                recommended = nonempty[0][0]
    except Exception as exc:  # noqa: BLE001
        logger.debug("dataset overview for health failed: %s", exc)
    embedder_ok = get_default_embedder() is not None
    return {
        "rag_enabled": is_rag_enabled(),
        "embedder_available": embedder_ok,
        "semantic_embedding_available": embedder_ok,
        "indexed_sources": int(legacy.get("sources") or 0) + dataset_docs,
        "indexed_chunks": int(legacy.get("chunks") or 0) + dataset_chunks,
        "legacy_indexed_sources": int(legacy.get("sources") or 0),
        "legacy_indexed_chunks": int(legacy.get("chunks") or 0),
        "dataset_count": dataset_count,
        "dataset_document_count": dataset_docs,
        "dataset_chunk_count": dataset_chunks,
        "recommended_dataset_id": recommended,
    }


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, request: Request) -> IngestResponse:
    try:
        count = _index.ingest(
            req.text, req.source, req.chunk_strategy, req.chunk_size, req.chunk_overlap
        )
        mirrored = _mirror_ingest_to_persy(
            text=req.text,
            source=req.source,
            chunk_strategy=req.chunk_strategy,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            request=request,
        )
        mirror_note = ""
        if mirrored.get("success"):
            mirror_note = f"；已同步 Persy +{int(mirrored.get('chunk_count') or 0)} chunk"
        return IngestResponse(
            success=True,
            chunk_count=count,
            source=req.source,
            strategy=req.chunk_strategy,
            message=f"已入库 {count} 个 chunk{mirror_note}",
        )
    except (ValueError, TypeError) as e:
        return IngestResponse(
            success=False,
            chunk_count=0,
            source=req.source,
            strategy=req.chunk_strategy,
            message=str(e),
        )


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    chunks = _index.query(req.query, req.top_k)
    return QueryResponse(
        success=True,
        query=req.query,
        chunks=[
            {"chunk_index": c.chunk_index, "text": c.text, "score": c.score, "source": c.source}
            for c in chunks
        ],
        citations=[],
        rag_enabled=is_rag_enabled(),
    )


@router.post("/datasets/{dataset_id}/documents")
def ingest_dataset_document(
    dataset_id: str,
    req: DatasetDocumentIngestRequest,
    request: Request,
) -> JSONResponse:
    return _run_dataset_rag_agent(
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
    metadata_json: str = Form("{}"),
) -> JSONResponse:
    raw_name = Path(str(file.filename or "document")).name
    suffix = Path(raw_name).suffix.lower()
    stem_limit = max(1, 240 - len(suffix))
    original_name = f"{Path(raw_name).stem[:stem_limit]}{suffix}"
    if suffix not in _DATASET_UPLOAD_EXTENSIONS:
        return JSONResponse(
            {
                "success": False,
                "message": f"不支持的资料类型: {suffix or '无扩展名'}",
                "allowed_extensions": sorted(_DATASET_UPLOAD_EXTENSIONS),
            },
            status_code=400,
        )
    source_label = str(source or original_name).strip() or original_name
    if len(source_label) > 300:
        return JSONResponse(
            {"success": False, "message": "资料名称不能超过 300 个字符"},
            status_code=400,
        )
    if any(
        len(str(value or "")) > limit
        for value, limit in (
            (tenant_id, 160),
            (version, 80),
            (version_label, 120),
            (metadata_json, _DATASET_METADATA_MAX_BYTES),
        )
    ):
        return JSONResponse(
            {"success": False, "message": "上传参数过长"},
            status_code=400,
        )
    try:
        parsed_metadata = json.loads(metadata_json or "{}")
        if not isinstance(parsed_metadata, dict):
            raise ValueError("资料元数据必须是 JSON 对象")
        _ensure_bounded_metadata(parsed_metadata)
    except (json.JSONDecodeError, ValueError) as exc:
        return JSONResponse(
            {"success": False, "message": f"资料元数据无效: {exc}"},
            status_code=400,
        )

    from app.utils.path_utils import get_upload_dir

    safe_dataset = re.sub(r"[^A-Za-z0-9._-]+", "_", str(dataset_id or "default"))[:100]
    upload_dir = Path(get_upload_dir()).resolve() / "knowledge" / (safe_dataset or "default")
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_path = upload_dir / f"{uuid.uuid4().hex}{suffix}"
    size = 0
    try:
        with saved_path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > _DATASET_UPLOAD_MAX_BYTES:
                    raise ValueError("资料文件不能超过 25 MB")
                target.write(chunk)
    except (OSError, ValueError) as exc:
        saved_path.unlink(missing_ok=True)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    finally:
        await file.close()

    response = _run_dataset_rag_agent(
        request=request,
        action="ingest_document",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/upload",
        params={
            "dataset_id": dataset_id,
            "source": source_label,
            "file_path": str(saved_path),
            "text": "",
            "document_id": "",
            "chunk_strategy": chunk_strategy
            if chunk_strategy in {"semantic", "fixed"}
            else "semantic",
            "chunk_size": 500,
            "chunk_overlap": 50,
            "metadata": {
                **parsed_metadata,
                "original_file_name": original_name,
                "upload_size_bytes": size,
                "entrypoint": "persy_knowledge_upload",
            },
            "tenant_id": tenant_id,
            "version": version,
            "version_label": version_label,
        },
    )
    if response.status_code >= 400:
        try:
            saved_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to clean rejected Persy upload: %s", saved_path)
    return response


@router.post("/datasets/{dataset_id}/query")
def query_dataset(
    dataset_id: str,
    req: DatasetQueryRequest,
    request: Request,
) -> JSONResponse:
    return _run_dataset_rag_agent(
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
            "include_public": req.include_public,
        },
    )


@router.get("/datasets")
def dataset_status_all(request: Request) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    access = _dataset_access_context_from_request(request)
    return cast(
        "dict[str, Any]",
        _public_dataset_payload(
            get_dataset_rag_app_service().status(
                tenant_id=_dataset_read_tenant_scope(access),
                access_context=access,
            )
        ),
    )


@router.get("/datasets/{dataset_id}/status")
def dataset_status(
    dataset_id: str,
    request: Request,
    tenant_id: str = FastAPIQuery(
        "",
        max_length=160,
        description="Admin-only explicit tenant scope; regular users remain session-scoped",
    ),
    include_documents: bool = FastAPIQuery(
        True,
        description="When false, omit document rows (counts/index only) for lighter graph HUD loads",
    ),
) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    access = _dataset_access_context_from_request(request)
    denied = _private_scope_requires_auth(tenant_id, access)
    if denied is not None:
        return denied
    return cast(
        "dict[str, Any]",
        _public_dataset_payload(
            get_dataset_rag_app_service().status(
                dataset_id,
                tenant_id=tenant_id.strip() or _dataset_read_tenant_scope(access),
                access_context=access,
                include_documents=bool(include_documents),
            )
        ),
    )


@router.get("/datasets/{dataset_id}/graph")
def dataset_graph(
    dataset_id: str,
    request: Request,
    limit: int = FastAPIQuery(80, ge=20, le=240),
    tenant_id: str = FastAPIQuery(
        "",
        max_length=160,
        description="Admin-only explicit tenant scope; regular users remain session-scoped",
    ),
) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service
    from app.application.erp_domain_ontology import (
        build_erp_ontology_graph,
        merge_erp_ontology_graph,
    )
    from app.application.persy_memory_app_service import merge_memory_graph

    access = _dataset_access_context_from_request(request)
    denied = _private_scope_requires_auth(tenant_id, access)
    if denied is not None:
        return denied
    tenant_id = tenant_id.strip() or _dataset_read_tenant_scope(access)
    memory_graph: dict[str, Any] = {"success": True, "nodes": [], "edges": [], "stats": {}}
    erp_graph: dict[str, Any] = {"success": True, "nodes": [], "edges": [], "stats": {}}
    graph_limit = limit
    if dataset_id == _PERSY_DATASET_ID:
        memory_graph = _persy_memory_service().graph(
            access_context=access,
            limit=max(8, min(40, int(limit * 0.28))),
        )
        erp_graph = build_erp_ontology_graph(
            dataset_id=dataset_id,
            limit=max(24, min(64, int(limit * 0.56))),
        )
        if memory_graph.get("nodes"):
            graph_limit = max(20, int(limit * 0.38))
        else:
            graph_limit = max(20, int(limit * 0.48))
    base_graph = get_dataset_rag_app_service().knowledge_graph(
        dataset_id,
        tenant_id=tenant_id,
        limit=graph_limit,
        access_context=access,
    )
    if not base_graph.get("success") or not memory_graph.get("success"):
        return cast("dict[str, Any]", _public_dataset_payload(base_graph))
    merged_graph = merge_memory_graph(base_graph, memory_graph, limit=limit)
    if erp_graph.get("success"):
        merged_graph = merge_erp_ontology_graph(merged_graph, erp_graph, limit=limit)
    return cast("dict[str, Any]", _public_dataset_payload(merged_graph))


@router.get("/datasets/{dataset_id}/memories")
def list_persy_memories(
    dataset_id: str,
    request: Request,
    status: str = FastAPIQuery(""),
    memory_type: str = FastAPIQuery(""),
    limit: int = FastAPIQuery(200, ge=1, le=1000),
) -> JSONResponse:
    unsupported = _persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    payload = _persy_memory_service().list_memories(
        access_context=_dataset_access_context_from_request(request),
        status=status,
        memory_type=memory_type,
        limit=limit,
    )
    code = str(payload.get("error_code") or "")
    status_code = 200 if payload.get("success") else 400
    if code in {"dataset_permission_denied", "persy_memory_scope_missing"}:
        status_code = 403
    return JSONResponse(payload, status_code=status_code)


@router.post("/datasets/{dataset_id}/memories/query")
def query_persy_memories(
    dataset_id: str,
    req: PersyMemoryQueryRequest,
    request: Request,
) -> JSONResponse:
    unsupported = _persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    payload = _persy_memory_service().query(
        access_context=_dataset_access_context_from_request(request),
        query=req.query,
        top_k=req.top_k,
        reinforce=req.reinforce,
    )
    code = str(payload.get("error_code") or "")
    status_code = 200 if payload.get("success") else 400
    if code in {"dataset_permission_denied", "persy_memory_scope_missing"}:
        status_code = 403
    return JSONResponse(payload, status_code=status_code)


@router.post("/datasets/{dataset_id}/memories/{memory_id}/confirm")
def confirm_persy_memory(
    dataset_id: str,
    memory_id: str,
    req: PersyMemoryMutationRequest,
    request: Request,
) -> JSONResponse:
    unsupported = _persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    correction = {
        key: getattr(req, key)
        for key in ("key", "value", "memory_type", "confidence")
        if key in req.model_fields_set
    }
    payload = _persy_memory_service().mutate(
        access_context=_dataset_access_context_from_request(request),
        memory_id=memory_id,
        action="confirm",
        patch=correction,
        reason=req.reason,
    )
    return _persy_memory_response(payload, request=request, action="confirm")


@router.post("/datasets/{dataset_id}/memories/{memory_id}/reject")
def reject_persy_memory(
    dataset_id: str,
    memory_id: str,
    req: PersyMemoryMutationRequest,
    request: Request,
) -> JSONResponse:
    unsupported = _persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    payload = _persy_memory_service().mutate(
        access_context=_dataset_access_context_from_request(request),
        memory_id=memory_id,
        action="reject",
        reason=req.reason,
    )
    return _persy_memory_response(payload, request=request, action="reject")


@router.patch("/datasets/{dataset_id}/memories/{memory_id}")
def correct_persy_memory(
    dataset_id: str,
    memory_id: str,
    req: PersyMemoryMutationRequest,
    request: Request,
) -> JSONResponse:
    unsupported = _persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    patch = {key: getattr(req, key) for key in ("key", "value") if key in req.model_fields_set}
    payload = _persy_memory_service().mutate(
        access_context=_dataset_access_context_from_request(request),
        memory_id=memory_id,
        action="correct",
        patch=patch,
        reason=req.reason,
    )
    return _persy_memory_response(payload, request=request, action="correct")


@router.delete("/datasets/{dataset_id}/memories/{memory_id}")
def delete_persy_memory(
    dataset_id: str,
    memory_id: str,
    request: Request,
    reason: str = FastAPIQuery("", max_length=500),
) -> JSONResponse:
    unsupported = _persy_dataset_error(dataset_id)
    if unsupported is not None:
        return unsupported
    payload = _persy_memory_service().mutate(
        access_context=_dataset_access_context_from_request(request),
        memory_id=memory_id,
        action="delete",
        reason=reason,
    )
    return _persy_memory_response(payload, request=request, action="delete")


@router.post("/datasets/{dataset_id}/versions/diff")
def diff_dataset_versions(
    dataset_id: str,
    req: DatasetVersionDiffRequest,
    request: Request,
) -> JSONResponse:
    return _run_dataset_rag_agent(
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


@router.post("/datasets/{dataset_id}/versions/rollback")
def rollback_dataset_version(
    dataset_id: str,
    req: DatasetRollbackRequest,
    request: Request,
) -> JSONResponse:
    return _run_dataset_rag_agent(
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


@router.post("/datasets/{dataset_id}/index/rebuild")
def rebuild_dataset_index(
    dataset_id: str,
    req: DatasetRebuildRequest,
    request: Request,
) -> JSONResponse:
    return _run_dataset_rag_agent(
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


@router.post("/datasets/{dataset_id}/index/rebuild/{job_id}/cancel")
def cancel_dataset_rebuild_job(
    dataset_id: str,
    job_id: str,
    request: Request,
) -> JSONResponse:
    return _run_dataset_rag_agent(
        request=request,
        action="cancel_rebuild",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/index/rebuild/{job_id}/cancel",
        params={
            "dataset_id": dataset_id,
            "job_id": job_id,
        },
    )


@router.get("/datasets/{dataset_id}/index/rebuild/{job_id}")
def dataset_rebuild_job(dataset_id: str, job_id: str, request: Request) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    return cast(
        "dict[str, Any]",
        _public_dataset_payload(
            get_dataset_rag_app_service().get_rebuild_job(
                dataset_id,
                job_id,
                access_context=_dataset_access_context_from_request(request),
            )
        ),
    )


@router.delete("/datasets/{dataset_id}/documents/{document_id}")
def delete_dataset_document(dataset_id: str, document_id: str, request: Request) -> JSONResponse:
    return _run_dataset_rag_agent(
        request=request,
        action="delete_document",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/{document_id}",
        params={
            "dataset_id": dataset_id,
            "document_id": document_id,
        },
    )


@router.patch("/datasets/{dataset_id}/documents/{document_id}/publication")
def update_dataset_document_publication(
    dataset_id: str,
    document_id: str,
    req: DatasetPublicationRequest,
    request: Request,
) -> JSONResponse:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    access = _dataset_access_context_from_request(request)
    if not _dataset_admin_access(access):
        return JSONResponse(
            {
                "success": False,
                "error_code": "dataset_permission_denied",
                "message": "dataset.admin permission is required",
                "required_permission": "dataset.admin",
            },
            status_code=403,
        )
    payload = get_dataset_rag_app_service().set_document_publication_status(
        dataset_id,
        document_id,
        req.status,
        reason=req.reason,
        expected_status=req.expected_status,
        access_context=access,
    )
    error_code = str(payload.get("error_code") or "")
    status_code = 200
    if not payload.get("success"):
        if error_code == "dataset_permission_denied":
            status_code = 403
        elif error_code == "dataset_document_not_found":
            status_code = 404
        elif error_code == "dataset_publication_conflict":
            status_code = 409
        else:
            status_code = 400
    try:
        from app.utils import audit_logger

        audit_logger.audit_log(
            "knowledge_publication_change",
            str(getattr(access, "actor_id", "") or ""),
            str(getattr(getattr(request, "client", None), "host", "") or ""),
            {
                "dataset_id": dataset_id,
                "document_id": document_id,
                "target_status": req.status,
                "expected_status": req.expected_status,
                "reason": req.reason,
                "previous_status": payload.get("previous_status"),
                "error_code": error_code,
            },
            success=bool(payload.get("success")),
        )
    except Exception:  # noqa: BLE001 - publication result must still be returned
        logger.exception("knowledge publication audit failed")
    return JSONResponse(
        cast("dict[str, Any]", _public_dataset_payload(payload)),
        status_code=status_code,
    )


@router.get("/status", response_model=StatusResponse)
def status(request: Request) -> StatusResponse:
    snap = _knowledge_runtime_snapshot(request)
    return StatusResponse(
        rag_enabled=bool(snap["rag_enabled"]),
        embedder_available=bool(snap["embedder_available"]),
        indexed_sources=int(snap["indexed_sources"]),
        indexed_chunks=int(snap["indexed_chunks"]),
        dataset_count=int(snap["dataset_count"]),
        dataset_document_count=int(snap["dataset_document_count"]),
        dataset_chunk_count=int(snap["dataset_chunk_count"]),
        semantic_embedding_available=bool(snap["semantic_embedding_available"]),
        recommended_dataset_id=str(snap["recommended_dataset_id"]),
    )


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    snap = _knowledge_runtime_snapshot(request)
    return {"success": True, **snap}


@router.get("/omniscient")
def omniscient_overview(request: Request) -> dict[str, Any]:
    """Admin/full-knowledge overview across all governed datasets."""
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    access = _dataset_access_context_from_request(request)
    if not _dataset_admin_access(access):
        return cast(
            "dict[str, Any]",
            JSONResponse(
                {
                    "success": False,
                    "error_code": "dataset_admin_required",
                    "message": "全知知识视图仅限管理员",
                },
                status_code=403,
            ),
        )
    overview = get_dataset_rag_app_service().status(access_context=access)
    snap = _knowledge_runtime_snapshot(request)
    datasets = overview.get("datasets") if isinstance(overview, dict) else {}
    return cast(
        "dict[str, Any]",
        _public_dataset_payload(
            {
                "success": True,
                "omniscient": True,
                "rag_enabled": snap["rag_enabled"],
                "embedder_available": snap["embedder_available"],
                "semantic_embedding_available": snap["semantic_embedding_available"],
                "recommended_dataset_id": snap["recommended_dataset_id"],
                "dataset_count": snap["dataset_count"],
                "document_count": snap["dataset_document_count"],
                "chunk_count": snap["dataset_chunk_count"],
                "datasets": datasets if isinstance(datasets, dict) else {},
                "is_admin": bool(getattr(access, "is_admin", False)) if access else False,
            }
        ),
    )


@router.post("/omniscient/query")
def omniscient_query(req: QueryRequest, request: Request) -> dict[str, Any]:
    """Query across all datasets visible to the caller (admin = full platform)."""
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    access = _dataset_access_context_from_request(request)
    if not _dataset_admin_access(access):
        return cast(
            "dict[str, Any]",
            JSONResponse(
                {
                    "success": False,
                    "error_code": "dataset_admin_required",
                    "message": "全知知识检索仅限管理员",
                },
                status_code=403,
            ),
        )
    service = get_dataset_rag_app_service()
    overview = service.status(access_context=access)
    datasets = overview.get("datasets") if isinstance(overview, dict) else {}
    merged: list[dict[str, Any]] = []
    if isinstance(datasets, dict):
        per_ds = max(1, min(int(req.top_k), 20))
        for dataset_id in datasets:
            result = service.query(
                dataset_id=str(dataset_id),
                query=req.query,
                top_k=per_ds,
                access_context=access,
                rerank=True,
            )
            if not result.get("success"):
                continue
            for chunk in result.get("chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                item = dict(chunk)
                item["dataset_id"] = str(dataset_id)
                merged.append(item)
    merged.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    top = merged[: max(1, min(int(req.top_k), 50))]
    return {
        "success": True,
        "query": req.query,
        "chunks": top,
        "citations": [],
        "rag_enabled": is_rag_enabled(),
        "omniscient": True,
        "dataset_hits": len({str(c.get("dataset_id") or "") for c in top if c.get("dataset_id")}),
    }
