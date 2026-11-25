"""Real cross-process SQLite auth/RBAC bootstrap regression.

The workers open independent SQLite connections to the same brand-new file.
Both DDL checkfirst and the read-before-insert RBAC seed must be serialized.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

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
            process.stdin.write("GO\\n")
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
            assert session.query(Permission).count() == len(DEFAULT_PERMISSIONS)
            assert session.query(Role).count() == len(DEFAULT_ROLES)
            roles = {role.name: role for role in session.query(Role).all()}
            for role_spec in DEFAULT_ROLES:
                role = roles[role_spec["name"]]
                assert role.is_system
                assert {permission.code for permission in role.permissions} == set(
                    role_spec["permissions"]
                )
    finally:
        engine.dispose()
