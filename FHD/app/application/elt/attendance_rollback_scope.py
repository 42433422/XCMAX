"""Evidence for conservative single-run attendance rollback on a shared source.

Legacy tables lack row ownership. Refuse rollback when another source batch or
unattributed rows existed, or when any source row changed after this run committed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

TABLES = (
    "attendance_import_batches",
    "attendance_daily_records",
    "attendance_monthly_marks",
    "attendance_employees",
    "attendance_departments",
    "products",
    "customers",
)


def source_snapshot(conn: sqlite3.Connection, source_file: str) -> tuple[str, bool]:
    snapshot = {}
    any_rows = False
    for table in TABLES:
        # Identifiers come only from this fixed internal allowlist.
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE source_file = ? ORDER BY id", (source_file,)
        ).fetchall()
        snapshot[table] = [list(row) for row in rows]
        any_rows = any_rows or bool(rows)
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest(), any_rows


def has_external_reference(conn: sqlite3.Connection, source_file: str) -> bool:
    """Shared names/department identities are ambiguous in legacy tables: refuse."""
    for table in ("attendance_employees", "attendance_daily_records", "attendance_monthly_marks"):
        found = conn.execute(
            f"SELECT 1 FROM attendance_employees own JOIN {table} other "
            "ON own.employee_name = other.employee_name "
            "WHERE own.source_file = ? AND other.source_file != ? LIMIT 1",
            (source_file, source_file),
        ).fetchone()
        if found:
            return True
    for table in ("attendance_departments", "attendance_employees", "attendance_daily_records"):
        found = conn.execute(
            f"SELECT 1 FROM attendance_departments own JOIN {table} other "
            "ON own.department = other.department "
            "WHERE own.source_file = ? AND own.department != '' AND other.source_file != ? LIMIT 1",
            (source_file, source_file),
        ).fetchone()
        if found:
            return True
    return False
