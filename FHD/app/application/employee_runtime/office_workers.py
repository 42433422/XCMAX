"""Runtime classification for the bundled deterministic Office workers."""

from __future__ import annotations

from app.utils.operational_errors import RECOVERABLE_ERRORS


def is_deterministic_office_worker(employee_id: str, handler_list: list[str]) -> bool:
    """Return whether a bundled Office pack can run without model cognition."""

    if handler_list != ["direct_python"]:
        return False
    try:
        from app.mod_sdk.employee_pack_compat import list_office_pack_catalog

        return employee_id in set(list_office_pack_catalog().get("pack_ids") or [])
    except RECOVERABLE_ERRORS:
        return False
