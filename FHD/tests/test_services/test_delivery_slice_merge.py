"""Exercise both real histories and block loss before either legacy downgrade."""

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy import text

from alembic import command
from app.db.db_base import Base
from tests.test_services.test_erp_schema_migration import _alembic_config
from tests.test_services.test_erp_schema_migration import _db_url as _db_url
from tests.test_services.test_etl_source_slices_migration import _FIELDS, _legacy_database

# 历史交付合并修订 2026_11_15_delivery_slices_merge 保持不变；
# upgrade("head") 的现行戳是更晚的单头。
_PRIORS = ["2026_11_15_stock_posting_key", "2026_11_15_etl_source_slices"]


def _current_head(config) -> str:
    heads = ScriptDirectory.from_config(config).get_heads()
    assert heads == [heads[0]]
    return heads[0]


def _run_rows_table(engine) -> str:
    names = set(sa.inspect(engine).get_table_names())
    if "elt_run_rows" in names:
        return "elt_run_rows"
    if "etl_run_rows" in names:
        return "etl_run_rows"
    raise AssertionError("run-rows table missing after upgrade")


def _from_history(url, prior):
    engine, original = _legacy_database(url, already_sliced=True)
    Base.metadata.create_all(engine)
    config = _alembic_config()
    command.upgrade(config, prior)
    command.upgrade(config, "head")
    return engine, config, original


def _rows(engine):
    table = _run_rows_table(engine)
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT " + _FIELDS + f",source_slice FROM {table} ORDER BY id"
        ).all()


def _assert_current_head(engine, config):
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == _current_head(config)


@pytest.mark.parametrize("prior", _PRIORS)
@pytest.mark.parametrize("target", ["2026_11_11_agent_permissions", "2026_11_15_stock_posting_key"])
def test_combined_downgrade_guards_legal_splits_before_either_branch(_db_url, prior, target):
    engine, config, _original = _from_history(_db_url, prior)
    try:
        table = _run_rows_table(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO {table} ("
                    + _FIELDS
                    + ",source_slice) SELECT 3,"
                    + _FIELDS.removeprefix("id,")
                    + f",1 FROM {table} WHERE id=1"
                )
            )
        before = _rows(engine)
        assert len(before) == 3
        with pytest.raises(RuntimeError, match="without losing ELT slice provenance"):
            command.downgrade(config, target)
        assert _rows(engine) == before
        _assert_current_head(engine, config)
    finally:
        engine.dispose()


@pytest.mark.parametrize("prior", _PRIORS)
def test_zero_slice_roundtrip_preserves_history_from_both_parents(_db_url, prior):
    engine, config, original = _from_history(_db_url, prior)
    try:
        command.downgrade(config, "2026_11_11_agent_permissions")
        command.upgrade(config, "head")
        assert _rows(engine) == [tuple(row) + (0,) for row in original]
        _assert_current_head(engine, config)
        table = _run_rows_table(engine)
        assert table == "elt_run_rows"
        # 测试夹具中的 canary 列不是生产列；改名收回旧表后应仍保留。
        with engine.connect() as connection:
            assert "legacy_audit" in {
                column["name"] for column in sa.inspect(connection).get_columns(table)
            }
            assert "etl_run_rows" not in set(sa.inspect(connection).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.parametrize("prior", _PRIORS)
@pytest.mark.parametrize("target", _PRIORS)
def test_zero_slice_partial_parent_downgrade_cannot_leave_a_false_schema_stamp(
    _db_url, prior, target
):
    engine, config, _original = _from_history(_db_url, prior)
    try:
        before = _rows(engine)
        with pytest.raises(
            RuntimeError, match="Cannot partially downgrade merged delivery histories"
        ):
            command.downgrade(config, target)
        assert _rows(engine) == before
        _assert_current_head(engine, config)
    finally:
        engine.dispose()
