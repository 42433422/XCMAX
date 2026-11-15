"""Actual forward DDL preserves old rows and fails closed on lossy downgrade."""

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from alembic import command
from tests.test_services.test_erp_schema_migration import _alembic_config
from tests.test_services.test_erp_schema_migration import _db_url as _db_url

_OLD = "2026_11_11_business_ref_unique"
_HEAD = "2026_11_15_etl_source_slices"
_FIELDS = "id,run_id,tenant_id,owner_user_id,source_sheet,source_row,source_json,provenance_json,legacy_audit"


def _legacy_database(url, *, already_sliced=False):
    engine = sa.create_engine(url)
    slice_column = "source_slice INTEGER NOT NULL DEFAULT 0," if already_sliced else ""
    constraint = (
        "CONSTRAINT uq_etl_run_source_slice UNIQUE (run_id,source_sheet,source_row,source_slice)"
        if already_sliced
        else "CONSTRAINT uq_etl_run_source_row UNIQUE (run_id,source_sheet,source_row)"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE etl_runs (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO etl_runs (id) VALUES ('run')")
        connection.exec_driver_sql(
            "CREATE TABLE etl_run_rows (id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES etl_runs(id),"
            "tenant_id INTEGER NOT NULL,owner_user_id INTEGER NOT NULL,source_sheet TEXT NOT NULL,"
            "source_row INTEGER NOT NULL,source_json TEXT NOT NULL,provenance_json TEXT NOT NULL,"
            "legacy_audit TEXT NOT NULL," + slice_column + constraint + ")"
        )
        for identifier in (1, 2):
            connection.execute(
                sa.text(
                    "INSERT INTO etl_run_rows ("
                    + _FIELDS
                    + ") VALUES (:id,'run',17,21,'原表',:row,:source,:provenance,:audit)"
                ),
                {
                    "id": identifier,
                    "row": identifier + 1,
                    "source": '{"原件":"保留"}',
                    "provenance": '{"table_id":"原表!T1"}',
                    "audit": "audit-" + str(identifier),
                },
            )
        original = connection.exec_driver_sql(
            "SELECT " + _FIELDS + " FROM etl_run_rows ORDER BY id"
        ).all()
    command.stamp(_alembic_config(), _OLD)
    return engine, original


@pytest.mark.parametrize("already_sliced", [False, True])
def test_forward_upgrade_preserves_every_legacy_field_and_accepts_distinct_slices(
    _db_url, already_sliced
):
    engine, original = _legacy_database(_db_url, already_sliced=already_sliced)
    config = _alembic_config()
    command.upgrade(config, _HEAD)
    command.upgrade(config, _HEAD)
    with engine.begin() as connection:
        assert (
            connection.exec_driver_sql("SELECT " + _FIELDS + " FROM etl_run_rows ORDER BY id").all()
            == original
        )
        assert connection.exec_driver_sql(
            "SELECT source_slice FROM etl_run_rows ORDER BY id"
        ).scalars().all() == [0, 0]
        uniques = {
            item["name"] for item in sa.inspect(connection).get_unique_constraints("etl_run_rows")
        }
        assert "uq_etl_run_source_row" not in uniques
        assert "uq_etl_run_source_slice" in uniques
        foreign_keys = sa.inspect(connection).get_foreign_keys("etl_run_rows")
        assert foreign_keys[0]["referred_table"] == "etl_runs"
        insert = "INSERT INTO etl_run_rows (id,run_id,tenant_id,owner_user_id,source_sheet,source_row,source_json,provenance_json,legacy_audit,source_slice) VALUES (:id,'run',17,21,'原表',2,'{}','{}','new',:slice)"
        connection.execute(sa.text(insert), {"id": 3, "slice": 1})
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(sa.text(insert), {"id": 4, "slice": 1})
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(sa.text(insert.replace("'run'", "'missing'")), {"id": 5, "slice": 2})
        assert connection.exec_driver_sql("SELECT count(*) FROM etl_run_rows").scalar_one() == 3
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM etl_run_rows WHERE tenant_id=17 AND owner_user_id=21"
            ).scalar_one()
            == 3
        )
    engine.dispose()


def test_zero_slice_downgrade_reupgrade_preserves_legacy_history(_db_url):
    engine, original = _legacy_database(_db_url)
    config = _alembic_config()
    command.upgrade(config, _HEAD)
    command.downgrade(config, _OLD)
    with engine.connect() as connection:
        assert "source_slice" not in {
            item["name"] for item in sa.inspect(connection).get_columns("etl_run_rows")
        }
        assert (
            connection.exec_driver_sql("SELECT " + _FIELDS + " FROM etl_run_rows ORDER BY id").all()
            == original
        )
    command.upgrade(config, _HEAD)
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT " + _FIELDS + " FROM etl_run_rows ORDER BY id").all()
            == original
        )
    engine.dispose()


def test_downgrade_refuses_losing_real_slices_before_any_ddl(_db_url):
    engine, original = _legacy_database(_db_url)
    config = _alembic_config()
    command.upgrade(config, _HEAD)
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE etl_run_rows SET source_slice=1 WHERE id=2")
    with pytest.raises(RuntimeError, match="without losing provenance"):
        command.downgrade(config, _OLD)
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT " + _FIELDS + " FROM etl_run_rows ORDER BY id").all()
            == original
        )
        assert connection.exec_driver_sql(
            "SELECT source_slice FROM etl_run_rows ORDER BY id"
        ).scalars().all() == [0, 1]
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == _HEAD
        )
    engine.dispose()


def test_new_revision_extends_current_main_without_another_head():
    scripts = ScriptDirectory.from_config(_alembic_config())
    assert scripts.get_heads() == ["2026_11_15_delivery_slices_merge"]
    assert _HEAD in scripts.get_revision(scripts.get_current_head()).down_revision
    assert scripts.get_revision(_HEAD).down_revision == _OLD
