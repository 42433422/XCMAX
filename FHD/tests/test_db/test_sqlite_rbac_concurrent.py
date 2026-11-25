"""Cross-connection SQLite RBAC bootstrap must serialize without granting new rights."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

from app.db.bootstrap.seeding import seed_rbac
from app.db.init_db import ensure_sqlite_rbac_bootstrap
from app.db.models.permission import DEFAULT_PERMISSIONS, DEFAULT_ROLES

_LOGGER = logging.getLogger(__name__)


def _engine(db_path):
    # Separate connections are essential: StaticPool would hide the real race.
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 10},
        poolclass=NullPool,
    )


def _seed_from_independent_connection(db_path, barrier, write_attempt=None):
    engine = _engine(db_path)
    if write_attempt is not None:
        def _watch_begin(_conn, _cursor, statement, _params, _context, _many):
            if statement.strip().upper() == "BEGIN IMMEDIATE":
                write_attempt.set()
        event.listen(engine, "before_cursor_execute", _watch_begin)
    try:
        barrier.wait(timeout=10)
        seed_rbac(engine, logger=_LOGGER)
    finally:
        engine.dispose()


def test_parallel_rbac_bootstrap_has_one_catalog_and_no_duplicate_grants(tmp_path):
    db_path = tmp_path / "rbac-concurrent.sqlite"
    engine = _engine(db_path)
    try:
        ensure_sqlite_rbac_bootstrap(engine=engine, swallow_errors=False)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM role_permissions"))
            conn.execute(text("DELETE FROM roles"))
            conn.execute(text("DELETE FROM permissions"))

        workers = 6
        barrier = Barrier(workers)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(_seed_from_independent_connection, db_path, barrier)
                for _ in range(workers)
            ]
            for future in futures:
                future.result(timeout=45)

        with engine.connect() as conn:
            codes = conn.execute(text("SELECT code FROM permissions")).scalars().all()
            roles = conn.execute(text("SELECT name FROM roles")).scalars().all()
            grants = conn.execute(
                text(
                    "SELECT r.name, p.code FROM role_permissions rp "
                    "JOIN roles r ON r.id = rp.role_id "
                    "JOIN permissions p ON p.id = rp.permission_id"
                )
            ).all()
        assert set(codes) == {row["code"] for row in DEFAULT_PERMISSIONS}
        assert len(codes) == len(set(codes))
        assert set(roles) == {row["name"] for row in DEFAULT_ROLES}
        assert len(roles) == len(set(roles))
        expected_grants = {
            (role["name"], code)
            for role in DEFAULT_ROLES
            for code in role["permissions"]
        }
        assert set(grants) == expected_grants
        assert len(grants) == len(expected_grants)
        assert all(code != "model_payment.refund" for _, code in grants)
    finally:
        engine.dispose()


def test_seed_waits_for_external_sqlite_writer_and_preserves_existing_rows(tmp_path):
    db_path = tmp_path / "rbac-writer.sqlite"
    engine = _engine(db_path)
    try:
        ensure_sqlite_rbac_bootstrap(engine=engine, swallow_errors=False)
        with engine.connect() as writer:
            writer.exec_driver_sql("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=1) as executor:
                write_attempt = Event()
                future = executor.submit(
                    _seed_from_independent_connection,
                    db_path,
                    Barrier(1),
                    write_attempt,
                )
                try:
                    assert write_attempt.wait(timeout=10)
                    assert not future.done()
                finally:
                    writer.commit()
                future.result(timeout=30)
        with engine.connect() as conn:
            codes = conn.execute(text("SELECT code FROM permissions")).scalars().all()
        assert set(codes) == {row["code"] for row in DEFAULT_PERMISSIONS}
        assert len(codes) == len(set(codes))
    finally:
        engine.dispose()
