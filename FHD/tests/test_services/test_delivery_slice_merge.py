"""Exercise both real histories and block loss before either legacy downgrade."""

import pytest
from sqlalchemy import text

from alembic import command
from app.db.db_base import Base
from tests.test_services.test_erp_schema_migration import _alembic_config
from tests.test_services.test_erp_schema_migration import _db_url as _db_url
from tests.test_services.test_etl_source_slices_migration import _FIELDS, _legacy_database

_HEAD = "2026_11_15_delivery_slices_merge"
_PRIORS = ["2026_11_15_stock_posting_key", "2026_11_15_etl_source_slices"]


def _from_history(url, prior):
    engine, original = _legacy_database(url, already_sliced=True)
    Base.metadata.create_all(engine)
    config = _alembic_config()
    command.upgrade(config, prior)
    command.upgrade(config, "head")
    return engine, config, original


def _rows(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT " + _FIELDS + ",source_slice FROM etl_run_rows ORDER BY id"
        ).all()


@pytest.mark.parametrize("prior", _PRIORS)
@pytest.mark.parametrize("target", ["2026_11_11_agent_permissions", "2026_11_15_stock_posting_key"])
def test_combined_downgrade_guards_legal_splits_before_either_branch(_db_url, prior, target):
    engine, config, _original = _from_history(_db_url, prior)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO etl_run_rows ("
                    + _FIELDS
                    + ",source_slice) SELECT 3,"
                    + _FIELDS.removeprefix("id,")
                    + ",1 FROM etl_run_rows WHERE id=1"
                )
            )
        before = _rows(engine)
        assert len(before) == 3
        with pytest.raises(RuntimeError, match="without losing ELT slice provenance"):
            command.downgrade(config, target)
        assert _rows(engine) == before
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == _HEAD
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("prior", _PRIORS)
def test_zero_slice_roundtrip_preserves_history_from_both_parents(_db_url, prior):
    engine, config, original = _from_history(_db_url, prior)
    try:
        command.downgrade(config, "2026_11_11_agent_permissions")
        command.upgrade(config, "head")
        assert _rows(engine) == [tuple(row) + (0,) for row in original]
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == _HEAD
            )
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
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == _HEAD
            )
    finally:
        engine.dispose()
