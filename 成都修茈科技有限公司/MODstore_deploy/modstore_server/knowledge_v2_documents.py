# mypy: disable-error-code="arg-type, assignment"
"""Document ingestion transaction for Knowledge v2 collections."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable, Dict, List

from fastapi import HTTPException, UploadFile

from modstore_server import rag_service, vector_engine
from modstore_server.embedding_service import EmbeddingConfigError, embed_texts
from modstore_server.knowledge_ingest import parse_and_chunk_with_metadata
from modstore_server.knowledge_vector_store import make_doc_id
from modstore_server.models import KnowledgeDocument, User, get_session_factory
from modstore_server.vector_engine import VectorEngineError


async def upload_document(
    *,
    coll_id: int,
    file: UploadFile,
    embedding_provider: str | None,
    chunk_strategy: str | None,
    user: User,
    ensure_collection: Callable[[Any, int], Any],
    can_admin: Callable[[Any, User], bool],
    service_unavailable: Callable[[Exception], HTTPException],
) -> Dict[str, Any]:
    """Authorize, embed, upsert and persist one uploaded document."""
    session_factory = get_session_factory()
    with session_factory() as session:
        collection = ensure_collection(session, coll_id)
        can_write = rag_service.can_access_collection(
            session,
            collection_id=collection.id,
            user_id=user.id,
            permission="write",
        )
        if not can_write and not can_admin(collection, user):
            raise HTTPException(403, "无权写入该集合")

    effective_strategy = chunk_strategy
    if effective_strategy is None and collection.chunk_config:
        try:
            chunk_config = (
                json.loads(collection.chunk_config)
                if isinstance(collection.chunk_config, str)
                else collection.chunk_config
            )
            effective_strategy = chunk_config.get("strategy")
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass

    filename = (file.filename or "upload.txt").strip()
    raw = await file.read()
    text, chunks, chunk_metas = parse_and_chunk_with_metadata(
        filename,
        raw,
        chunk_strategy=effective_strategy,
    )
    doc_id = make_doc_id(int(user.id), filename, raw)
    try:
        with get_session_factory()() as session:
            embeddings = await embed_texts(
                chunks,
                session=session,
                user_id=int(user.id),
                provider=embedding_provider,
            )
    except EmbeddingConfigError as error:
        raise service_unavailable(error) from error

    ids: List[str] = [f"{doc_id}:{index}" for index in range(len(chunks))]
    output_metas: List[Dict[str, Any]] = []
    created_at_ts = int(datetime.now(UTC).timestamp())
    for index, metadata in enumerate(chunk_metas or [{} for _ in chunks]):
        output: Dict[str, Any] = {
            "user_id": str(int(user.id)),
            "doc_id": str(doc_id),
            "chunk_id": ids[index],
            "filename": filename,
            "chunk_index": index,
            "created_at": created_at_ts,
        }
        page_no = metadata.get("page_no") if isinstance(metadata, dict) else None
        if page_no is not None:
            try:
                output["page_no"] = int(page_no)
            except (TypeError, ValueError):
                pass
        output_metas.append(output)

    try:
        vector_engine.upsert(
            vector_engine.kb_collection_name(int(coll_id)),
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=output_metas,
        )
    except VectorEngineError as error:
        raise service_unavailable(error) from error

    with get_session_factory()() as session:
        collection = ensure_collection(session, coll_id)
        try:
            vector_engine.delete(
                vector_engine.kb_collection_name(int(collection.id)),
                where={"doc_id": str(doc_id), "_replace_marker": True},
            )
        except VectorEngineError:
            pass
        document = (
            session.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.collection_id == collection.id,
                KnowledgeDocument.doc_id == str(doc_id),
            )
            .first()
        )
        if document is None:
            document = KnowledgeDocument(
                collection_id=collection.id,
                doc_id=str(doc_id),
                filename=filename,
                size_bytes=len(raw),
                chunk_count=len(chunks),
            )
            session.add(document)
        else:
            document.filename = filename
            document.size_bytes = len(raw)
            document.chunk_count = len(chunks)
        chunk_rows = (
            session.query(KnowledgeDocument.chunk_count)
            .filter(KnowledgeDocument.collection_id == collection.id)
            .all()
        )
        collection.chunk_count = sum(int(row[0] or 0) for row in chunk_rows)
        session.commit()
    return {
        "ok": True,
        "document": {
            "doc_id": doc_id,
            "filename": filename,
            "size_bytes": len(raw),
            "chunk_count": len(chunks),
            "created_at": created_at_ts,
        },
        "text_chars": len(text),
    }
