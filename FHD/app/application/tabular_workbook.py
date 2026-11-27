"""Read an existing authorized snapshot through the shared Excel facts adapter."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.application.reviewed_excel_formula_cells import formula_facts
from app.application.reviewed_excel_io_lock import serialize_workbook_io
from app.infrastructure.document_parsing.archive_safety import (
    OfficeArchiveError,
    inspect_office_archive,
)
from app.infrastructure.excel.workbook_facts import build_workbook_facts

WORKBOOK_SNAPSHOT_LIMIT_BYTES = 40 * 1024 * 1024
# Native dictionaries/styles require materialized objects. Streaming ELT keeps
# its separate budget; exceeding this limit is blocked, never truncated.
WORKBOOK_MATERIALIZED_CELL_LIMIT = 500_000


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
    audit = inspect_office_archive(body, max_compressed_bytes=WORKBOOK_SNAPSHOT_LIMIT_BYTES)
    materialized_upper_bound = audit["worksheet_cell_elements"] + audit["merged_area_upper_bound"]
    if materialized_upper_bound > WORKBOOK_MATERIALIZED_CELL_LIMIT:
        raise OfficeArchiveError("tabular_native_materialization_budget_exceeded")
    document = build_workbook_facts(
        body,
        source_name=source_name,
        authorization_scope=authorization_scope,
        formula_evidence=formula_facts(body),
    )
    document["archive_audit"] = audit
    document["resource_budget"] = {
        "materialized_cells_limit": WORKBOOK_MATERIALIZED_CELL_LIMIT,
        "materialized_cells_upper_bound": materialized_upper_bound,
    }
    return document
