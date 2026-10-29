"""Upgrade legacy ETL storage without promoting or changing existing uploads."""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError

from app.db.etl_bootstrap import ensure_sqlite_etl_bootstrap
from app.db.models.etl import EltSourceAsset, EltSourceRevision, EtlUpload

SOURCE = Path(__file__).resolve().parents[2] / "alembic/versions/2026_10_29_elt_sources.py"
spec = importlib.util.spec_from_file_location("elt_source_migration", SOURCE)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def _apply(engine, function):
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        function()


def _upload(upload_id, *, retained=False):
    return {
        "id": upload_id,
        "tenant_id": 1,
        "owner_user_id": 7,
        "file_name": "original.csv",
        "suffix": ".csv",
        "size_bytes": 4,
        "sha256": "a" * 64,
        "storage_path": f"/originals/{upload_id}.csv",
        "expires_at": None if retained else datetime(2026, 11, 5),
    }


@pytest.fixture(params=["bootstrap", "migration"])
def upgraded(request, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    EtlUpload.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(EtlUpload.__table__.insert(), _upload("legacy"))
    if request.param == "bootstrap":
        for _ in range(2):
            ensure_sqlite_etl_bootstrap(engine, swallow_errors=False)
        _apply(engine, migration.upgrade)
    else:
        for _ in range(2):
            _apply(engine, migration.upgrade)
    yield engine
    engine.dispose()


def test_upgrade_preserves_legacy_upload_and_creates_no_sources(upgraded):
    with upgraded.connect() as connection:
        upload = connection.execute(select(EtlUpload.__table__)).mappings().one()
        assert upload["id"] == "legacy"
        assert upload["storage_path"] == "/originals/legacy.csv"
        assert upload["expires_at"] == datetime(2026, 11, 5)
        assert connection.execute(select(EltSourceAsset.__table__)).all() == []
        assert connection.execute(select(EltSourceRevision.__table__)).all() == []


def _create_source(engine):
    with engine.begin() as connection:
        connection.execute(
            EtlUpload.__table__.insert(),
            [_upload("v1", retained=True), _upload("v2", retained=True)],
        )
        connection.execute(
            EltSourceAsset.__table__.insert(),
            {"id": "asset", "tenant_id": 1, "owner_user_id": 7, "name": "考勤资料"},
        )
        connection.execute(
            EltSourceRevision.__table__.insert(),
            {
                "id": "revision",
                "tenant_id": 1,
                "owner_user_id": 7,
                "asset_id": "asset",
                "version": 1,
                "upload_id": "v1",
            },
        )


@pytest.mark.parametrize(
    ("asset_id", "version", "upload_id"),
    [
        ("asset", 1, "v2"),
        ("asset", 2, "v1"),
        ("asset2", 1, "v1"),
        ("missing", 1, "v2"),
        ("asset", 2, "missing"),
    ],
)
def test_revisions_reject_reused_versions_uploads_and_missing_references(
    upgraded, asset_id, version, upload_id
):
    _create_source(upgraded)
    with upgraded.begin() as connection:
        connection.execute(
            EltSourceAsset.__table__.insert(),
            {"id": "asset2", "tenant_id": 1, "owner_user_id": 7, "name": "另一份资料"},
        )
    with pytest.raises(IntegrityError), upgraded.begin() as connection:
        connection.execute(
            EltSourceRevision.__table__.insert(),
            {
                "id": "invalid",
                "tenant_id": 1,
                "owner_user_id": 7,
                "asset_id": asset_id,
                "version": version,
                "upload_id": upload_id,
            },
        )


def test_retained_revision_defaults_and_required_tenant(upgraded):
    _create_source(upgraded)
    with upgraded.connect() as connection:
        asset = connection.execute(select(EltSourceAsset.__table__)).mappings().one()
        revision = connection.execute(select(EltSourceRevision.__table__)).mappings().one()
        assert asset["current_version"] == 1
        assert isinstance(revision["created_at"], datetime)
        assert (
            connection.execute(
                select(EtlUpload.expires_at).where(EtlUpload.id == revision["upload_id"])
            ).scalar_one()
            is None
        )
    with pytest.raises(IntegrityError), upgraded.begin() as connection:
        connection.execute(
            EltSourceAsset.__table__.insert(),
            {"id": "unowned", "tenant_id": None, "owner_user_id": 7, "name": "无归属"},
        )


def test_migration_downgrade_preserves_all_uploads(upgraded):
    _create_source(upgraded)
    _apply(upgraded, migration.downgrade)
    _apply(upgraded, migration.downgrade)
    assert not {"elt_source_assets", "elt_source_revisions"} & set(
        inspect(upgraded).get_table_names()
    )
    with upgraded.connect() as connection:
        assert connection.execute(select(EtlUpload.id).order_by(EtlUpload.id)).scalars().all() == [
            "legacy",
            "v1",
            "v2",
        ]
    _apply(upgraded, migration.upgrade)
    with upgraded.connect() as connection:
        assert connection.execute(select(EltSourceRevision.id)).all() == []


def test_source_migration_extends_the_single_head():
    config = Config()
    config.set_main_option("script_location", str(SOURCE.parents[1]))
    assert ScriptDirectory.from_config(config).get_current_head() == migration.revision
