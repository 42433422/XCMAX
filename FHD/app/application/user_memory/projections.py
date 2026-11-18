"""Rebuildable projections of committed MemoryV2 records."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from app.application.user_memory.governance import (
    is_recallable_memory,
    is_scoped_memory_owner,
    memory_statement,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def project_after_commit(method):
    """Run external indexing after the authority transaction has been released."""

    @wraps(method)
    def wrapped(self, user_id: str, *args, **kwargs):
        result = method(self, user_id, *args, **kwargs)
        if result.get("success") and isinstance(result.get("memory"), dict):

            def list_records(owner: str) -> list[dict[str, Any]]:
                memory = self.access.get_memory(owner)
                return memory.memory_v2_records if memory is not None else []

            result["projection"] = sync_memory_projection(
                user_id, result["memory"], list_records=list_records
            )
        return result

    return wrapped


def _projection_signature(record: dict[str, Any] | None) -> tuple[Any, ...] | None:
    if record is None:
        return None
    return (
        int(record.get("revision") or 1),
        record.get("status"),
        record.get("eligible_for_planner"),
        record.get("source_policy"),
        memory_statement(record),
        record.get("memory_type"),
        record.get("key"),
    )


def sync_memory_projection(
    user_id: str,
    record: dict[str, Any],
    *,
    list_records: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, str]:
    """Project a current authority snapshot, then verify it after external IO.

    A delayed callback identifies a source; its captured value is never authority.
    Retry one changed snapshot inline, then report remaining races for replay.
    Each authority read releases its transaction before touching either replica.
    """
    if not is_scoped_memory_owner(user_id):
        return {"user_vector": "quarantined", "mem0": "quarantined"}
    from app.infrastructure.memory.mem0_backend import get_long_term_memory

    source_id = str(record.get("memory_id") or "")
    status = {"user_vector": "retry_required", "mem0": "retry_required"}
    try:
        if not source_id:
            raise ValueError("memory projection requires a source ID")
        if list_records is None:
            from app.domain.shared_services.user_memory_service import get_user_memory_service

            list_records = get_user_memory_service().list_memories

        def current_record() -> dict[str, Any] | None:
            return next(
                (row for row in list_records(user_id) if row.get("memory_id") == source_id),
                None,
            )

        current = current_record()
        for _ in range(2):
            status = _write_current_projection(user_id, source_id, current)
            latest = current_record()
            if _projection_signature(current) == _projection_signature(latest):
                break
            current = latest
        else:
            status = {
                name: "disabled" if value == "disabled" else "retry_required"
                for name, value in status.items()
            }
    except RECOVERABLE_ERRORS:
        logger.warning("memory authority could not verify projection", exc_info=True)
        status = {"user_vector": "retry_required", "mem0": "retry_required"}

    if "retry_required" in status.values():
        # Replay both stores after a vector-only outage or an unverified write,
        # even if Mem0 previously cached this owner as synchronized.
        try:
            get_long_term_memory().invalidate_projection(user_id)
        except RECOVERABLE_ERRORS:
            logger.warning("memory projection replay could not be scheduled", exc_info=True)
    return status


def _write_current_projection(
    user_id: str, source_id: str, record: dict[str, Any] | None
) -> dict[str, str]:
    from app.application.user_memory_vector_app_service import (
        get_user_memory_vector_ingest_app_service,
    )
    from app.infrastructure.memory.mem0_backend import get_long_term_memory

    record = record or {}
    revision = int(record.get("revision") or 1)
    metadata = {
        "source_memory_id": source_id,
        "source_revision": revision,
        "source_owner_id": user_id,
        "source": "memory_v2",
        "memory_type": record.get("memory_type"),
        "key": record.get("key"),
    }
    status: dict[str, str] = {}
    active = is_recallable_memory(record)
    for name, provider in (
        ("user_vector", get_user_memory_vector_ingest_app_service),
        ("mem0", get_long_term_memory),
    ):
        try:
            backend = provider()
            if name == "mem0" and not backend.enabled:
                status[name] = "disabled"
                continue
            if active:
                written = backend.upsert_governed(
                    user_id=user_id,
                    source_memory_id=source_id,
                    revision=revision,
                    text=memory_statement(record),
                    metadata=metadata,
                )
                status[name] = "current" if written else "retry_required"
            else:
                removed = backend.forget_source(user_id=user_id, source_memory_id=source_id)
                status[name] = "removed" if removed >= 0 else "retry_required"
        except RECOVERABLE_ERRORS:
            logger.warning("memory projection %s requires retry", name, exc_info=True)
            status[name] = "retry_required"
    return status


def rebuild_memory_projections(user_id: str, *, memory_service: Any = None) -> dict[str, int]:
    """Replay current authority after a model/collection change or an indexing outage."""
    if not is_scoped_memory_owner(user_id):
        return {"total": 0, "current": 0, "retry_required": 0}
    from app.domain.shared_services.user_memory_service import get_user_memory_service

    service = memory_service or get_user_memory_service()
    # Tombstones must also be replayed: a prior delete may have committed while
    # an external store was unavailable.
    records = service.list_memories(user_id)
    failed = 0
    for record in records:
        status = sync_memory_projection(user_id, record, list_records=service.list_memories)
        failed += int("retry_required" in status.values())
    return {"total": len(records), "current": len(records) - failed, "retry_required": failed}
