"""Host-owned attendance reference data used by desktop compatibility routes.

Private customer Mods are updated independently from the desktop application.
The host therefore owns the small read-only units alias consumed by the smart
chat attendance UI, so an older entitled Mod cannot turn the page into a 404.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path

_TABLE_INFO_SQL = {
    "attendance_departments": "PRAGMA table_info(attendance_departments)",
    "attendance_employees": "PRAGMA table_info(attendance_employees)",
}
_TABLE_FROM_SQL = {
    "attendance_departments": " FROM attendance_departments",
    "attendance_employees": " FROM attendance_employees",
}


def _names_from_host_units(payload: dict[str, Any] | None) -> set[str]:
    names: set[str] = set()
    rows = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return names
    for row in rows:
        if isinstance(row, dict):
            value = row.get("name") or row.get("unit_name") or row.get("symbol")
        else:
            value = row
        text = str(value or "").strip()
        if text:
            names.add(text)
    return names


def attendance_unit_names(host_units: dict[str, Any] | None = None) -> list[str]:
    """Return real department/unit names without requiring a current Mod build."""

    names = _names_from_host_units(host_units)
    db_path = resolve_mod_private_sqlite_path("taiyangniao_pro.db")
    if not db_path.is_file():
        return sorted(names, key=str.casefold)

    try:
        with sqlite3.connect(str(db_path)) as conn:
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for table in ("attendance_departments", "attendance_employees"):
                if table not in tables:
                    continue
                columns = {str(row[1]) for row in conn.execute(_TABLE_INFO_SQL[table]).fetchall()}
                selected = [name for name in ("department", "main_department") if name in columns]
                if not selected:
                    continue
                query = "SELECT " + ", ".join(selected) + _TABLE_FROM_SQL[table]
                for row in conn.execute(query).fetchall():
                    names.update(
                        str(value or "").strip() for value in row if str(value or "").strip()
                    )
    except sqlite3.Error:
        # The compatibility endpoint remains useful with host units even when a
        # customer-owned side database is temporarily unavailable.
        pass
    return sorted(names, key=str.casefold)


__all__ = ["attendance_unit_names"]
