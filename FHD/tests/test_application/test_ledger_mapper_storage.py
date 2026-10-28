"""Real mapper/repository storage only; no fake tool specs or execution kernel."""

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.db.models.agent_business_action import (
    AgentBusinessActionRecord as Record,
)
from app.db.models.agent_business_action import (
    ledger_metadata,
    validate_ledger_storage,
)
from app.db.schema_migrations.business_action_ledger import (
    LedgerSchemaError,
    prepare_business_action_schema,
)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    import app.db as host

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'host.sqlite'}")
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(host, "HostSessionLocal", factory)
    repo = SQLAlchemyAgentRunRepository(auto_create=False)
    yield engine, repo
    engine.dispose()


def prepare(engine):
    with engine.begin() as conn:
        prepare_business_action_schema(Operations(MigrationContext.configure(conn)), opt_in=True)


def row(key="claim", tenant="7", mod="mod-a"):
    # Concrete persisted storage values; NOT a fabricated tool specification or actor.
    return Record(
        action_key=key,
        tenant_id=tenant,
        mod_id=mod,
        business_action_id="request",
        tool_id="synthetic-storage",
        action="storage-test",
        user_id="71",
        fingerprint="fingerprint",
        owner="owner",
        run_id="run",
        state="claimed",
        created_at="2026-10-27",
        updated_at="2026-10-27",
    )


def test_private_mapping_same_host_transaction_and_client_default(storage):
    from app.db.db_base import Base

    engine, repo = storage
    assert Record.__table__.metadata is ledger_metadata
    assert Record.__tablename__ == "agent_business_actions"
    assert "agent_business_actions" not in Base.metadata.tables
    assert sa.inspect(engine).get_table_names() == []
    prepare(engine)
    with repo.transaction() as db:
        validate_ledger_storage(db)
        db.add(row())
    with repo.transaction(read_only=True) as db:
        result = db.get(Record, "claim")
        assert result.receipt_json == "{}" and result.owner == "owner"
    with engine.connect() as conn:
        assert (
            conn.exec_driver_sql("SELECT action_key FROM agent_business_actions").scalar()
            == "claim"
        )


def test_missing_or_incompatible_schema_rejected_without_ddl(storage):
    engine, repo = storage
    with pytest.raises(LedgerSchemaError, match="missing"), repo.transaction() as db:
        validate_ledger_storage(db)
    # Raw ORM does NOT validate schema, but cannot silently create it either.
    with pytest.raises(sa.exc.OperationalError), repo.transaction(read_only=True) as db:
        db.get(Record, "missing")
    assert sa.inspect(engine).get_table_names() == []
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE agent_business_actions (action_key TEXT PRIMARY KEY)")
        before = list(conn.connection.driver_connection.iterdump())
    with pytest.raises(LedgerSchemaError), repo.transaction() as db:
        validate_ledger_storage(db)
    with engine.connect() as conn:
        assert list(conn.connection.driver_connection.iterdump()) == before


def test_unique_key_conditional_updates_rollback_and_explicit_scope(storage):
    engine, repo = storage
    prepare(engine)
    with repo.transaction() as db:
        validate_ledger_storage(db)
        db.add_all([row(), row("foreign-tenant", "8"), row("foreign-mod", mod="mod-b")])
    with pytest.raises(sa.exc.IntegrityError), repo.transaction() as db:
        db.add(row())
        db.flush()
    with repo.transaction() as db:
        validate_ledger_storage(db)
        assert (
            db.query(Record)
            .filter_by(action_key="claim", owner="wrong", state="claimed")
            .update({"receipt_json": "bad"})
            == 0
        )
        assert (
            db.query(Record)
            .filter_by(action_key="claim", owner="owner", state="claimed")
            .update({"receipt_json": '{"outcome":"unknown"}', "state": "unknown"})
            == 1
        )
        assert (
            db.query(Record)
            .filter_by(action_key="claim", owner="owner", state="claimed")
            .update({"state": "completed"})
            == 0
        )
    with pytest.raises(ValueError), repo.transaction() as db:
        db.get(Record, "claim").receipt_json = "should roll back"
        db.flush()
        raise ValueError("synthetic transaction failure")
    with repo.transaction(read_only=True) as db:
        # Isolation here is explicit consumer filtering, NOT implicit tenant RBAC.
        scoped = db.query(Record).filter_by(tenant_id="7", mod_id="mod-a").all()
        assert [r.action_key for r in scoped] == ["claim"]
        assert scoped[0].receipt_json == '{"outcome":"unknown"}'
        assert db.query(Record).count() == 3


def test_repository_clear_and_global_metadata_operations_retain_receipts(storage):
    from app.db.db_base import Base
    from app.db.models.agent import AgentRunRecord, AgentTaskCommandRecord, AgentTaskRecord

    engine, repo = storage
    prepare(engine)
    tables = [AgentRunRecord.__table__, AgentTaskRecord.__table__, AgentTaskCommandRecord.__table__]
    Base.metadata.create_all(engine, tables=tables)
    with repo.transaction() as db:
        db.add(row())
    repo.clear()
    # This is the actual metadata mechanism used by ordinary baseline downgrade.
    Base.metadata.drop_all(engine, tables=tables)
    with repo.transaction(read_only=True) as db:
        validate_ledger_storage(db)
        assert db.get(Record, "claim").receipt_json == "{}"
