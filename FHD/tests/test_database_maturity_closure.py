"""Database failure recovery and explicitly selected remote storage regressions."""

from __future__ import annotations

import multiprocessing
import os
import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from app import db as runtime_db
from app.desktop_runtime import database_profile, migrate
from app.desktop_runtime.db import check_database
from app.desktop_runtime.desktop_runtime_paths import (
    configure_desktop_environment,
    ensure_desktop_dirs,
)

REMOTE_URL = "postgresql+psycopg://test@database.invalid/customer"


@pytest.fixture(autouse=True)
def isolated_desktop(tmp_path, monkeypatch):
    with patch.dict(os.environ):
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
        for key in (
            "XCAGI_DESKTOP_DATABASE_URL",
            "XCAGI_DESKTOP_VECTOR_DB_URL",
            "XCAGI_DESKTOP_DB_RECOVERY",
            "XCAGI_DESKTOP_KEEP_DATABASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(database_profile, "_active_remote_profile", None)
        monkeypatch.setattr(runtime_db, "_get_test_db_manager", lambda: None)
        yield


def select_remote(root, *, enabled=True):
    database_profile.save_profile(
        root,
        {"mode": "remote", "remote": {"enabled": enabled, "database_url": REMOTE_URL}},
    )
    database_profile.apply_database_profile_to_env(
        root, local_sqlite_url=f"sqlite:///{root / 'data' / 'xcagi.db'}"
    )


def test_locked_healthy_database_never_restores_an_older_snapshot(tmp_path, monkeypatch):
    dirs = ensure_desktop_dirs(tmp_path)
    database = dirs["data"] / "xcagi.db"
    backup = dirs["backups"] / "xcagi-old-20261124000000.db"
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("CREATE TABLE orders(value INTEGER)")
        writer.execute("INSERT INTO orders VALUES(1)")
        writer.commit()
        with closing(sqlite3.connect(backup)) as target:
            writer.backup(target)
        writer.execute("UPDATE orders SET value=2")
        writer.commit()
        original, old_backup = database.read_bytes(), backup.read_bytes()
        writer.execute("BEGIN EXCLUSIVE")

        # Exercise real SQLITE_BUSY with a short wait, not a substituted check result.
        connect = sqlite3.connect
        monkeypatch.setattr(
            sqlite3, "connect", lambda *a, **kw: connect(*a, **{**kw, "timeout": 0.01})
        )
        check = check_database(database)
        assert check.state == "unavailable"
        assert check.sqlite_errorcode == sqlite3.SQLITE_BUSY
        assert migrate.recover_if_corrupt(tmp_path)["action"] == "unavailable"
        with pytest.raises(RuntimeError, match="check unavailable"):
            configure_desktop_environment(tmp_path)
        assert os.environ["XCAGI_DESKTOP_DB_RECOVERY"] == "unavailable"
        assert database.read_bytes() == original
        assert backup.read_bytes() == old_backup
        assert not list(dirs["data"].glob("*.corrupt-*"))
        assert not (tmp_path / "config" / "database-recovery-required").exists()
        writer.rollback()

    configure_desktop_environment(tmp_path)
    assert "XCAGI_DESKTOP_DB_RECOVERY" not in os.environ
    with closing(sqlite3.connect(database)) as current:
        assert current.execute("SELECT value FROM orders").fetchone() == (2,)


def test_readonly_check_with_pending_journal_preserves_the_entire_database_image(tmp_path):
    dirs = ensure_desktop_dirs(tmp_path)
    database = dirs["data"] / "xcagi.db"
    backup = dirs["backups"] / "xcagi-old.db"
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("CREATE TABLE orders(value INTEGER)")
        writer.execute("INSERT INTO orders VALUES(1)")
        writer.commit()
        with closing(sqlite3.connect(backup)) as target:
            writer.backup(target)
        writer.execute("UPDATE orders SET value=2")
        writer.commit()
    journal = database.with_name(database.name + "-journal")
    journal.write_bytes(b"original journal evidence")
    original, old_backup = database.read_bytes(), backup.read_bytes()

    check = check_database(database)
    assert check.state == "unavailable"
    assert check.sqlite_errorcode is not None
    assert check.sqlite_errorcode & 0xFF == sqlite3.SQLITE_READONLY
    assert migrate.recover_if_corrupt(tmp_path)["action"] == "unavailable"
    with pytest.raises(RuntimeError, match="check unavailable"):
        configure_desktop_environment(tmp_path)
    assert database.read_bytes() == original
    assert journal.read_bytes() == b"original journal evidence"
    assert backup.read_bytes() == old_backup
    assert not list(database.parent.glob("*.corrupt-*"))
    assert not (tmp_path / "config" / "database-recovery-required").exists()


@pytest.mark.parametrize(
    "code", [sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_CANTOPEN]
)
def test_inconclusive_storage_errors_preserve_database(tmp_path, monkeypatch, code):
    database = ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE preserved(value INTEGER)")
    before = database.read_bytes()
    failure = sqlite3.OperationalError("storage temporarily unavailable")
    failure.sqlite_errorcode = code

    def unavailable(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(sqlite3, "connect", unavailable)
    assert check_database(database).state == "unavailable"
    assert migrate.recover_if_corrupt(tmp_path)["action"] == "unavailable"
    assert database.read_bytes() == before
    assert not list(database.parent.glob("*.corrupt-*"))


@pytest.mark.parametrize("failure", [TimeoutError, PermissionError])
def test_migration_lock_failure_never_marks_a_healthy_database_corrupt(
    tmp_path, monkeypatch, failure
):
    database = ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE preserved(value INTEGER)")
    before = database.read_bytes()

    def unavailable_lock(_root):
        raise failure("migration lock unavailable")

    monkeypatch.setattr(migrate, "migration_lock", unavailable_lock)
    assert migrate.recover_if_corrupt(tmp_path)["action"] == "unavailable"
    with pytest.raises(RuntimeError, match="check unavailable"):
        configure_desktop_environment(tmp_path)
    assert os.environ["XCAGI_DESKTOP_DB_RECOVERY"] == "unavailable"
    assert database.read_bytes() == before
    assert not list(database.parent.glob("*.corrupt-*"))
    assert not (tmp_path / "config" / "database-recovery-required").exists()


def test_unresolved_corruption_cannot_bootstrap_an_empty_replacement(tmp_path):
    database = ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    database.write_bytes(b"corrupt database with no usable backup")
    for _ in range(2):
        with pytest.raises(RuntimeError, match="recovery is unresolved"):
            migrate.ensure_startup_migration(tmp_path)
        assert not database.exists()
        assert (tmp_path / "config" / "database-recovery-required").is_file()


def test_explicit_remote_profile_controls_business_and_host_database(tmp_path):
    select_remote(tmp_path)
    # Other initialization must not replace the profile's chosen database.
    os.environ["DATABASE_URL"] = "sqlite:///stale-local.db"
    assert runtime_db._get_database_url() == REMOTE_URL
    assert runtime_db._resolve_host_database_url() == REMOTE_URL
    assert os.environ["DATABASE_URL"] == REMOTE_URL
    assert runtime_db._sqlite_desktop_mode() is False


def _resolve_spawned_database(result):
    # A spawned interpreter has no parent profile cache or desktop bootstrap.
    assert database_profile._active_remote_profile is None
    with patch.object(runtime_db, "_get_test_db_manager", return_value=None):
        result.send(
            (
                runtime_db._get_database_url(),
                runtime_db._resolve_host_database_url(),
                runtime_db._sqlite_desktop_mode(),
            )
        )
    result.close()


def test_spawned_worker_reads_explicit_profile_without_connecting(tmp_path):
    select_remote(tmp_path)
    os.environ["DATABASE_URL"] = "sqlite:///stale-parent.db"
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=_resolve_spawned_database, args=(sender,))
    try:
        child.start()
        sender.close()
        assert receiver.poll(30), "spawned resolver did not return"
        assert receiver.recv() == (REMOTE_URL, REMOTE_URL, False)
        child.join(5)
        assert child.exitcode == 0
        assert not (tmp_path / "data" / "xcagi.db").exists()
    finally:
        if child.is_alive():
            child.kill()
            child.join(5)
        receiver.close()
        sender.close()
        child.close()


def test_desktop_bootstrap_reloads_profile_after_cache_loss(tmp_path, monkeypatch):
    select_remote(tmp_path)
    monkeypatch.setattr(database_profile, "_active_remote_profile", None)
    configure_desktop_environment(tmp_path)
    assert runtime_db._get_database_url() == REMOTE_URL
    assert runtime_db._resolve_host_database_url() == REMOTE_URL
    assert not (tmp_path / "data" / "xcagi.db").exists()


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        "[]",
        "null",
        '{"mode":"invalid"}',
        '{"remote":false}',
        '{"remote":{"enabled":true,"database_url":""}}',
    ],
)
def test_existing_invalid_profile_never_changes_database_selection(tmp_path, content):
    path = database_profile.profile_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(content)
    os.environ["DATABASE_URL"] = REMOTE_URL
    for apply in (
        lambda: database_profile.apply_database_profile_to_env(
            tmp_path, local_sqlite_url="sqlite:///wrong.db"
        ),
        lambda: configure_desktop_environment(tmp_path),
        lambda: database_profile.configured_remote_database_url(tmp_path),
    ):
        with pytest.raises(RuntimeError, match="profile is invalid"):
            apply()
        assert os.environ["DATABASE_URL"] == REMOTE_URL
        assert path.read_text() == content
        assert not (tmp_path / "data" / "xcagi.db").exists()


def test_unreadable_profile_does_not_boot_an_empty_local_database(tmp_path, monkeypatch):
    select_remote(tmp_path)
    path = database_profile.profile_path(tmp_path)
    original_read = type(path).read_text

    def read(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError("profile temporarily inaccessible")
        return original_read(candidate, *args, **kwargs)

    monkeypatch.setattr(type(path), "read_text", read)
    with pytest.raises(PermissionError):
        database_profile.apply_database_profile_to_env(
            tmp_path, local_sqlite_url="sqlite:///wrong.db"
        )
    with pytest.raises(PermissionError):
        configure_desktop_environment(tmp_path)
    assert os.environ["DATABASE_URL"] == REMOTE_URL
    assert not (tmp_path / "data" / "xcagi.db").exists()


def test_empty_profile_object_is_a_valid_local_default(tmp_path):
    path = database_profile.profile_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    configure_desktop_environment(tmp_path)
    assert runtime_db._get_database_url() == f"sqlite:///{tmp_path / 'data' / 'xcagi.db'}"


def test_inherited_remote_flags_do_not_authorize_a_remote_database(tmp_path):
    os.environ["DATABASE_URL"] = REMOTE_URL
    os.environ["XCAGI_DESKTOP_KEEP_DATABASE_URL"] = "1"
    assert runtime_db._get_database_url() == f"sqlite:///{tmp_path / 'data' / 'xcagi.db'}"
    assert runtime_db._sqlite_desktop_mode() is True


def test_disabling_remote_profile_clears_the_applied_selection(tmp_path):
    select_remote(tmp_path)
    assert runtime_db._get_database_url() == REMOTE_URL
    select_remote(tmp_path, enabled=False)
    assert runtime_db._get_database_url() == f"sqlite:///{tmp_path / 'data' / 'xcagi.db'}"
    assert runtime_db._sqlite_desktop_mode() is True


def test_remote_selection_is_scoped_to_its_desktop_data_root(tmp_path, monkeypatch):
    select_remote(tmp_path)
    other_root = tmp_path / "other-profile"
    monkeypatch.setenv("XCAGI_DATA_DIR", str(other_root))
    assert runtime_db._get_database_url() == f"sqlite:///{other_root / 'data' / 'xcagi.db'}"


@pytest.mark.parametrize("revision", ["current", "older"])
def test_remote_startup_only_inspects_schema_and_preserves_business_data(
    tmp_path, monkeypatch, revision
):
    select_remote(tmp_path)
    # A real SQLAlchemy connection / Alembic context exercises the schema probe;
    # no external PostgreSQL instance is contacted by this regression.
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL)")
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES(?)", (revision,))
        connection.exec_driver_sql("CREATE TABLE customer_records(value INTEGER)")
        connection.exec_driver_sql("INSERT INTO customer_records VALUES(42)")
    monkeypatch.setattr(runtime_db, "get_host_engine", lambda: engine)
    monkeypatch.setattr(migrate, "_known_alembic_heads", lambda: ["current"])

    def forbid_mutation(*_args, **_kwargs):
        pytest.fail("desktop startup must not migrate or stamp the shared database")

    monkeypatch.setattr(migrate, "_run_alembic_cli", forbid_mutation)
    monkeypatch.setattr(migrate, "bootstrap_sqlite_schema", forbid_mutation)
    try:
        if revision == "current":
            assert migrate.ensure_startup_migration(tmp_path) == {
                "action": "skipped",
                "detail": "remote schema already at head",
            }
        else:
            with pytest.raises(RuntimeError, match="requires explicit server migration"):
                migrate.ensure_startup_migration(tmp_path)
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
                == revision
            )
            assert connection.exec_driver_sql("SELECT value FROM customer_records").scalar() == 42
        assert not (tmp_path / "data" / "xcagi.db").exists()
    finally:
        engine.dispose()


def test_remote_profile_refuses_local_migration_and_backup_helpers(tmp_path):
    select_remote(tmp_path)
    with pytest.raises(RuntimeError, match="explicit server migration workflow"):
        migrate.run_alembic_upgrade(tmp_path)
    with pytest.raises(RuntimeError, match="server backup workflow"):
        migrate.backup_database(tmp_path)
    assert not (tmp_path / "data" / "xcagi.db").exists()
