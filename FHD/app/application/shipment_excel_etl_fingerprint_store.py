"""送货单 ETL 幂等指纹库（SQLite，按租户隔离，单条成功即落盘）。"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _db_path() -> Path:
    try:
        from app.utils.path_utils import get_data_dir

        root = Path(get_data_dir())
    except Exception:
        root = Path.cwd() / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root / "shipment_etl_fingerprints.sqlite3"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shipment_etl_fingerprints (
            tenant_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            shipment_id TEXT,
            unit_name TEXT,
            order_number TEXT,
            file_name TEXT,
            imported_at TEXT NOT NULL,
            PRIMARY KEY (tenant_key, fingerprint)
        )
        """
    )
    conn.commit()
    return conn


def has_fingerprint(tenant_key: str, fingerprint: str) -> bool:
    fp = str(fingerprint or "").strip()
    if not fp:
        return False
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM shipment_etl_fingerprints WHERE tenant_key=? AND fingerprint=?",
                (str(tenant_key), fp),
            ).fetchone()
            return row is not None
        finally:
            conn.close()


def get_fingerprint(tenant_key: str, fingerprint: str) -> dict[str, Any] | None:
    fp = str(fingerprint or "").strip()
    if not fp:
        return None
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM shipment_etl_fingerprints WHERE tenant_key=? AND fingerprint=?",
                (str(tenant_key), fp),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def record_fingerprint(
    tenant_key: str,
    fingerprint: str,
    *,
    shipment_id: Any = None,
    unit_name: str = "",
    order_number: str = "",
    file_name: str = "",
) -> None:
    fp = str(fingerprint or "").strip()
    if not fp:
        return
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO shipment_etl_fingerprints
                    (tenant_key, fingerprint, shipment_id, unit_name, order_number, file_name, imported_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_key, fingerprint) DO UPDATE SET
                    shipment_id=excluded.shipment_id,
                    unit_name=excluded.unit_name,
                    order_number=excluded.order_number,
                    file_name=excluded.file_name,
                    imported_at=excluded.imported_at
                """,
                (
                    str(tenant_key),
                    fp,
                    str(shipment_id) if shipment_id is not None else None,
                    str(unit_name or ""),
                    str(order_number or ""),
                    str(file_name or ""),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
