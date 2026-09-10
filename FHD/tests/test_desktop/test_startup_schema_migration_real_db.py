"""End-to-end tests for ``ensure_startup_migration`` against a real SQLite DB.

Unlike ``test_startup_schema_migration.py`` (which mocks ``backup_database`` /
``run_alembic_upgrade``), these tests drive the real Alembic chain against a
throwaway SQLite database in ``tmp_path``:

* a legacy DB is built with the real ``alembic upgrade <old_revision>`` and a
  sentinel business row is written before startup migration runs;
* ``ensure_startup_migration`` upgrades it to the real chain head;
* the pre-migration hot backup is verified restorable (integrity + old stamp +
  sentinel row);
* the migrated DB carries the columns that broke the 2026-09-10 incident
  (``products.base_uom_id``, ``inventory_transactions.ordered_quantity``) and
  accepts business writes;
* a second startup is a no-op (no extra backup);
* an interrupted upgrade (ENOSPC / KeyboardInterrupt) propagates instead of
  being reported as success, and the backup survives.
"""

from __future__ import annotations

import errno
import logging
import os
import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from app.desktop_runtime import migrate
from app.desktop_runtime.paths import ensure_desktop_dirs

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _PROJECT_ROOT / "alembic.ini"

# A real, older revision that exists in the packaged chain (baseline .. head).
_LEGACY_REVISION = "2026_07_05_employee_run_logs"
_SENTINEL_MODEL = "SENTINEL-LEGACY-001"


@pytest.fixture(autouse=True)
def _isolate_env():
    """``configure_desktop_environment`` writes many os.environ keys directly."""
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


def _sqlite_url(db: Path) -> str:
    return "sqlite:///" + db.as_posix()


def _seed_legacy_db(data_dir: Path) -> Path:
    """Build a real SQLite DB stamped at an old revision with a sentinel row."""
    dirs = ensure_desktop_dirs(data_dir)
    db = dirs["data"] / "xcagi.db"
    os.environ["DATABASE_URL"] = _sqlite_url(db)

    command.upgrade(Config(str(_ALEMBIC_INI)), _LEGACY_REVISION)

    conn = sqlite3.connect(str(db))
    try:
        with conn:
            conn.execute(
                "insert into products (model_number, name, unit, is_active) values (?, ?, ?, 1)",
                (_SENTINEL_MODEL, "Legacy sentinel product", "pcs"),
            )
    finally:
        conn.close()
    return db


@pytest.fixture()
def legacy_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "xcagi-home"
    _seed_legacy_db(data_dir)
    return data_dir


def _stamped_revision(db: Path) -> str | None:
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("select version_num from alembic_version").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _count_products(db: Path, model_number: str) -> int:
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(
            "select count(*) from products where model_number = ?", (model_number,)
        ).fetchone()[0]
    finally:
        conn.close()


def _integrity_ok(db: Path) -> bool:
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def _backups(data_dir: Path) -> list[Path]:
    return sorted((data_dir / "backups").glob("xcagi-*.db"))


def test_upgrades_real_db_and_pre_migration_backup_is_restorable(
    legacy_data_dir: Path,
) -> None:
    db = legacy_data_dir / "data" / "xcagi.db"
    assert _stamped_revision(db) == _LEGACY_REVISION

    result = migrate.ensure_startup_migration(str(legacy_data_dir))

    assert result["action"] == "upgraded"
    assert _stamped_revision(db) == migrate._current_head_revision()

    backups = _backups(legacy_data_dir)
    assert len(backups) == 1
    backup = backups[0]
    assert _integrity_ok(backup)
    assert _stamped_revision(backup) == _LEGACY_REVISION
    assert _count_products(backup, _SENTINEL_MODEL) == 1

    # Business data is preserved across the migration.
    assert _count_products(db, _SENTINEL_MODEL) == 1


def test_migrated_db_has_incident_columns_and_accepts_writes(
    legacy_data_dir: Path,
) -> None:
    db = legacy_data_dir / "data" / "xcagi.db"
    migrate.ensure_startup_migration(str(legacy_data_dir))

    conn = sqlite3.connect(str(db))
    try:
        product_cols = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
        tx_cols = {row[1] for row in conn.execute("PRAGMA table_info(inventory_transactions)")}
        assert "base_uom_id" in product_cols
        assert "ordered_quantity" in tx_cols

        with conn:
            cur = conn.execute(
                "insert into products (model_number, name, unit, is_active, base_uom_id) "
                "values (?, ?, ?, 1, ?)",
                ("ROUNDTRIP-001", "Roundtrip product", "pcs", None),
            )
            product_id = cur.lastrowid
            conn.execute(
                "insert into inventory_transactions "
                "(transaction_type, product_id, warehouse_id, quantity, ordered_quantity, "
                " transaction_date) values (?, ?, ?, ?, ?, ?)",
                ("in", product_id, 1, 3, 3, "2026-09-10 00:00:00"),
            )

        product_row = conn.execute(
            "select model_number, base_uom_id from products where id = ?", (product_id,)
        ).fetchone()
        assert product_row[0] == "ROUNDTRIP-001"
        assert product_row[1] is None
        tx_row = conn.execute(
            "select ordered_quantity from inventory_transactions where product_id = ?",
            (product_id,),
        ).fetchone()
        assert float(tx_row[0]) == 3.0
    finally:
        conn.close()


def test_second_startup_is_idempotent(legacy_data_dir: Path) -> None:
    migrate.ensure_startup_migration(str(legacy_data_dir))
    backups_after_first = _backups(legacy_data_dir)
    assert len(backups_after_first) == 1

    result = migrate.ensure_startup_migration(str(legacy_data_dir))

    assert result == {"action": "skipped", "detail": "schema already at head"}
    assert _backups(legacy_data_dir) == backups_after_first


def test_disk_full_during_upgrade_propagates_and_keeps_backup(
    legacy_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = legacy_data_dir / "data" / "xcagi.db"

    def _enospc(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(migrate, "_run_alembic_cli", _enospc)

    with pytest.raises(OSError) as exc_info:
        migrate.ensure_startup_migration(str(legacy_data_dir))

    assert exc_info.value.errno == errno.ENOSPC
    # The failure must not be swallowed as a successful migration.
    assert _stamped_revision(db) == _LEGACY_REVISION

    backups = _backups(legacy_data_dir)
    assert len(backups) == 1
    assert _integrity_ok(backups[0])
    assert _stamped_revision(backups[0]) == _LEGACY_REVISION
    assert _count_products(backups[0], _SENTINEL_MODEL) == 1


def test_keyboard_interrupt_during_upgrade_propagates(
    legacy_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(migrate, "_run_alembic_cli", _interrupt)

    with pytest.raises(KeyboardInterrupt):
        migrate.ensure_startup_migration(str(legacy_data_dir))


def test_in_process_upgrade_does_not_disable_existing_app_loggers(tmp_path: Path) -> None:
    """迁移不得禁用既有 ``app.*`` logger。

    ``alembic/env.py`` 曾依赖 ``fileConfig`` 的默认 ``disable_existing_loggers=True``：
    desktop 端在 frozen 进程内以 API 方式调用 ``command.upgrade``，迁移之后所有已存在
    的 ``app.*`` logger 会被置为 ``disabled``，应用静默丢日志（同一个 pytest 会话里的
    后续用例也会因此收不到 ``caplog`` 记录）。
    """
    probe = logging.getLogger("app.desktop_runtime.probe_logger")
    assert probe.disabled is False

    _seed_legacy_db(tmp_path / "xcagi-home")  # 真实 in-process ``command.upgrade``

    assert probe.disabled is False
