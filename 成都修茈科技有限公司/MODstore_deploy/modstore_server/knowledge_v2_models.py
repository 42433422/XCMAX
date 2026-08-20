"""Request DTOs for the Knowledge v2 API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CollectionCreateBody(BaseModel):
    owner_kind: str = Field("user", min_length=1, max_length=16)
    owner_id: Optional[str] = Field(None, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=2000)
    visibility: str = Field("private", min_length=1, max_length=16)
    embedding_model: Optional[str] = Field(None, max_length=64)
    embedding_dim: Optional[int] = Field(None, ge=8, le=8192)


class CollectionUpdateBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=2000)
    visibility: Optional[str] = Field(None, min_length=1, max_length=16)


class ShareBody(BaseModel):
    grantee_kind: str = Field(..., min_length=1, max_length=16)
    grantee_id: str = Field(..., min_length=1, max_length=64)
    permission: str = Field("read", min_length=1, max_length=8)


class RetrieveBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(6, ge=1, le=20)
    min_score: float = Field(0.0, ge=0.0, le=1.0)
    employee_id: Optional[str] = Field(None, max_length=64)
    workflow_id: Optional[int] = None
    org_id: Optional[str] = Field(None, max_length=64)
    collection_ids: Optional[list[int]] = None
    embedding_provider: Optional[str] = Field(None, max_length=64)
    embedding_model: Optional[str] = Field(None, max_length=128)
