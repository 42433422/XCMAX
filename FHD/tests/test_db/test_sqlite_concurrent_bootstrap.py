"""Real cross-process SQLite auth/RBAC bootstrap regression.

The workers open independent SQLite connections to the same brand-new file.
Both DDL checkfirst and the read-before-insert RBAC seed must be serialized.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.db.bootstrap.seeding import seed_rbac
from app.db.models.permission import DEFAULT_PERMISSIONS, DEFAULT_ROLES, Permission, Role
from app.db.models.user import User

_WORKER = """
import sys

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.db.init_db import ensure_sqlite_auth_bootstrap, ensure_sqlite_rbac_bootstrap

engine = create_engine(
    sys.argv[1], connect_args={"timeout": 15}, poolclass=NullPool
)
print("READY", flush=True)
if sys.stdin.readline().strip() != "GO":
    raise RuntimeError("bootstrap worker was not released")
try:
    ensure_sqlite_auth_bootstrap(engine=engine, swallow_errors=False)
    ensure_sqlite_rbac_bootstrap(engine=engine, swallow_errors=False)
finally:
    engine.dispose()
"""


def _assert_default_graph(session: Session) -> None:
    permissions = session.query(Permission).all()
    assert len(permissions) == len(DEFAULT_PERMISSIONS)
    assert {perm.code for perm in permissions} == {spec["code"] for spec in DEFAULT_PERMISSIONS}
    roles = session.query(Role).all()
    assert len(roles) == len(DEFAULT_ROLES)
    expected = {spec["name"]: set(spec["permissions"]) for spec in DEFAULT_ROLES}
    actual = {role.name: {perm.code for perm in role.permissions} for role in roles}
    assert actual == expected
    assert all(role.is_system for role in roles)
    assert all("model_payment.refund" not in grants for grants in actual.values())


def test_concurrent_sqlite_bootstrap_seeds_one_consistent_permission_graph(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'concurrent.sqlite3'}"
    root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "ADMIN_USERNAME": "sqlite-bootstrap-test",
        "ADMIN_PASSWORD": "test-only-bootstrap-password",
    }
    processes: list[subprocess.Popen[str]] = []
    try:
        for _ in range(4):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-c", _WORKER, url],
                    cwd=root,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        for process in processes:
            assert process.stdout is not None
            assert process.stdout.readline().strip() == "READY", (
                "concurrent bootstrap worker failed before its start barrier"
            )
        for process in processes:
            assert process.stdin is not None
            process.stdin.write("GO\n")
            process.stdin.flush()
            process.stdin.close()
            process.stdin = None

        for process in processes:
            stdout, stderr = process.communicate(timeout=90)
            assert process.returncode == 0, (
                f"concurrent bootstrap failed with {process.returncode}: "
                f"{stdout[-500:]} {stderr[-2000:]}"
            )
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

    engine = create_engine(url, poolclass=NullPool)
    try:
        with Session(engine) as session:
            assert session.query(User).count() == 1
            _assert_default_graph(session)
    finally:
        engine.dispose()


def test_sqlite_rbac_seed_failure_rolls_back_and_retry_is_idempotent(tmp_path: Path):
    from app.db.init_db import ensure_sqlite_rbac_bootstrap

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'rollback.sqlite3'}", poolclass=NullPool
    )

    def fail_role_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO ROLES"):
            raise RuntimeError("injected role seed failure")

    try:
        event.listen(engine, "before_cursor_execute", fail_role_insert)
        try:
            with pytest.raises(RuntimeError, match="injected role seed failure"):
                ensure_sqlite_rbac_bootstrap(engine=engine, swallow_errors=False)
        finally:
            event.remove(engine, "before_cursor_execute", fail_role_insert)
        with Session(engine) as session:
            assert session.query(Permission).count() == 0
            assert session.query(Role).count() == 0
        for _ in range(2):
            ensure_sqlite_rbac_bootstrap(engine=engine, swallow_errors=False)
        with Session(engine) as session:
            _assert_default_graph(session)
    finally:
        engine.dispose()


def test_rbac_seed_waits_for_external_writer_without_expanding_grants(tmp_path: Path):
    from app.db.init_db import ensure_sqlite_rbac_bootstrap

    url = f"sqlite+pysqlite:///{tmp_path / 'writer.sqlite3'}"
    engine = create_engine(url, connect_args={"timeout": 15}, poolclass=NullPool)
    write_attempt = Event()

    def seed_from_independent_connection():
        worker = create_engine(url, connect_args={"timeout": 15}, poolclass=NullPool)

        def watch_begin(conn, cursor, statement, parameters, context, executemany):
            if statement.strip().upper() == "BEGIN IMMEDIATE":
                write_attempt.set()

        try:
            event.listen(worker, "before_cursor_execute", watch_begin)
            seed_rbac(worker, logger=logging.getLogger(__name__))
        finally:
            worker.dispose()

    try:
        ensure_sqlite_rbac_bootstrap(engine=engine, swallow_errors=False)
        with engine.connect() as writer, ThreadPoolExecutor(max_workers=1) as executor:
            writer.exec_driver_sql("BEGIN IMMEDIATE")
            future = executor.submit(seed_from_independent_connection)
            try:
                assert write_attempt.wait(timeout=10)
                assert not future.done()
            finally:
                writer.commit()
            future.result(timeout=30)
        with Session(engine) as session:
            _assert_default_graph(session)
    finally:
        engine.dispose()
