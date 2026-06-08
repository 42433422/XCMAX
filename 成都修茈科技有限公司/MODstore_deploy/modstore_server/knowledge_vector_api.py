"""User-scoped knowledge-base upload and Redis vector search APIs."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from modstore_server.api.deps import _get_current_user
from modstore_server.embedding_service import (
    EmbeddingConfigError,
    embed_texts,
    embedding_config_snapshot,
)
from modstore_server.knowledge_ingest import SUPPORTED_EXTENSIONS, parse_and_chunk_with_metadata
from modstore_server.knowledge_vector_store import (
    KnowledgeVectorError,
    delete_document,
    list_documents,
    make_doc_id,
    search,
)
from modstore_server.knowledge_vector_store import status as vector_status
from modstore_server.knowledge_vector_store import (
    upsert_document,
)
from modstore_server.models import User, get_session_factory

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class KnowledgeSearchBody(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    limit: int = Field(6, ge=1, le=20)
    embedding_provider: str | None = Field(None, max_length=64)
    embedding_model: str | None = Field(None, max_length=128)


def _service_unavailable(e: Exception) -> HTTPException:
    return HTTPException(503, str(e))


@router.get("/status")
def api_knowledge_status(user: User = Depends(_get_current_user)):
    sf = get_session_factory()
    with sf() as session:
        emb = embedding_config_snapshot(session=session, user_id=int(user.id))
    vec = vector_status()
    return {
        "ok": bool(emb.get("configured") and vec.get("ready")),
        "embedding": emb,
        "vector": vec,
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
    }


@router.get("/documents")
def api_list_documents(user: User = Depends(_get_current_user)):
    """列出资料；向量后端不可用时降级为空列表，避免工作台首屏被 503 阻断。"""
    try:
        return {"documents": list_documents(user.id)}
    except KnowledgeVectorError as e:
        return {
            "documents": [],
            "degraded": True,
            "reason": str(e),
        }


@router.post("/documents")
async def api_upload_document(
    file: UploadFile = File(...),
    embedding_provider: str | None = Form(None),
    embedding_model: str | None = Form(None),
    user: User = Depends(_get_current_user),
):
    filename = (file.filename or "upload.txt").strip()
    raw = await file.read()
    text, chunks, chunk_metas = parse_and_chunk_with_metadata(filename, raw)
    doc_id = make_doc_id(user.id, filename, raw)
    try:
        sf = get_session_factory()
        with sf() as session:
            embeddings = await embed_texts(
                chunks,
                session=session,
                user_id=int(user.id),
                provider=embedding_provider,
            )
        doc = upsert_document(
            user_id=user.id,
            doc_id=doc_id,
            filename=filename,
            size_bytes=len(raw),
            chunks=chunks,
            embeddings=embeddings,
            chunk_metas=chunk_metas,
        )
    except EmbeddingConfigError as e:
        raise _service_unavailable(e)
    except KnowledgeVectorError as e:
        raise _service_unavailable(e)
    return {"ok": True, "document": doc, "text_chars": len(text)}


@router.post("/extract-text")
async def api_extract_text(file: UploadFile = File(...), user: User = Depends(_get_current_user)):
    """Parse an uploaded file and return extracted text without requiring the embedding service.

    Used as a fallback when the vector store / embedding service is unavailable so the
    client can still inject file content directly into the LLM context window.
    """
    filename = (file.filename or "upload.txt").strip()
    raw = await file.read()
    try:
        text, _chunks, _metas = parse_and_chunk_with_metadata(filename, raw)
    except HTTPException:
        raise
    max_chars = int(os.environ.get("MODSTORE_KB_INLINE_MAX_CHARS", str(20_000)))
    truncated = len(text) > max_chars
    return {
        "ok": True,
        "filename": filename,
        "text": text[:max_chars],
        "truncated": truncated,
        "char_count": len(text),
    }


@router.delete("/documents/{doc_id}")
def api_delete_document(doc_id: str, user: User = Depends(_get_current_user)):
    try:
        deleted = delete_document(user.id, doc_id)
    except KnowledgeVectorError as e:
        raise _service_unavailable(e)
    if not deleted:
        raise HTTPException(404, "资料不存在")
    return {"ok": True, "doc_id": doc_id}


@router.post("/search")
async def api_search_knowledge(body: KnowledgeSearchBody, user: User = Depends(_get_current_user)):
    try:
        sf = get_session_factory()
        with sf() as session:
            vecs = await embed_texts(
                [body.query],
                session=session,
                user_id=int(user.id),
                provider=body.embedding_provider,
            )
        items = search(user.id, vecs[0], body.limit)
    except EmbeddingConfigError as e:
        raise _service_unavailable(e)
    except KnowledgeVectorError as e:
        raise _service_unavailable(e)
    return {"items": items}
