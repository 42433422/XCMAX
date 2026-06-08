"""Catalog persistence adapters (SQL + JSON file storage + in-memory for tests)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from modstore_server import catalog_store
from modstore_server.domain.catalog.types import CatalogItem as CatalogDomainItem
from modstore_server.models import CatalogItem as CatalogItemRow


class FileCatalogPackageStorage:
    """Append-only package storage backed by :mod:`modstore_server.catalog_store`."""

    def append_package(self, record: dict[str, Any], src_file: Path | None) -> dict[str, Any]:
        return catalog_store.append_package(record, src_file)


class SqlCatalogRepository:
    """ORM adapter for :class:`CatalogDomainItem` rows."""

    def __init__(self, session: Session):
        self._session = session

    def get_by_pkg_id(self, pkg_id: str) -> CatalogDomainItem | None:
        row = self._session.query(CatalogItemRow).filter(CatalogItemRow.pkg_id == pkg_id).first()
        if not row:
            return None
        return CatalogDomainItem(
            pkg_id=str(row.pkg_id),
            author_id=int(row.author_id or 0),
            version=str(row.version or ""),
            artifact=str(row.artifact or "mod"),
            name=str(row.name or ""),
            description=str(row.description or ""),
            industry=str(row.industry or "通用"),
            sha256=str(row.sha256 or ""),
            stored_filename=str(row.stored_filename or ""),
        )

    def upsert(self, item: CatalogDomainItem, *, price: float) -> None:
        row = (
            self._session.query(CatalogItemRow).filter(CatalogItemRow.pkg_id == item.pkg_id).first()
        )
        if not row:
            row = CatalogItemRow(pkg_id=item.pkg_id, author_id=item.author_id)
            self._session.add(row)
        row.version = item.version
        row.name = item.name
        row.description = item.description or ""
        row.price = float(price or 0.0)
        row.artifact = item.artifact or "mod"
        row.industry = item.industry or "通用"
        row.stored_filename = item.stored_filename or ""
        row.sha256 = item.sha256 or ""


class InMemoryCatalogRepository:
    """Volatile store for unit tests."""

    def __init__(self) -> None:
        self._rows: dict[str, CatalogDomainItem] = {}

    def get_by_pkg_id(self, pkg_id: str) -> CatalogDomainItem | None:
        return self._rows.get(pkg_id)

    def upsert(self, item: CatalogDomainItem, *, price: float) -> None:
        _ = price
        self._rows[item.pkg_id] = item


class InMemoryCatalogPackageStorage:
    """Captures append calls for tests (no filesystem)."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], Path | None]] = []
        self.saved: list[dict[str, Any]] = []

    def append_package(self, record: dict[str, Any], src_file: Path | None) -> dict[str, Any]:
        self.calls.append((dict(record), src_file))
        rec = dict(record)
        rec.setdefault("sha256", "test-sha")
        rec.setdefault("stored_filename", "test.bin")
        self.saved.append(rec)
        return rec


__all__ = [
    "FileCatalogPackageStorage",
    "InMemoryCatalogPackageStorage",
    "InMemoryCatalogRepository",
    "SqlCatalogRepository",
]
