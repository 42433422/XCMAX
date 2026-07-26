from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.db import schema_contract


def test_schema_contract_accepts_exact_head(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('head-a')"))
    monkeypatch.setattr(schema_contract, "expected_schema_heads", lambda: {"head-a"})

    schema_contract.assert_database_schema_at_head(engine)


@pytest.mark.parametrize("current", [None, "old-head"])
def test_schema_contract_rejects_unversioned_or_stale_database(
    monkeypatch: pytest.MonkeyPatch,
    current: str | None,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    if current is not None:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)")
            )
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:version)"),
                {"version": current},
            )
    monkeypatch.setattr(schema_contract, "expected_schema_heads", lambda: {"head-a"})

    with pytest.raises(schema_contract.SchemaMigrationRequired, match="Run `alembic"):
        schema_contract.assert_database_schema_at_head(engine)


def test_production_entrypoint_has_no_migration_bypass() -> None:
    root = Path(__file__).resolve().parents[2]
    entrypoint = (root / "docker" / "docker-entrypoint-fhd-api.sh").read_text(encoding="utf-8")
    compose = (root / "docker" / "docker-compose.fhd-prod.yml").read_text(encoding="utf-8")

    assert "FHD_SKIP_ALEMBIC" not in entrypoint
    assert "FHD_SKIP_ALEMBIC" not in compose
    assert "DATABASE_URL is required" in entrypoint
    assert "alembic -c alembic.ini upgrade head" in entrypoint
    assert "current --check-heads" in entrypoint


def test_desktop_bootstrap_migrates_before_backend_start() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "desktop" / "main.ts").read_text(encoding="utf-8")
    bootstrap = source[source.index("function bootstrap()") :]

    migrate_at = bootstrap.index("await runBackendMigration()")
    backend_at = bootstrap.index("await startBackend()")
    assert migrate_at < backend_at


def test_first_long_revision_widens_postgres_alembic_version_before_early_return() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = (
        root / "alembic" / "versions" / "2026_07_24_shipment_etl_fingerprints.py"
    ).read_text(encoding="utf-8")

    widen_at = migration.index(
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"
    )
    early_return_at = migration.index("if insp.has_table(_TABLE)")
    assert widen_at < early_return_at
