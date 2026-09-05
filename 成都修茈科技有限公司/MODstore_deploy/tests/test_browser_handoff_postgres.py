"""Optional PostgreSQL acceptance; every run owns a temporary isolated schema."""

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text, update
from sqlalchemy.orm import sessionmaker

from alembic.migration import MigrationContext
from alembic.operations import Operations
from modstore_server import browser_handoff as service
from modstore_server.db.identity import BrowserHandoffCode, User


@pytest.fixture
def postgres_handoff(monkeypatch):
    url = os.environ.get("MODSTORE_TEST_POSTGRES_URL", "")
    if not url:
        pytest.skip("Set MODSTORE_TEST_POSTGRES_URL for isolated PostgreSQL acceptance")
    admin_engine = create_engine(url)
    assert admin_engine.dialect.name == "postgresql"
    schema = f"pm_handoff_{uuid4().hex}"
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    migration_path = Path(__file__).parents[1] / "alembic/versions/20260905_browser_handoff.py"
    spec = importlib.util.spec_from_file_location("handoff_migration_acceptance", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        User.__table__.create(engine)
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()
            assert "browser_handoff_codes" in inspect(connection).get_table_names()
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        monkeypatch.setattr(service, "get_session_factory", lambda: factory)
        with factory() as session:
            session.add(
                User(
                    id=1,
                    username="pg-acceptance",
                    password_hash="synthetic",
                    account_state="active",
                )
            )
            session.commit()
        yield engine, factory, migration
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_postgres_concurrent_redemption_and_migration_round_trip(postgres_handoff):
    engine, factory, migration = postgres_handoff
    issued = service.issue_code(1, "/wallet?source=fhd&recharge=30", "wallet")

    def redeem(_):
        try:
            return service.consume_code(issued["code"], issued["target"], "wallet").id
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as workers:
        outcomes = list(workers.map(redeem, range(8)))
    assert outcomes.count(1) == 1
    assert outcomes.count(None) == 7
    with factory() as session:
        assert session.query(BrowserHandoffCode).one().consumed_at is not None
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        assert "browser_handoff_codes" not in inspect(connection).get_table_names()
        migration.upgrade()
    renewed = service.issue_code(1, "/plans?plan=vip", "plans")
    assert service.consume_code(renewed["code"], renewed["target"], "plans").id == 1


def test_postgres_expiry_and_credential_revocation(postgres_handoff):
    _engine, factory, _migration = postgres_handoff
    expired = service.issue_code(1, "/wallet", "wallet")
    with factory() as session:
        session.execute(
            update(BrowserHandoffCode).values(expires_at=datetime.utcnow() - timedelta(seconds=1))
        )
        session.commit()
    with pytest.raises(ValueError):
        service.consume_code(expired["code"], "/wallet", "wallet")
    revoked = service.issue_code(1, "/wallet", "wallet")
    with factory() as session:
        session.get(User, 1).password_hash = "changed-synthetic"
        session.commit()
    with pytest.raises(ValueError):
        service.consume_code(revoked["code"], "/wallet", "wallet")
