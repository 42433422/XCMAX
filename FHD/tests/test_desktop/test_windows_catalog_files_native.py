"""Actual Windows kernel probes on disposable files, not catalog activation.

No platform monkeypatch, ACL changes, installer, live DB or network is used.
These tests must execute on Windows; Linux skips are explicitly not acceptance.
"""

import os
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from app.desktop_runtime.windows_catalog_files import (
    WindowsCatalogUnsupported,
    observe_sqlite_family,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="requires real Windows kernel")


def make_database(target):
    with closing(sqlite3.connect(target)) as db, db:
        db.execute("CREATE TABLE values_for_test (value INTEGER)")


def test_native_main_pin_allows_sqlite_writes_but_refuses_rename_and_delete(tmp_path):
    target = tmp_path / "catalog.sqlite"
    make_database(target)
    with observe_sqlite_family(str(target)) as snapshot:
        with closing(sqlite3.connect(target)) as db, db:
            db.execute("INSERT INTO values_for_test VALUES (1)")
            db.commit()
            assert db.execute("SELECT value FROM values_for_test").fetchall() == [(1,)]
        snapshot.recheck_main_and_ancestors()
        with pytest.raises(OSError):
            target.rename(tmp_path / "replaced.sqlite")
        with pytest.raises(OSError):
            target.unlink()
    with pytest.raises(WindowsCatalogUnsupported, match="scope is closed"):
        snapshot.recheck_main_and_ancestors()
    target.rename(tmp_path / "after-close.sqlite")


def test_native_wal_snapshot_does_not_pin_sqlite_sidecar_cleanup(tmp_path):
    target = tmp_path / "catalog.sqlite"
    db = sqlite3.connect(target)
    try:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        db.execute("CREATE TABLE values_for_test (value INTEGER)")
        db.commit()
        with observe_sqlite_family(str(target)) as snapshot:
            observations = dict(snapshot.sidecars)
            assert observations["-wal"] is not None and observations["-shm"] is not None
            with closing(sqlite3.connect(target)) as second, second:
                second.execute("INSERT INTO values_for_test VALUES (2)")
                second.commit()
            db.close()
            assert not target.with_name(target.name + "-wal").exists()
            assert not target.with_name(target.name + "-shm").exists()
            snapshot.recheck_main_and_ancestors()
    finally:
        db.close()


def test_native_hardlinked_main_and_sidecar_are_refused(tmp_path):
    target, alias = tmp_path / "catalog.sqlite", tmp_path / "alias.sqlite"
    make_database(target)
    os.link(target, alias)
    with pytest.raises(WindowsCatalogUnsupported, match="hardlink"):
        with observe_sqlite_family(str(target)):
            pytest.fail("hardlinked main accepted")
    alias.unlink()
    other = tmp_path / "other"
    other.write_bytes(b"not a SQLite sidecar")
    os.link(other, str(target) + "-wal")
    with pytest.raises(WindowsCatalogUnsupported, match="hardlink"):
        with observe_sqlite_family(str(target)):
            pytest.fail("hardlinked sidecar accepted")


def test_native_parent_junction_is_refused_without_elevation(tmp_path):
    real, junction = tmp_path / "real", tmp_path / "junction"
    real.mkdir()
    make_database(real / "catalog.sqlite")
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(real)],
        check=True,
        capture_output=True,
    )
    try:
        with pytest.raises(WindowsCatalogUnsupported):
            with observe_sqlite_family(str(junction / "catalog.sqlite")):
                pytest.fail("reparse ancestor accepted")
    finally:
        os.rmdir(junction)  # Remove only this task's junction, never its target.
