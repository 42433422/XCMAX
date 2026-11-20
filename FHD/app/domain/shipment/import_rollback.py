"""Pure receipt identity and completion rule for import rollback."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImportRollback:
    run_id: str
    origin: dict[str, str]
    rows: int


def confirmed_rollback(receipt: dict, item: ImportRollback) -> bool:
    rollback = receipt.get("rollback")
    return (
        isinstance(rollback, dict)
        and rollback.get("status") == "completed"
        and rollback.get("rows") == item.rows
    )
