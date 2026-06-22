"""知识库 API（V1 简化版）。

Phase 3.3 交付：
  - POST /api/knowledge/v1/ingest   — 文本入库（语义分块 + 内存索引）
  - POST /api/knowledge/v1/query    — 检索（混合 + 引用）
  - GET  /api/knowledge/v1/status   — 健康检查
  - GET  /api/knowledge/v1/health   — 详细状态

生产应代理到 MODstore `/api/knowledge/v2/*`；本地开发可用此简化版。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.infrastructure.rag import (
    HybridRetriever,
    RetrievedChunk,
    SemanticChunker,
    get_default_embedder,
    is_rag_enabled,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/knowledge/v1", tags=["knowledge-v1"])


class IngestRequest(BaseModel):
    text: str = Field(..., description="待入库文本")
    source: str = Field("default", description="来源标识")
    chunk_strategy: str = Field("semantic", description="semantic | fixed")
    chunk_size: int = Field(500, ge=50, le=5000)
    chunk_overlap: int = Field(50, ge=0, le=500)


class QueryRequest(BaseModel):
    query: str = Field(..., description="查询文本")
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


class DatasetDocumentIngestRequest(BaseModel):
    text: str = Field("", description="inline document text")
    file_path: str = Field("", description="allowed local file path")
    source: str = Field("", description="source label")
    document_id: str = Field("", description="optional stable document id")
    tenant_id: str = Field("", description="tenant/user isolation key")
    version: str = Field("", description="document version number, vN, or empty for auto increment")
    version_label: str = Field("", description="optional display version label")
    chunk_strategy: str = Field("semantic", description="semantic | fixed")
    chunk_size: int = Field(500, ge=50, le=5000)
    chunk_overlap: int = Field(50, ge=0, le=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetQueryRequest(BaseModel):
    query: str = Field(..., description="question or retrieval query")
    top_k: int = Field(5, ge=1, le=50)
    include_answer: bool = Field(True, description="return deterministic answer with citations")
    tenant_id: str = Field("", description="tenant/user isolation key")
    version: str = Field("", description="document version number, vN, latest, or empty")
    metadata_filter: dict[str, Any] = Field(default_factory=dict)
    rerank: bool = Field(False, description="apply lexical reranker after hybrid retrieval")


class DatasetVersionDiffRequest(BaseModel):
    source: str = Field(..., description="document source label")
    tenant_id: str = Field("", description="tenant/user isolation key")
    from_version: str = Field(..., description="source version number, vN, or label")
    to_version: str = Field("latest", description="target version number, vN, label, or latest")


class DatasetRollbackRequest(BaseModel):
    source: str = Field(..., description="document source label")
    tenant_id: str = Field("", description="tenant/user isolation key")
    target_version: str = Field(..., description="version to restore into a new latest version")
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetRebuildRequest(BaseModel):
    tenant_id: str = Field("", description="tenant/user isolation key")
    metadata_filter: dict[str, Any] = Field(default_factory=dict)
    background: bool = Field(True, description="run index rebuild in a background thread")
    max_attempts: int = Field(1, ge=1, le=5)


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
    from app.application.dataset_rag_app_service import DatasetAccessContext
    from app.infrastructure.auth.tenant_context import resolve_tenant_id

    headers = request.headers
    tenant = (headers.get("X-Dataset-Tenant-ID") or headers.get("X-Tenant-ID") or "").strip()
    if not tenant:
        resolved_tenant = resolve_tenant_id(request)
        tenant = str(resolved_tenant) if resolved_tenant is not None else ""
    actor_id = (headers.get("X-Dataset-Actor-ID") or headers.get("X-User-ID") or "").strip()
    permissions_raw = headers.get("X-Dataset-Permissions") or headers.get("X-Permissions") or ""
    permissions = frozenset(
        part.strip() for part in permissions_raw.replace(";", ",").split(",") if part.strip()
    )
    is_admin = headers.get("X-Dataset-Admin", "").strip().lower() in {"1", "true", "yes", "on"}
    if not tenant and not actor_id and not permissions and not is_admin:
        return None
    return DatasetAccessContext(
        actor_id=actor_id,
        tenant_id=tenant,
        permissions=permissions,
        is_admin=is_admin,
    )


def _dataset_access_payload_from_request(request: Request) -> dict[str, Any]:
    context = _dataset_access_context_from_request(request)
    if context is None:
        return {}
    payload = dict(context.to_dict())
    permissions = payload.get("permissions") if isinstance(payload.get("permissions"), list) else []
    if not payload.get("tenant_id") and not permissions and not payload.get("is_admin"):
        return {}
    return payload


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
    return output


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
    from app.services.tools_execution.registry import get_workflow_tool_registry

    data = dict(params or {})
    access_payload = _dataset_access_payload_from_request(request)
    if access_payload:
        data["access_context"] = access_payload
        if access_payload.get("tenant_id"):
            data.setdefault("tenant_id", access_payload["tenant_id"])
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
    if run.status == "waiting_user":
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "dataset-rag-route",
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued

    payload = _agent_node_output(run, node_id)
    status_code = 200
    if payload.get("error_code") == "tool_exception":
        status_code = 500
    if run.status in {"waiting_user", "blocked"}:
        status_code = 202
    return JSONResponse(payload, status_code=status_code)


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest) -> IngestResponse:
    try:
        count = _index.ingest(
            req.text, req.source, req.chunk_strategy, req.chunk_size, req.chunk_overlap
        )
        return IngestResponse(
            success=True,
            chunk_count=count,
            source=req.source,
            strategy=req.chunk_strategy,
            message=f"已入库 {count} 个 chunk",
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
        },
    )


@router.get("/datasets")
def dataset_status_all(request: Request) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    return get_dataset_rag_app_service().status(
        access_context=_dataset_access_context_from_request(request),
    )


@router.get("/datasets/{dataset_id}/status")
def dataset_status(dataset_id: str, request: Request) -> dict[str, Any]:
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    return get_dataset_rag_app_service().status(
        dataset_id,
        access_context=_dataset_access_context_from_request(request),
    )


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

    return get_dataset_rag_app_service().get_rebuild_job(
        dataset_id,
        job_id,
        access_context=_dataset_access_context_from_request(request),
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


@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    s = _index.status()
    return StatusResponse(
        rag_enabled=is_rag_enabled(),
        embedder_available=get_default_embedder() is not None,
        indexed_sources=s["sources"],
        indexed_chunks=s["chunks"],
    )


@router.get("/health")
def health() -> dict[str, Any]:
    s = _index.status()
    return {
        "success": True,
        "rag_enabled": is_rag_enabled(),
        "embedder_available": get_default_embedder() is not None,
        "indexed_sources": s["sources"],
        "indexed_chunks": s["chunks"],
    }
