"""Dataset publication status helpers (extracted for source-governance)."""
from __future__ import annotations

from typing import Any

def set_document_publication_status(
    service,
    dataset_id: str,
    document_id: str,
    publication_status: str,
    *,
    reason: str,
    expected_status: str | None = None,
    access_context: Any = None,
) -> dict[str, Any]:
    dataset_key = _clean_key(dataset_id, default="default")
    doc_key = document_id.strip()
    next_status = str(publication_status or "").strip().lower()
    change_reason = str(reason or "").strip()
    expected = str(expected_status or "").strip().lower()
    context = _coerce_access_context(access_context)
    denied = _ensure_dataset_permission(
        context,
        DATASET_ADMIN_PERMISSION,
        dataset_id=dataset_key,
    )
    if denied is not None:
        return denied
    if next_status not in {"draft", "published", "archived"}:
        return {
            "success": False,
            "dataset_id": dataset_key,
            "document_id": doc_key,
            "error_code": "dataset_publication_status_invalid",
            "message": "publication status must be draft, published, or archived",
        }
    if len(change_reason) < 4:
        return {
            "success": False,
            "dataset_id": dataset_key,
            "document_id": doc_key,
            "error_code": "dataset_publication_reason_required",
            "message": "publication reason must contain at least 4 characters",
        }

    with service._lock:
        service._reload_external_state_locked()
        state = service._datasets.get(dataset_key)
        document = state.documents.get(doc_key) if state is not None else None
        if document is None:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "document_id": doc_key,
                "error_code": "dataset_document_not_found",
                "message": "document not found",
            }
        if document.tenant_id != PUBLIC_KNOWLEDGE_TENANT_ID:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "document_id": doc_key,
                "error_code": "dataset_publication_scope_invalid",
                "message": "only public-tenant documents have a publication lifecycle",
            }

        previous_status = str(document.metadata.get("publication_status") or "draft")
        if expected and previous_status != expected:
            return {
                "success": False,
                "dataset_id": dataset_key,
                "document_id": doc_key,
                "error_code": "dataset_publication_conflict",
                "message": "publication status changed; refresh before retrying",
                "expected_status": expected,
                "publication_status": previous_status,
            }
        actor_id = str(context.actor_id if context is not None else "")
        changed_at = _utc_now_iso()
        change_id = uuid.uuid4().hex
        history = document.metadata.get("publication_history")
        history_rows = list(history) if isinstance(history, list) else []
        history_rows.append(
            {
                "change_id": change_id,
                "from": previous_status,
                "to": next_status,
                "reason": change_reason,
                "actor_id": actor_id,
                "changed_at": changed_at,
            }
        )
        history_rows = history_rows[-100:]
        publication_metadata = {
            "audience": "public",
            "visibility": "public",
            "publication_status": next_status,
            "publication_updated_at": changed_at,
            "publication_updated_by": actor_id,
            "publication_change_id": change_id,
            "publication_reason": change_reason,
            "publication_history": history_rows,
        }
        previous_document_metadata = copy.deepcopy(document.metadata)
        previous_chunk_metadata = [
            (chunk, copy.deepcopy(chunk.metadata))
            for chunk in state.chunks
            if isinstance(chunk.metadata, dict)
            and str(chunk.metadata.get("document_id") or "") == doc_key
        ]
        document.metadata.update(publication_metadata)
        for chunk in state.chunks:
            metadata = chunk.metadata if isinstance(chunk.metadata, dict) else {}
            if str(metadata.get("document_id") or "") != doc_key:
                continue
            metadata.update(publication_metadata)
            chunk.metadata = metadata
        service._sync_vector_index_locked(state)
        if str(state.index.get("vector_backend_sync_status") or "") == "failed":
            document.metadata = previous_document_metadata
            for chunk, metadata in previous_chunk_metadata:
                chunk.metadata = metadata
            service._sync_vector_index_locked(state)
            service._refresh_index_metadata(state)
            return {
                "success": False,
                "dataset_id": dataset_key,
                "document_id": doc_key,
                "error_code": "dataset_publication_vector_sync_failed",
                "message": "vector index synchronization failed; publication was not changed",
            }
        service._refresh_index_metadata(state)
        service._persist_locked()

    return {
        "success": True,
        "dataset_id": dataset_key,
        "document_id": doc_key,
        "previous_status": previous_status,
        "publication_status": next_status,
        "change_id": change_id,
        "document": copy.deepcopy(document.to_dict()),
    }
