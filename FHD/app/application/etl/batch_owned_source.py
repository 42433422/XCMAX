"""Versioned real-price catalog composition; never selects or adopts a legacy database."""

import sqlite3
from asyncio import current_task
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from threading import get_ident

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.application.etl.errors import EtlError
from app.mod_sdk.owned_price_catalog import CatalogPurpose

PROTOCOL = "etl-owned-sql-v1"
MIXED_PROTOCOL = "etl-owned-mixed-v1"
_operation_owner = ContextVar("etl_owned_operation", default=None)


def _foreign_keys(connection, _record):
    connection.execute("PRAGMA foreign_keys=ON")


def _read_only(connection, _record):
    # URI mode=ro protects main even if query_only is reset. Also prohibit temp
    # writes and attachments on this fresh, private physical connection.
    connection.execute("PRAGMA query_only=ON")

    def authorize(action, first, second, _database, _trigger):
        if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH} or (
            action == sqlite3.SQLITE_PRAGMA
            and second is not None
            and first
            not in {
                "table_info",
                "table_xinfo",
                "index_list",
                "index_info",
                "index_xinfo",
                "foreign_key_list",
                "foreign_key_check",
            }
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorize)


def unverified():
    return EtlError(
        "ETL_BATCH_RECOVERY_SOURCE_UNVERIFIED",
        "原数据库来源世代尚未核验，未执行恢复；请核对原回执，勿重复撤销",
        status_code=503,
    )


class OwnedSqlSessions:
    """Every plan, upload, effect and journal uses the validated physical connection."""

    def __init__(self, principal, *, mixed=False, purpose=CatalogPurpose.ETL, lock_timeout=0):
        from app.application.etl.owned_sql_session import _read_only_url
        from app.mod_sdk.owned_price_catalog import resolve_owned_price_catalog

        self.principal, self.mixed, self.purpose = principal, mixed, purpose
        self.lock_timeout = lock_timeout
        self.target, self.source = resolve_owned_price_catalog(
            principal, mixed=mixed, purpose=purpose, lock_timeout=lock_timeout
        )
        self.binding = {"protocol": MIXED_PROTOCOL if mixed else PROTOCOL, **asdict(self.source)}
        self.upload_root = self.target.parent / (
            "mixed-originals-v1" if mixed else "price-catalog-originals-v1"
        )
        self.engine = create_engine(
            _read_only_url(self.target)
            if purpose is CatalogPurpose.READ
            else "sqlite:///" + str(self.target),
            poolclass=NullPool,
            connect_args={"check_same_thread": False},
        )
        event.listen(self.engine, "connect", _foreign_keys)
        if purpose is CatalogPurpose.READ:
            event.listen(self.engine, "connect", _read_only)
        self.raw_sessions = sessionmaker(self.engine)
        self.knowledge = None
        if mixed:
            from app.application.dataset_rag.owned_store import OwnedKnowledge

            with self.guard():
                self.knowledge = OwnedKnowledge(self)
                self.binding["knowledge_store_id"] = self.knowledge.store_id

    @contextmanager
    def guard(self):
        from app.desktop_runtime.database_generation_registry import (
            _owned_lock,
            target_database_lock,
        )
        from app.mod_sdk.owned_price_catalog import validate_catalog_scope

        try:
            task = current_task()
        except RuntimeError:
            task = None
        owner = (self, get_ident(), task)
        if _operation_owner.get() == owner:
            _owned_lock(self.target, None)
            validate_catalog_scope(
                self.principal, self.target, self.source, mixed=self.mixed, purpose=self.purpose
            )
            yield
            return
        with target_database_lock(self.target, lock_timeout=self.lock_timeout):
            token = _operation_owner.set(owner)
            try:
                validate_catalog_scope(
                    self.principal, self.target, self.source, mixed=self.mixed, purpose=self.purpose
                )
                yield
            finally:
                _operation_owner.reset(token)

    def validate(self, db):
        from app.desktop_runtime.database_generation_registry import validate_owned_source
        from app.mod_sdk.owned_price_catalog import validate_price_catalog

        connection = db.connection().connection.driver_connection
        if connection.execute("PRAGMA foreign_keys").fetchone() != (1,) or (
            self.purpose is CatalogPurpose.READ
            and connection.execute("PRAGMA query_only").fetchone() != (1,)
        ):
            raise unverified()
        validate_owned_source(connection, self.target, self.source)
        validate_price_catalog(connection, mixed=self.mixed)
        db.info["etl_owned_source"] = self.binding
        db.info["etl_owned_upload_root"] = str(self.upload_root)

    @contextmanager
    def __call__(self):
        from app.application.etl.owned_sql_session import _fresh_target_session

        with (
            self.guard(),
            _fresh_target_session(
                self.raw_sessions, self.target, read_only=self.purpose is CatalogPurpose.READ
            ) as db,
        ):
            self.validate(db)
            yield db
