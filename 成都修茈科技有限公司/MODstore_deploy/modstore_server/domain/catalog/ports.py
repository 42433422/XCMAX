"""Persistence and storage ports for the catalog domain."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from modstore_server.domain.catalog.types import CatalogItem


class CatalogRepository(Protocol):
    """Read/write catalog rows (e.g. SQLAlchemy ``CatalogItem``)."""

    def get_by_pkg_id(self, pkg_id: str) -> CatalogItem | None: ...

    def upsert(self, item: CatalogItem, *, price: float) -> None: ...


class CatalogPackageStorage(Protocol):
    """Append-only package blob storage (filesystem or object store)."""

    def append_package(self, record: dict[str, Any], src_file: Path | None) -> dict[str, Any]: ...


__all__ = ["CatalogRepository", "CatalogPackageStorage"]
