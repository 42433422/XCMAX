"""Read an existing authorized snapshot through the shared Excel facts adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils.cell import range_boundaries

from app.application.reviewed_excel_io_lock import serialize_workbook_io
from app.domain.tabular_facts import SCHEMA_VERSION
from app.infrastructure.document_parsing.archive_safety import (
    OfficeArchiveError,
    inspect_office_archive,
)
from app.infrastructure.excel.workbook_facts import build_workbook_facts
from app.infrastructure.excel.workbook_page_index import WorkbookPageIndex, project_workbook_page
from app.utils.performance.cache_manager import LRUTTLCache

WORKBOOK_SNAPSHOT_LIMIT_BYTES = 40 * 1024 * 1024
# Native dictionaries/styles require materialized objects. Streaming ELT keeps
# its separate budget; exceeding this limit is blocked, never truncated.
WORKBOOK_MATERIALIZED_CELL_LIMIT = 500_000
WORKBOOK_PAGE_CACHE_ENTRY_BYTES = 64 * 1024 * 1024
_PAGE_READER_VERSION = "native-pages-v1"
_PAGE_CACHE = LRUTTLCache(max_size=2, ttl_seconds=120, name="native_workbook_pages")
_SNAPSHOT_SCOPE: ContextVar[tuple[Path, str] | None] = ContextVar(
    "authorized_workbook_snapshot", default=None
)


@contextmanager
def workbook_snapshot_scope(path: Path, authorization_scope: str) -> Iterator[None]:
    """Host-only binding, entered AFTER current file/session ownership checks.

    Model arguments cannot set this context. It must be renewed for every page;
    a cache key, source digest or previous context is never an authorization.
    """
    token = _SNAPSHOT_SCOPE.set((path.resolve(), authorization_scope))
    try:
        yield
    finally:
        _SNAPSHOT_SCOPE.reset(token)


def _snapshot(
    source: bytes | str | Path, source_name: str, expected_sha256: str | None
) -> tuple[bytes, str, str]:
    if isinstance(source, bytes):
        body = source
    else:
        path = Path(source)
        source_name = source_name or path.name
        with path.open("rb") as handle:
            body = handle.read(WORKBOOK_SNAPSHOT_LIMIT_BYTES + 1)
    if len(body) > WORKBOOK_SNAPSHOT_LIMIT_BYTES:
        raise OfficeArchiveError("office_compressed_budget_exceeded")
    digest = hashlib.sha256(body).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("workbook snapshot SHA-256 mismatch")
    return body, source_name, digest


@serialize_workbook_io
def read_workbook_facts(
    source: bytes | str | Path,
    *,
    source_name: str = "",
    authorization_scope: str = "",
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """No authorization lookup, external fetch, shared cache, or recalculation.

    Callers retain their existing snapshot/owner checks. A digest or document ID
    is never accepted as permission. Read a path once so metadata and values
    cannot be assembled from different file versions.
    """
    body, source_name, _ = _snapshot(source, source_name, expected_sha256)
    audit = inspect_office_archive(body, max_compressed_bytes=WORKBOOK_SNAPSHOT_LIMIT_BYTES)
    materialized_upper_bound = audit["worksheet_cell_elements"] + audit["merged_area_upper_bound"]
    if materialized_upper_bound > WORKBOOK_MATERIALIZED_CELL_LIMIT:
        raise OfficeArchiveError("tabular_native_materialization_budget_exceeded")
    document = build_workbook_facts(
        body,
        source_name=source_name,
        authorization_scope=authorization_scope,
    )
    document["archive_audit"] = audit
    document["resource_budget"] = {
        "materialized_cells_limit": WORKBOOK_MATERIALIZED_CELL_LIMIT,
        "materialized_cells_upper_bound": materialized_upper_bound,
    }
    return document


@serialize_workbook_io
def read_workbook_page(
    path: Path,
    *,
    view: str,
    sheet_name: str | None = None,
    cell_range: str | None = None,
    offset: int = 0,
    limit: int = 1000,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Revalidate snapshot bytes and reuse only scoped, bounded derived indexes.

    Cold reads retain the complete native facts contract. Warm pages inflate
    only selected blocks; neither cache contents nor TTL replace authorization.
    Unbound local calls and over-budget indexes remain fully readable uncached.
    """
    if view not in {"cells", "sheets"}:
        raise ValueError("invalid_read_view")
    if type(offset) is not int or offset < 0 or type(limit) is not int or limit < 1:
        raise ValueError("invalid_native_page_bounds")
    # The byte budget remains authoritative; no caller can allocate a position
    # list larger than the admitted native document itself.
    limit = min(limit, WORKBOOK_MATERIALIZED_CELL_LIMIT)
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        raise ValueError("native_facts_unsupported_format")
    if offset and not expected_sha256:
        raise ValueError("native_page_requires_source_sha256")
    bounds = None
    if cell_range and view == "cells":
        if not isinstance(cell_range, str):
            raise ValueError("invalid_native_cell_range")
        left, top, right, bottom = range_boundaries(cell_range)
        if (
            left is None
            or top is None
            or right is None
            or bottom is None
            or not 1 <= left <= right <= 16384
            or not 1 <= top <= bottom <= 1048576
        ):
            raise ValueError("invalid_native_cell_range")
        bounds = (left, top, right, bottom)
    body, name, digest = _snapshot(path, "", expected_sha256)
    binding = _SNAPSHOT_SCOPE.get()
    scope = binding[1] if binding is not None and binding[0] == path.resolve() else ""
    key = json.dumps(
        [
            scope,
            digest,
            path.suffix.lower(),
            SCHEMA_VERSION,
            openpyxl.__version__,
            _PAGE_READER_VERSION,
            WORKBOOK_SNAPSHOT_LIMIT_BYTES,
            WORKBOOK_MATERIALIZED_CELL_LIMIT,
            WORKBOOK_PAGE_CACHE_ENTRY_BYTES,
        ],
        separators=(",", ":"),
    )
    indexed = _PAGE_CACHE.get(key) if scope else None
    if indexed is None:
        document = read_workbook_facts(body, source_name=name, authorization_scope=scope)
        indexed = (
            WorkbookPageIndex.build(document, WORKBOOK_PAGE_CACHE_ENTRY_BYTES) if scope else None
        )
        if indexed is not None:
            _PAGE_CACHE.set(key, indexed)
        source = indexed if indexed is not None else document
    else:
        source = indexed
    return {
        **project_workbook_page(
            source, view=view, sheet_name=sheet_name, bounds=bounds, offset=offset, limit=limit
        ),
        "view": view,
        "sheet_name": sheet_name,
        "cell_range": cell_range,
    }
