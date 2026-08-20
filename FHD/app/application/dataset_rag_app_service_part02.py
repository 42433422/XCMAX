# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.dataset_rag_app_service")


def _semantic_embedding_available(embedding_count: int = 0) -> bool:
    """UI contract: true when a live embedder exists or chunks already carry vectors."""
    if int(embedding_count or 0) > 0:
        return True
    try:
        from app.infrastructure.rag import get_default_embedder

        return get_default_embedder() is not None
    except _facade().RECOVERABLE_ERRORS:
        return False


@_facade().dataclass(frozen=True)
class DatasetAccessContext:
    actor_id: str = ""
    tenant_id: str = ""
    permissions: frozenset[str] = _facade().field(default_factory=frozenset)
    is_admin: bool = False

    def to_dict(self) -> dict[str, _facade().Any]:
        return {
            "actor_id": self.actor_id,
            "tenant_id": self.tenant_id,
            "permissions": sorted(self.permissions),
            "is_admin": self.is_admin,
        }


@_facade().dataclass
class _DatasetState:
    dataset_id: str
    documents: dict[str, _facade().DatasetDocument] = _facade().field(default_factory=dict)
    chunks: list[_facade().RetrievedChunk] = _facade().field(default_factory=list)
    index: dict[str, _facade().Any] = _facade().field(default_factory=dict)
    rebuild_jobs: dict[str, _facade().DatasetRebuildJob] = _facade().field(default_factory=dict)
