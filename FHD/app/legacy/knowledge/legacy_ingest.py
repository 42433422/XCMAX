"""Project legacy in-memory ingests into the governed Persy dataset."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from fastapi import Request

from app.application.dataset_rag.models import DatasetAccessContext
from app.fastapi_routes.knowledge.ports import AccessResolver
from app.utils.operational_errors import RECOVERABLE_ERRORS


class DocumentWriter(Protocol):
    def __call__(
        self,
        *,
        dataset_id: str,
        source: str,
        text: str,
        chunk_strategy: str,
        chunk_size: int,
        chunk_overlap: int,
        metadata: dict[str, Any],
        access_context: DatasetAccessContext | None,
    ) -> dict[str, Any]: ...


def mirror_legacy_ingest(
    *,
    text: str,
    source: str,
    chunk_strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    request: Request | None,
    writer: Callable[[], DocumentWriter],
    access_resolver: AccessResolver,
    dataset_id: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    try:
        access = access_resolver(request) if request is not None else None
        return writer()(
            dataset_id=dataset_id,
            source=source or "legacy-ingest",
            text=text,
            chunk_strategy=chunk_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            metadata={"entrypoint": "legacy_ingest_mirror"},
            access_context=access,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning("mirror ingest to persy-knowledge failed: %s", exc)
        return {"success": False, "message": str(exc)}
