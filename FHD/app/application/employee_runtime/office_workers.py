"""Runtime classification for the bundled deterministic Office workers."""

from __future__ import annotations

from app.application.employee_runtime.loader import (
    manifest_actions_handlers,
    verify_direct_python_pack_trust,
)
from app.domain.workbook_write_contract import WORKBOOK_QC, WORKBOOK_WRITER
from app.utils.operational_errors import RECOVERABLE_ERRORS


def is_trusted_workbook_pack(employee_id: str, pack: dict) -> bool:
    return (
        pack["pack_id"] == employee_id
        and manifest_actions_handlers(pack["manifest"]) == ["direct_python"]
        and verify_direct_python_pack_trust(pack["pack_dir"])[0]
    )


def is_deterministic_office_worker(employee_id: str, handler_list: list[str]) -> bool:
    """Return whether a bundled Office pack can run without model cognition."""

    if handler_list != ["direct_python"]:
        return False
    if employee_id in {WORKBOOK_WRITER, WORKBOOK_QC}:
        return True
    try:
        from app.mod_sdk.employee_pack_compat import list_office_pack_catalog

        return employee_id in set(list_office_pack_catalog().get("pack_ids") or [])
    except RECOVERABLE_ERRORS:
        return False
