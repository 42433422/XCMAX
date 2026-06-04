"""签收记录 SQLite（crm.sqlite3，legacy）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def _db_path() -> Path:
    from app.utils.path_utils import get_base_dir, get_data_dir

    for base in (
        Path(get_data_dir()) / "customer_service",
        Path(get_base_dir()) / "data" / "customer_service",
    ):
        base.mkdir(parents=True, exist_ok=True)
        return base / "crm.sqlite3"
    p = Path(get_data_dir()) / "customer_service"
    p.mkdir(parents=True, exist_ok=True)
    return p / "crm.sqlite3"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cs_delivery_signoffs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              opportunity_id INTEGER NOT NULL,
              market_user_id INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              signed_by TEXT NOT NULL DEFAULT '',
              signed_role TEXT NOT NULL DEFAULT 'customer',
              attachment_url TEXT NOT NULL DEFAULT '',
              notes TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              signed_at TEXT,
              FOREIGN KEY(opportunity_id) REFERENCES cs_crm_opportunities(id)
            );
            CREATE INDEX IF NOT EXISTS ix_cs_signoff_opp ON cs_delivery_signoffs(opportunity_id);
            """
        )
        conn.commit()


def insert_pending(
    *,
    opportunity_id: int,
    market_user_id: int,
    signed_by: str,
    notes: str,
    created_at: str,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO cs_delivery_signoffs (
              opportunity_id, market_user_id, status, signed_by, signed_role,
              notes, created_at
            ) VALUES (?, ?, 'pending', ?, 'customer', ?, ?)
            """,
            (int(opportunity_id), int(market_user_id), signed_by[:128], notes[:2000], created_at),
        )
        conn.commit()
        return int(cur.lastrowid)


def confirm_row(
    *,
    signoff_id: int,
    market_user_id: int,
    attachment_url: str,
    signed_at: str,
) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE cs_delivery_signoffs SET status='signed', signed_at=?, attachment_url=?
            WHERE id=? AND market_user_id=?
            """,
            (signed_at, attachment_url[:512], int(signoff_id), int(market_user_id)),
        )
        conn.commit()
        return int(cur.rowcount or 0) > 0


def count_rows() -> int:
    ensure_schema()
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM cs_delivery_signoffs").fetchone()
        return int(row["c"] if row else 0)


def list_for_market_user(market_user_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    ensure_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM cs_delivery_signoffs
            WHERE market_user_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(market_user_id), int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]
