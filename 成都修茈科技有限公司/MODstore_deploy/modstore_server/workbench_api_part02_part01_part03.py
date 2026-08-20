# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


def _assert_employee_catalog_registered(db: _facade().Session, pack_id: str) -> bool:
    """Return True when pack_id is visible to employee_executor (DB or packages.json)."""
    pid = str(pack_id or "").strip()
    if not pid:
        return False
    row = (
        db.query(_facade().CatalogItem)
        .filter(
            _facade().CatalogItem.pkg_id == pid,
            _facade().CatalogItem.artifact == "employee_pack",
        )
        .first()
    )
    if row:
        return True
    try:
        from modstore_server.catalog_store import employee_pack_records_from_store

        rec = employee_pack_records_from_store().get(pid)
        return isinstance(rec, dict)
    except RECOVERABLE_ERRORS:
        return False
