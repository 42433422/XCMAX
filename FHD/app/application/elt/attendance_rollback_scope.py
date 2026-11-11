"""Evidence for conservative single-run attendance rollback on a shared source.

Legacy tables lack row ownership. Refuse rollback when another source batch or
unattributed rows existed, or when any source row changed after this run committed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

# Complete static statements: identifiers cannot be supplied by a caller.
SOURCE_QUERIES = {
    "attendance_import_batches": "SELECT * FROM attendance_import_batches WHERE source_file = ? ORDER BY id",
    "attendance_daily_records": "SELECT * FROM attendance_daily_records WHERE source_file = ? ORDER BY id",
    "attendance_monthly_marks": "SELECT * FROM attendance_monthly_marks WHERE source_file = ? ORDER BY id",
    "attendance_employees": "SELECT * FROM attendance_employees WHERE source_file = ? ORDER BY id",
    "attendance_departments": "SELECT * FROM attendance_departments WHERE source_file = ? ORDER BY id",
    "products": "SELECT * FROM products WHERE source_file = ? ORDER BY id",
    "customers": "SELECT * FROM customers WHERE source_file = ? ORDER BY id",
}


def source_snapshot(conn: sqlite3.Connection, source_file: str) -> tuple[str, bool]:
    snapshot = {}
    any_rows = False
    for table, query in SOURCE_QUERIES.items():
        rows = conn.execute(query, (source_file,)).fetchall()
        snapshot[table] = [list(row) for row in rows]
        any_rows = any_rows or bool(rows)
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest(), any_rows


def has_external_reference(conn: sqlite3.Connection, source_file: str) -> bool:
    """Shared names/department identities are ambiguous in legacy tables: refuse."""
    found = conn.execute(
        "SELECT 1 FROM attendance_employees own JOIN ("
        "SELECT employee_name, source_file FROM attendance_employees UNION ALL "
        "SELECT employee_name, source_file FROM attendance_daily_records UNION ALL "
        "SELECT employee_name, source_file FROM attendance_monthly_marks"
        ") other ON own.employee_name = other.employee_name "
        "WHERE own.source_file = ? AND other.source_file != ? LIMIT 1",
        (source_file, source_file),
    ).fetchone()
    if found:
        return True
    found = conn.execute(
        "SELECT 1 FROM attendance_departments own JOIN ("
        "SELECT department, source_file FROM attendance_departments UNION ALL "
        "SELECT department, source_file FROM attendance_employees UNION ALL "
        "SELECT department, source_file FROM attendance_daily_records"
        ") other ON own.department = other.department "
        "WHERE own.source_file = ? AND own.department != '' AND other.source_file != ? LIMIT 1",
        (source_file, source_file),
    ).fetchone()
    return found is not None
