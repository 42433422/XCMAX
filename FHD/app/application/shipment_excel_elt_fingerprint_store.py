"""送货单 ETL 幂等指纹库：优先主库唯一约束，失败回退本地 SQLite。"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Table

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()


def _legacy_db_path() -> Path:
    try:
        from app.utils.path_io.path_utils import get_data_dir

        root = Path(get_data_dir())
    except RECOVERABLE_ERRORS:
        root = Path.cwd() / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root / "shipment_elt_fingerprints.sqlite3"


def _legacy_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_legacy_db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shipment_elt_fingerprints (
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


def _ensure_orm_table() -> bool:
    """尽量确保主库有指纹表（兼容未跑迁移的环境）。"""
    try:
        from app.db.db_base import Base
        from app.db.models.shipment_elt_fingerprint import ShipmentEltImportFingerprint
        from app.db.session import get_db

        with get_db() as db:
            bind = db.get_bind()
            cast("Table", ShipmentEltImportFingerprint.__table__).create(bind=bind, checkfirst=True)
            # touch mapper
            _ = Base.metadata.tables.get(ShipmentEltImportFingerprint.__tablename__)
        return True
    except RECOVERABLE_ERRORS:
        logger.debug("shipment elt orm fingerprint table ensure skipped", exc_info=True)
        return False


def _use_orm_backend() -> bool:
    import os

    mode = os.environ.get("FHD_SHIPMENT_ETL_FINGERPRINT_BACKEND", "auto").strip().lower()
    if mode in {"legacy", "sqlite", "file"}:
        return False
    if mode in {"orm", "db", "sqlalchemy"}:
        return True
    return True  # auto: try ORM first


def has_fingerprint(tenant_key: str, fingerprint: str) -> bool:
    fp = str(fingerprint or "").strip()
    if not fp:
        return False
    if _use_orm_backend() and _orm_has(tenant_key, fp):
        return True
    return _legacy_has(tenant_key, fp)


def record_fingerprint(
    tenant_key: str,
    fingerprint: str,
    *,
    shipment_id: Any = None,
    unit_name: str = "",
    order_number: str = "",
    file_name: str = "",
    source_kind: str = "",
) -> None:
    fp = str(fingerprint or "").strip()
    if not fp:
        return
    if _use_orm_backend() and _orm_record(
        tenant_key,
        fp,
        shipment_id=shipment_id,
        unit_name=unit_name,
        order_number=order_number,
        file_name=file_name,
        source_kind=source_kind,
    ):
        return
    _legacy_record(
        tenant_key,
        fp,
        shipment_id=shipment_id,
        unit_name=unit_name,
        order_number=order_number,
        file_name=file_name,
    )


def delete_fingerprint(tenant_key: str, fingerprint: str) -> None:
    fp = str(fingerprint or "").strip()
    if not fp:
        return
    if _use_orm_backend():
        _orm_delete(tenant_key, fp)
    _legacy_delete(tenant_key, fp)


def _orm_has(tenant_key: str, fingerprint: str) -> bool:
    try:
        from app.db.models.shipment_elt_fingerprint import ShipmentEltImportFingerprint
        from app.db.session import get_db

        _ensure_orm_table()
        with get_db() as db:
            row = (
                db.query(ShipmentEltImportFingerprint.id)
                .filter(
                    ShipmentEltImportFingerprint.tenant_key == str(tenant_key),
                    ShipmentEltImportFingerprint.fingerprint == fingerprint,
                )
                .first()
            )
            return row is not None
    except RECOVERABLE_ERRORS:
        return False


def _orm_record(
    tenant_key: str,
    fingerprint: str,
    *,
    shipment_id: Any = None,
    unit_name: str = "",
    order_number: str = "",
    file_name: str = "",
    source_kind: str = "",
) -> bool:
    try:
        from sqlalchemy.exc import IntegrityError

        from app.db.models.shipment_elt_fingerprint import ShipmentEltImportFingerprint
        from app.db.session import get_db

        _ensure_orm_table()
        sid = None
        if shipment_id is not None and str(shipment_id).strip():
            try:
                sid = int(shipment_id)
            except (TypeError, ValueError):
                sid = None
        with get_db() as db:
            existing = (
                db.query(ShipmentEltImportFingerprint)
                .filter(
                    ShipmentEltImportFingerprint.tenant_key == str(tenant_key),
                    ShipmentEltImportFingerprint.fingerprint == fingerprint,
                )
                .first()
            )
            if existing:
                existing.shipment_id = sid if sid is not None else existing.shipment_id
                existing.unit_name = str(unit_name or existing.unit_name or "")
                existing.order_number = str(order_number or existing.order_number or "")
                existing.file_name = str(file_name or existing.file_name or "")
                existing.source_kind = str(source_kind or existing.source_kind or "")
            else:
                db.add(
                    ShipmentEltImportFingerprint(
                        tenant_key=str(tenant_key),
                        fingerprint=fingerprint,
                        shipment_id=sid,
                        unit_name=str(unit_name or ""),
                        order_number=str(order_number or ""),
                        file_name=str(file_name or ""),
                        source_kind=str(source_kind or ""),
                    )
                )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                # 并发下另一事务已插入：视为已记录
            return True
    except RECOVERABLE_ERRORS:
        logger.debug("orm fingerprint record failed; fallback legacy", exc_info=True)
        return False


def _orm_delete(tenant_key: str, fingerprint: str) -> None:
    try:
        from app.db.models.shipment_elt_fingerprint import ShipmentEltImportFingerprint
        from app.db.session import get_db

        with get_db() as db:
            db.query(ShipmentEltImportFingerprint).filter(
                ShipmentEltImportFingerprint.tenant_key == str(tenant_key),
                ShipmentEltImportFingerprint.fingerprint == fingerprint,
            ).delete(synchronize_session=False)
            db.commit()
    except RECOVERABLE_ERRORS:
        logger.debug("orm fingerprint delete failed", exc_info=True)


def _legacy_has(tenant_key: str, fingerprint: str) -> bool:
    with _LOCK:
        conn = _legacy_connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM shipment_elt_fingerprints WHERE tenant_key=? AND fingerprint=?",
                (str(tenant_key), fingerprint),
            ).fetchone()
            return row is not None
        finally:
            conn.close()


def _legacy_record(
    tenant_key: str,
    fingerprint: str,
    *,
    shipment_id: Any = None,
    unit_name: str = "",
    order_number: str = "",
    file_name: str = "",
) -> None:
    with _LOCK:
        conn = _legacy_connect()
        try:
            conn.execute(
                """
                INSERT INTO shipment_elt_fingerprints
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
                    fingerprint,
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


def _legacy_delete(tenant_key: str, fingerprint: str) -> None:
    with _LOCK:
        conn = _legacy_connect()
        try:
            conn.execute(
                "DELETE FROM shipment_elt_fingerprints WHERE tenant_key=? AND fingerprint=?",
                (str(tenant_key), fingerprint),
            )
            conn.commit()
        finally:
            conn.close()


# 兼容旧测试 monkeypatch
def _db_path() -> Path:
    return _legacy_db_path()
