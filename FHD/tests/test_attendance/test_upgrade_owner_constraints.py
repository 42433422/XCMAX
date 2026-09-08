"""Upgrade a real legacy database without losing rows or schema objects."""

import importlib.util
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "XCAGI/mods/attendance-industry/backend"


@pytest.fixture
def migration():
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    spec = importlib.util.spec_from_file_location("upgrade_owner_scope", BACKEND / "owner_scope.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def legacy_database(path, *, owned=False):
    with sqlite3.connect(path) as db:
        owner = ", owner_user_id TEXT NOT NULL DEFAULT ''" if owned else ""
        db.execute(
            "CREATE TABLE attendance_employees (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "source_file TEXT NOT NULL DEFAULT 'manual', employee_name TEXT NOT NULL, "
            "department TEXT NOT NULL DEFAULT '', custom_note TEXT DEFAULT 'retained'"
            + owner
            + ", UNIQUE(source_file, employee_name, department))"
        )
        db.execute(
            "CREATE TABLE attendance_departments (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "source_file TEXT NOT NULL DEFAULT 'manual', department TEXT NOT NULL, "
            "attendance_group TEXT NOT NULL DEFAULT ''"
            + owner
            + ", UNIQUE(source_file, department, attendance_group))"
        )
        db.execute(
            "INSERT INTO attendance_employees(id, employee_name, department) VALUES (7, 'Alice', 'Ops')"
        )
        db.execute("INSERT INTO attendance_departments(id, department) VALUES (9, 'Ops')")
        if owned:
            for table in ("attendance_employees", "attendance_departments"):
                db.execute(f"UPDATE {table} SET owner_user_id='existing-owner'")
        db.execute("CREATE INDEX employee_note_idx ON attendance_employees(custom_note)")
        db.execute("CREATE TABLE audit_events (employee_id INTEGER)")
        db.execute(
            "CREATE TRIGGER employee_added AFTER INSERT ON attendance_employees BEGIN INSERT INTO audit_events VALUES (new.id); END"
        )
        db.execute(
            "CREATE VIEW employee_names AS SELECT id, employee_name FROM attendance_employees"
        )
        db.execute(
            "CREATE TABLE attendance_daily_records (id INTEGER PRIMARY KEY, employee_id INTEGER REFERENCES attendance_employees(id), work_date TEXT)"
        )
        db.execute("INSERT INTO attendance_daily_records VALUES (1,7,'2026-09-01')")
        # Preserve AUTOINCREMENT's high-water mark, including previously deleted rows.
        db.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='attendance_employees'")


@pytest.mark.parametrize("owned", [False, True])
def test_upgrade_preserves_data_references_objects_and_owner(migration, tmp_path, owned):
    path = tmp_path / "legacy.sqlite"
    legacy_database(path, owned=owned)
    migration.migrate_owner_column(path)
    migration.migrate_owner_column(path)
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT id, custom_note, owner_user_id FROM attendance_employees"
        ).fetchall() == [(7, "retained", "existing-owner" if owned else "SUNBIRD")]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT * FROM employee_names").fetchall() == [(7, "Alice")]
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='employee_note_idx'"
        ).fetchone()
        db.execute(
            "INSERT INTO attendance_employees(employee_name,department,owner_user_id) VALUES ('Alice','Ops','second-owner')"
        )
        assert db.execute("SELECT employee_id FROM audit_events").fetchall() == [(101,)]
        db.execute(
            "INSERT INTO attendance_departments(department,owner_user_id) VALUES ('Ops','second-owner')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO attendance_employees(employee_name,department,owner_user_id) VALUES ('Alice','Ops','second-owner')"
            )


def test_database_replaced_at_same_path_is_rechecked(migration, tmp_path):
    path = tmp_path / "restored.sqlite"
    legacy_database(path)
    migration.migrate_owner_column(path)
    path.unlink()
    legacy_database(path)
    migration.migrate_owner_column(path)
    with sqlite3.connect(path) as db:
        assert "owner_user_id" in {
            row[1] for row in db.execute("PRAGMA table_info(attendance_employees)")
        }


def test_two_migration_instances_serialize_on_database(tmp_path, migration):
    path = tmp_path / "concurrent.sqlite"
    legacy_database(path)
    spec = importlib.util.spec_from_file_location("second_upgrade", BACKEND / "owner_scope.py")
    second = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(second)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(module.migrate_owner_column, path) for module in (migration, second)]
        for job in jobs:
            job.result(timeout=10)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM attendance_employees").fetchone()[0] == 1
        db.execute(
            "INSERT INTO attendance_employees(employee_name,department,owner_user_id) VALUES ('Alice','Ops','other')"
        )


def test_failed_schema_rebuild_rolls_back_entire_migration(migration, tmp_path):
    path = tmp_path / "conflict.sqlite"
    legacy_database(path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE attendance_employees_owner_upgrade (important TEXT)")
        db.execute("INSERT INTO attendance_employees_owner_upgrade VALUES ('preserve me')")
    with pytest.raises(sqlite3.Error):
        migration.migrate_owner_column(path)
    with sqlite3.connect(path) as db:
        assert "owner_user_id" not in {
            r[1] for r in db.execute("PRAGMA table_info(attendance_employees)")
        }
        assert db.execute("SELECT * FROM attendance_employees_owner_upgrade").fetchall() == [
            ("preserve me",)
        ]
        assert db.execute("SELECT id FROM attendance_employees").fetchall() == [(7,)]
