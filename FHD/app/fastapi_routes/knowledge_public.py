"""Public read-only knowledge query authenticated by a dataset API key.

Mounted outside the desktop session gate; security comes from the hashed,
revocable ``X-KB-Key`` header. The key is bound to one dataset and the tenant of
its creator, so external callers can never widen visibility.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class PublicKnowledgeQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)
    metadata_filter: dict[str, object] = Field(default_factory=dict)
    retrieval_mode: str = Field("hybrid", description="hybrid | vector | keyword")
    mmr_lambda: float = Field(0.0, ge=0, le=1)
    expand_section: bool = Field(False)


def _service():
    from app.application.dataset_rag_app_service import get_dataset_rag_app_service

    return get_dataset_rag_app_service()


router = APIRouter(prefix="/api/knowledge/v1/public", tags=["knowledge-public"])


@router.post("/query")
def public_query(
    req: PublicKnowledgeQueryRequest,
    request: Request,
    x_kb_key: str = Header("", alias="X-KB-Key"),
) -> Any:
    key = x_kb_key.strip()
    if not key:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error_code": "knowledge_api_key_required",
                "message": "X-KB-Key header is required",
                "chunks": [],
            },
        )
    result = _service().public_query(
        api_key=key,
        query=req.query,
        top_k=req.top_k,
        metadata_filter=dict(req.metadata_filter or {}),
        retrieval_mode=req.retrieval_mode,
        mmr_lambda=req.mmr_lambda,
        expand_section=req.expand_section,
    )
    if not result.get("success"):
        status = 401 if result.get("error_code") == "knowledge_api_key_invalid" else 400
        return JSONResponse(status_code=status, content=result)
    return result
