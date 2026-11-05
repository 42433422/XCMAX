"""Bounded knowledge request payloads and stable HTTP response models."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

_DATASET_UPLOAD_EXTENSIONS = frozenset(
    {".pdf", ".docx", ".xlsx", ".xls", ".txt", ".md", ".csv", ".json", ".log"}
)
_DATASET_UPLOAD_MAX_BYTES = 25 * 1024 * 1024
_DATASET_INLINE_MAX_CHARS = 5_000_000
_DATASET_METADATA_MAX_BYTES = 64 * 1024
_PERSY_DATASET_ID = "persy-knowledge"


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
        if not self.text.strip() and (not self.file_path.strip()):
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

    @field_validator("metadata_filter")
    @classmethod
    def validate_metadata_filter(cls, value: dict[str, Any]) -> dict[str, Any]:
        _ensure_bounded_metadata(value)
        return value


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
