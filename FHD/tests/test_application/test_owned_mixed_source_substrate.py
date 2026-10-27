"""Explicit synthetic enrollment only; no host migration, catalog save or activation."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

PERMISSIONS = [
    "etl.execute",
    "product.edit",
    "dataset.read",
    "dataset.write",
    "etl.template.manage",
]


@pytest.fixture
def host(trusted_actor, monkeypatch, tmp_path):
    from app.db.models.agent_business_action import AgentBusinessActionRecord
    from app.db.models.product_edit_claim import ProductEditClaimRecord
    from app.desktop_runtime import database_generation_registry as g

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "control"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.delenv("XCAGI_OWNED_SOURCE_PROFILE", raising=False)
    monkeypatch.setattr(g, "_owned_profile", None)
    actor = trusted_actor(role="admin", mod_id="test-mod", permissions=PERMISSIONS)
    engine = actor.factory.kw["bind"]
    # Explicit test-only real HOST tables, never enrollment/startup DDL.
    AgentBusinessActionRecord.__table__.create(engine)
    ProductEditClaimRecord.__table__.create(engine)
    with engine.connect() as db:
        assert db.exec_driver_sql("PRAGMA journal_mode=WAL").scalar() == "wal"
    config = SimpleNamespace(OWNED_SOURCE_PROFILE="guarded-host-v1", DATABASE_URL=str(engine.url))
    g.configure_owned_source_profile(config)
    return SimpleNamespace(actor=actor, engine=engine, config=config, create_actor=trusted_actor)


def enrolled(host):
    from app.application.etl.batch_owned_source import OwnedSqlSessions
    from app.mod_sdk.owned_price_catalog import provision_owned_price_catalog

    source = provision_owned_price_catalog(host.actor.principal, confirmed=True, mixed=True)
    factory = OwnedSqlSessions(host.actor.principal, mixed=True)
    assert factory.source == source
    return factory


def test_private_models_leave_host_base_and_default_bootstrap_unchanged(tmp_path):
    from app.db.db_base import Base
    from app.db.models.owned_source import OwnedSourceBase
    from app.db.models.product_edit_claim import ProductEditClaimBase
    from app.desktop_runtime import database_generation_registry as g

    private = {"product_price_history", "etl_price_dimensions", "agent_product_edit_claims"}
    assert not private.intersection(Base.metadata.tables)
    assert set(OwnedSourceBase.metadata.tables) == private - {"agent_product_edit_claims"}
    assert set(ProductEditClaimBase.metadata.tables) == {"agent_product_edit_claims"}
    engine = create_engine(f"sqlite:///{tmp_path / 'ordinary.sqlite'}")
    Base.metadata.create_all(engine)
    with engine.connect() as db:
        tables = set(
            db.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars()
        )
    assert not private.intersection(tables)
    g.configure_owned_source_profile(SimpleNamespace())
    assert g._owned_profile is None
    with pytest.raises(g.GenerationObservationError):
        g.require_owned_source_profile()
    engine.dispose()


def test_fresh_enrollment_real_models_fk_knowledge_and_rollback(host):
    from app.db.models.owned_source import EtlPriceDimension, ProductPriceHistory
    from app.db.models.product import Product
    from app.infrastructure.tenant_scope import tenant_scope
    from app.mod_sdk.owned_price_catalog import validate_price_catalog

    factory = enrolled(host)
    with factory.guard():
        assert factory.knowledge.validate()["store_id"] == factory.binding["knowledge_store_id"]
    with factory() as db, tenant_scope(7):
        db.add(Product(id=1, tenant_id=7, name="catalog-only", price=10))
        db.flush()
        db.add(
            ProductPriceHistory(
                product_id=1,
                tenant_id=7,
                owner_user_id=host.actor.user_id,
                period_label="initial",
                price=10,
                source_key="a" * 64,
                provenance_json="{}",
            )
        )
        db.add(
            EtlPriceDimension(
                product_id=1,
                tenant_id=7,
                currency="CNY",
                price_unit="个",
                source_digest="b" * 64,
                reviewer_id=host.actor.user_id,
            )
        )
        db.commit()
    with factory() as db, tenant_scope(7):
        assert db.scalars(select(ProductPriceHistory)).one().product_id == 1
        assert db.scalars(select(EtlPriceDimension)).one().currency == "CNY"
        db.add(Product(id=2, tenant_id=7, name="rollback"))
        db.flush()
        # Leaving pinned Session rolls back before releasing the target lock.
    with sqlite3.connect(factory.target) as db:
        validate_price_catalog(db, mixed=True)
        assert db.execute("SELECT id FROM products").fetchall() == [(1,)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='agent_product_edit_claims'"
        ).fetchall()
    with host.engine.connect() as db:
        assert db.exec_driver_sql("SELECT count(*) FROM products").scalar() == 0


@pytest.mark.parametrize("change", ["missing", "nonwal", "unsupported", "desktop"])
def test_profile_refuses_unprepared_host_before_enrollment(host, monkeypatch, change):
    from app.desktop_runtime import database_generation_registry as g
    from app.mod_sdk.owned_price_catalog import catalog_path, provision_owned_price_catalog

    if change == "missing":
        with host.engine.begin() as db:
            db.exec_driver_sql("DROP TABLE agent_product_edit_claims")
    elif change == "nonwal":
        with host.engine.connect() as db:
            db.exec_driver_sql("PRAGMA journal_mode=DELETE")
    elif change == "unsupported":
        monkeypatch.setattr(g.sys, "platform", "unsupported")
    else:
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    with pytest.raises((g.GenerationObservationError, RuntimeError)):
        g.configure_owned_source_profile(host.config)
    with pytest.raises(g.GenerationObservationError):
        provision_owned_price_catalog(host.actor.principal, confirmed=True, mixed=True)
    assert not catalog_path("7", "test-mod", mixed=True).exists()


@pytest.mark.parametrize(
    "tamper", ["index", "temp-table", "temp-view", "temp-trigger", "main-trigger"]
)
def test_host_claim_exact_schema_validator_no_mutation(host, tamper):
    from app.db.models.product_edit_claim import validate_product_edit_claim_schema

    with host.engine.connect() as db:
        commands = {
            "index": "CREATE INDEX extra_claim_index ON agent_product_edit_claims(user_id)",
            "temp-table": "CREATE TEMP TABLE agent_product_edit_claims(fake TEXT)",
            "temp-view": "CREATE TEMP VIEW agent_product_edit_claims AS SELECT 1",
            "temp-trigger": "CREATE TEMP TRIGGER extra_claim_trigger AFTER INSERT ON main.agent_product_edit_claims BEGIN SELECT 1; END",
            "main-trigger": "CREATE TRIGGER extra_claim_trigger AFTER INSERT ON agent_product_edit_claims BEGIN SELECT 1; END",
        }
        db.exec_driver_sql(commands[tamper])
        before = db.exec_driver_sql(
            "SELECT type,name,sql FROM sqlite_master UNION ALL SELECT type,name,sql FROM sqlite_temp_master"
        ).all()
        with pytest.raises(RuntimeError):
            validate_product_edit_claim_schema(db)
        assert (
            db.exec_driver_sql(
                "SELECT type,name,sql FROM sqlite_master UNION ALL SELECT type,name,sql FROM sqlite_temp_master"
            ).all()
            == before
        )


def test_existing_source_never_adopted_or_retried(host):
    from app.mod_sdk.owned_price_catalog import catalog_path, provision_owned_price_catalog

    target = catalog_path("7", "test-mod", mixed=True)
    target.parent.mkdir(parents=True)
    with sqlite3.connect(target) as db:
        db.execute("CREATE TABLE customer_data(value TEXT)")
        db.execute("INSERT INTO customer_data VALUES ('keep')")
        db.commit()
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        provision_owned_price_catalog(host.actor.principal, confirmed=True, mixed=True)
    assert target.read_bytes() == before


@pytest.mark.parametrize("confirmed", [False, "true", 1, None])
def test_enrollment_requires_explicit_true(host, confirmed):
    from app.mod_sdk.owned_price_catalog import catalog_path, provision_owned_price_catalog

    with pytest.raises(ValueError):
        provision_owned_price_catalog(host.actor.principal, confirmed=confirmed, mixed=True)
    assert not catalog_path("7", "test-mod", mixed=True).exists()


def test_actor_tenant_mod_forgery_and_revocation(host):
    from app.db.models.user import Session as UserSession
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError
    from app.mod_sdk.owned_price_catalog import (
        provision_owned_price_catalog,
        resolve_owned_price_catalog,
    )

    factory = enrolled(host)
    principal = host.actor.principal
    for bad in (
        replace(principal, tenant_id="8"),
        replace(principal, user_id="9999"),
        replace(principal, actor_authorization={}),
        replace(
            principal, mod_authorization={**principal.mod_authorization, "mod_id": "foreign-mod"}
        ),
    ):
        with pytest.raises((ValueError, AgentModAuthorizationError)):
            resolve_owned_price_catalog(bad, mixed=True)
    foreign = host.create_actor(
        tenant_id=8, role="admin", mod_id="test-mod", permissions=PERMISSIONS
    )
    from app.desktop_runtime.database_generation_registry import GenerationObservationError

    with pytest.raises(GenerationObservationError):
        resolve_owned_price_catalog(foreign.principal, mixed=True)
    with host.actor.factory.begin() as db:
        db.delete(db.get(UserSession, host.actor.session_row_id))
    with pytest.raises((ValueError, AgentModAuthorizationError)):
        with factory():
            pytest.fail("revoked actor reached source session")


def test_closed_failed_initialization_retained_and_no_adoption(host):
    from app.desktop_runtime import database_generation_registry as g
    from app.mod_sdk.owned_price_catalog import catalog_path

    target = catalog_path("7", "test-mod", mixed=True)
    target.parent.mkdir(parents=True)

    def fail(_):
        raise RuntimeError("initializer-failed")

    with pytest.raises(RuntimeError, match="initializer-failed"):
        g.enroll_owned_source(target, host.actor.context, [], validate_schema=fail)
    original = target.read_bytes()
    assert g.read_owned_source(target, allow_closed=True)
    with pytest.raises(g.GenerationObservationError):
        g.read_owned_source(target)
    with pytest.raises(g.GenerationObservationError):
        g.enroll_owned_source(target, host.actor.context, [])
    assert target.read_bytes() == original


@pytest.mark.parametrize("tamper", ["epoch", "inode", "schema", "knowledge", "head", "intent"])
def test_source_generation_and_head_tampering_fail_closed(host, tamper):
    from app.application.dataset_rag.store_identity import StoreIdentityError
    from app.desktop_runtime import database_generation_registry as g

    factory = enrolled(host)
    if tamper == "inode":
        backup = factory.target.with_suffix(".copy")
        backup.write_bytes(factory.target.read_bytes())
        backup.replace(factory.target)
    elif tamper == "knowledge":
        raw = json.loads(factory.knowledge.path.read_text())
        raw["documents"] = [{"unexpected": True}]
        factory.knowledge.path.write_text(json.dumps(raw))
    elif tamper == "intent":
        with g.target_database_lock(factory.target):
            g.write_owned_source_epoch(
                factory.target, factory.source, factory.source, state="closed"
            )
            g.record_restore_intent(factory.target, "a" * 64)
    else:
        with sqlite3.connect(factory.target) as db:
            if tamper == "epoch":
                db.execute("UPDATE etl_database_generation SET generation_id='bad'")
            elif tamper == "schema":
                db.execute("CREATE TABLE surprise(value TEXT)")
            else:
                db.execute("UPDATE workflow_plans SET runtime_context='{}'")
            db.commit()
    with pytest.raises((g.GenerationObservationError, StoreIdentityError, ValueError)):
        with factory.guard():
            factory.knowledge.validate()


def test_pinned_session_refuses_custom_creator_and_foreign_target(host):
    from app.application.etl.owned_sql_session import _fresh_target_session
    from app.desktop_runtime.database_generation_registry import GenerationObservationError

    factory = enrolled(host)
    bad = create_engine(
        "sqlite:///" + str(factory.target), creator=lambda: sqlite3.connect(factory.target)
    )
    with pytest.raises(GenerationObservationError):
        with _fresh_target_session(sessionmaker(bad), factory.target):
            pytest.fail("custom creator admitted")
    with pytest.raises(GenerationObservationError):
        with _fresh_target_session(host.actor.factory, factory.target):
            pytest.fail("foreign physical source admitted")
    bad.dispose()


def test_lifecycle_refuses_legacy_host_restore_and_preserves_receipts(host):
    from app.desktop_runtime import database_generation_registry as g

    factory = enrolled(host)
    with host.engine.begin() as db:
        db.exec_driver_sql(
            "INSERT INTO agent_product_edit_claims VALUES (?,?,?,?,?,?,?,?,?)",
            ("r", "o", "7", str(host.actor.user_id), "test-mod", "1", "d", "run", "now"),
        )
    with pytest.raises(g.GenerationObservationError):
        with g.owned_source_lifecycle(
            host_target=Path(host.engine.url.database), legacy_restore=True
        ):
            pytest.fail("legacy rewind admitted")
    with host.engine.connect() as db:
        assert db.exec_driver_sql("SELECT operation_key FROM agent_product_edit_claims").all() == [
            ("o",)
        ]
    assert factory.target.exists()


@pytest.mark.parametrize(
    "role,permissions",
    [
        ("reader", PERMISSIONS),
        ("admin-missing", ["product.edit"]),
        ("tenant:7:limited", PERMISSIONS),
    ],
)
def test_missing_provisioning_role_or_actual_rbac_refused(host, role, permissions):
    from app.mod_sdk.owned_price_catalog import provision_owned_price_catalog

    actor = host.create_actor(role=role, permissions=permissions, mod_id="test-mod")
    with pytest.raises(ValueError):
        provision_owned_price_catalog(actor.principal, confirmed=True, mixed=True)


def test_pending_knowledge_receipt_retained_no_inferred_completion(host):
    from app.application.dataset_rag.store_identity import StoreIdentityError

    factory = enrolled(host)
    with sqlite3.connect(factory.target) as db:
        encoded = db.execute("SELECT runtime_context FROM workflow_plans").fetchone()[0]
        state = json.loads(encoded)
        state["pending"] = {"attempt": "interrupted-original"}
        state["effects"] = {"prior-operation": {"retained": "original-receipt"}}
        changed = json.dumps(state)
        db.execute("UPDATE workflow_plans SET runtime_context=?", (changed,))
        db.commit()
    with pytest.raises(StoreIdentityError, match="original receipt"):
        with factory.guard():
            factory.knowledge.validate()
    with sqlite3.connect(factory.target) as db:
        assert db.execute("SELECT runtime_context FROM workflow_plans").fetchone()[0] == changed


def test_schema_and_temporary_shadow_rejected_on_actual_connection(host):
    from app.desktop_runtime.database_generation_registry import GenerationObservationError

    factory = enrolled(host)
    with factory() as db:
        db.connection().exec_driver_sql("CREATE TEMP VIEW products AS SELECT 1 AS id")
        with pytest.raises(GenerationObservationError):
            factory.validate(db)


def test_nested_guard_exception_restores_ownership(host):
    from app.desktop_runtime import database_generation_registry as g

    factory = enrolled(host)
    with pytest.raises(RuntimeError, match="test-error"):
        with factory.guard(), factory.guard():
            with factory() as db:
                assert db.info["etl_owned_source"] == factory.binding
            raise RuntimeError("test-error")
    with pytest.raises(g.GenerationObservationError, match="held target"):
        g._owned_lock(factory.target, None)
    with factory() as db:
        assert db.connection().exec_driver_sql("SELECT 1").scalar() == 1


@pytest.mark.parametrize(
    "table",
    [
        "agent_business_actions",
        "agent_runs",
        "agent_task_executions",
        "agent_approval_consumptions",
    ],
)
@pytest.mark.parametrize("fault", ["missing", "malformed", "temp-shadow"])
def test_host_runtime_schema_blocks_enrollment_before_creation(host, monkeypatch, table, fault):
    from app import db as host_db
    from app.desktop_runtime import database_generation_registry as g
    from app.mod_sdk.owned_price_catalog import catalog_path, provision_owned_price_catalog

    with host.engine.connect() as connection:
        if fault == "temp-shadow":
            connection.exec_driver_sql("CREATE TEMP TABLE " + table + " (wrong_contract TEXT)")
        else:
            connection.exec_driver_sql("DROP TABLE " + table)
            if fault == "malformed":
                connection.exec_driver_sql("CREATE TABLE " + table + " (wrong_contract TEXT)")
        connection.commit()
        # TEMP belongs to the actual checked connection, never another pool slot.
        monkeypatch.setattr(host_db, "HostSessionLocal", sessionmaker(bind=connection))
        with pytest.raises((RuntimeError, ValueError)):
            g.configure_owned_source_profile(host.config)
        assert g._owned_profile is None
        with pytest.raises(g.GenerationObservationError):
            provision_owned_price_catalog(host.actor.principal, confirmed=True, mixed=True)
        assert not catalog_path("7", "test-mod", mixed=True).exists()
        if fault != "missing":
            assert connection.exec_driver_sql("SELECT count(*) FROM " + table).scalar() == 0


@pytest.mark.parametrize(
    "table", ["agent_runs", "agent_task_executions", "agent_approval_consumptions"]
)
@pytest.mark.parametrize("fault", ["index", "trigger", "temp-view", "temp-trigger", "constraint"])
def test_host_runtime_exact_constraints_and_shadows_unchanged_on_refusal(host, table, fault):
    from app.db.schema_migrations.owned_source_host import validate_owned_host_runtime_schema

    with host.engine.connect() as db:
        if fault == "index":
            db.exec_driver_sql("CREATE UNIQUE INDEX unexpected_index ON " + table + "(run_id)")
        elif fault == "trigger":
            db.exec_driver_sql(
                "CREATE TRIGGER unexpected_trigger AFTER INSERT ON "
                + table
                + " BEGIN SELECT 1; END"
            )
        elif fault == "temp-view":
            db.exec_driver_sql("CREATE TEMP VIEW " + table + " AS SELECT 1")
        elif fault == "temp-trigger":
            db.exec_driver_sql(
                "CREATE TEMP TRIGGER unexpected_trigger AFTER INSERT ON main."
                + table
                + " BEGIN SELECT 1; END"
            )
        else:
            ddl = db.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name=?", (table,)
            ).scalar_one()
            db.exec_driver_sql("DROP TABLE " + table)
            # A new CHECK is not silently accepted as the original contract.
            db.exec_driver_sql(ddl[: ddl.rfind(")")] + ", CHECK (1=1))")
        before = db.exec_driver_sql(
            "SELECT type,name,sql FROM sqlite_master UNION ALL SELECT type,name,sql FROM sqlite_temp_master"
        ).all()
        with pytest.raises(RuntimeError):
            validate_owned_host_runtime_schema(db)
        assert (
            db.exec_driver_sql(
                "SELECT type,name,sql FROM sqlite_master UNION ALL SELECT type,name,sql FROM sqlite_temp_master"
            ).all()
            == before
        )


@pytest.mark.parametrize(
    "table",
    [
        "agent_business_actions",
        "agent_runs",
        "agent_task_executions",
        "agent_approval_consumptions",
    ],
)
def test_host_schema_drift_after_profile_preparation_blocks_new_source(host, table):
    from app.mod_sdk.owned_price_catalog import catalog_path, provision_owned_price_catalog

    with host.engine.begin() as db:
        db.exec_driver_sql("DROP TABLE " + table)
        db.exec_driver_sql("CREATE TABLE " + table + " (wrong_contract TEXT)")
    with pytest.raises((ValueError, RuntimeError)):
        provision_owned_price_catalog(host.actor.principal, confirmed=True, mixed=True)
    assert not catalog_path("7", "test-mod", mixed=True).exists()
