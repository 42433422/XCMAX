"""Transactional upgrade of legacy account-independent unique constraints."""

import re
import sqlite3

LEGACY_KEYS = {
    "attendance_employees": ("source_file", "employee_name", "department"),
    "attendance_departments": ("source_file", "department", "attendance_group"),
}


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _scope_columns(sql: str, columns: tuple[str, ...]) -> str:
    def replace(match):
        identifiers = tuple(value.strip().strip('"`[]').lower() for value in match[1].split(","))
        if identifiers == columns:
            return "(" + match[1] + ", owner_user_id)"
        return match[0]

    return re.sub(r"\(([^()]*)\)", replace, sql)


def upgrade_unique_constraints(conn: sqlite3.Connection, table: str) -> None:
    """Preserve row ids, extra columns, indexes, triggers, views and sequence values.

    The caller owns BEGIN IMMEDIATE with foreign_keys off and legacy_alter_table on.
    No pre-existing staging table is overwritten, even after an interrupted upgrade.
    """
    legacy = LEGACY_KEYS.get(table)
    if legacy is None:
        return
    legacy_indexes = set()
    for row in conn.execute(f"PRAGMA index_list({quote(table)})").fetchall():
        if (
            row[2]
            and tuple(item[2] for item in conn.execute(f"PRAGMA index_info({quote(row[1])})"))
            == legacy
        ):
            legacy_indexes.add(row[1])
    if not legacy_indexes:
        return

    original = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()[0]
    objects = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    sequence = None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
        sequence = conn.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (table,)).fetchone()

    staging = table + "_owner_upgrade"
    definition = original[original.index("(") :]
    definition = _scope_columns(definition, legacy)
    conn.execute(f"CREATE TABLE {quote(staging)} " + definition)
    columns = ", ".join(
        quote(row[1]) for row in conn.execute(f"PRAGMA table_xinfo({quote(table)})") if row[6] == 0
    )
    conn.execute(f"INSERT INTO {quote(staging)} ({columns}) SELECT {columns} FROM {quote(table)}")
    conn.execute(f"DROP TABLE {quote(table)}")
    conn.execute(f"ALTER TABLE {quote(staging)} RENAME TO {quote(table)}")
    for name, sql in objects:
        conn.execute(_scope_columns(sql, legacy) if name in legacy_indexes else sql)
    if sequence:
        changed = conn.execute(
            "UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name=?", (sequence[0], table)
        )
        if changed.rowcount == 0:
            conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)", (table, sequence[0]))
