"""Server-selected read capability, physical write denial and private response evidence."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

from app.application.etl.batch_owned_source import OwnedSqlSessions
from app.db.models.product import Product
from app.desktop_runtime.database_generation_registry import GenerationObservationError
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError
from app.infrastructure.tenant_scope import tenant_scope
from app.mod_sdk.owned_price_catalog import (
    CatalogPurpose,
    provision_owned_price_catalog,
    resolve_owned_price_catalog,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_owned_mixed_source_substrate import host as host


@pytest.fixture(params=[False, True], ids=["price", "mixed"])
def catalog(host, request):
    mixed = request.param
    provision_owned_price_catalog(host.actor.principal, confirmed=True, mixed=mixed)
    writer = OwnedSqlSessions(host.actor.principal, mixed=mixed)
    actor = host.create_actor(
        role="user", mod_id="test-mod", permissions=["product.view", "dataset.read"]
    )
    reader = OwnedSqlSessions(actor.principal, mixed=mixed, purpose=CatalogPurpose.READ)
    with writer() as db, tenant_scope(7):
        db.add(Product(id=1, tenant_id=7, name="original", price=10))
        db.commit()
    try:
        yield writer, reader, actor
    finally:
        writer.engine.dispose()
        reader.engine.dispose()


def test_minimal_read_permissions_without_write_grants_or_shared_session_state(catalog):
    writer, reader, actor = catalog
    for _ in range(2):
        with reader.guard(), reader() as db, tenant_scope(7):
            assert db.scalars(select(Product)).one().name == "original"
            assert db.connection().exec_driver_sql("PRAGMA query_only").scalar() == 1
            assert db.info["etl_owned_source"] == writer.binding
            if reader.knowledge:
                assert reader.knowledge.validate()["store_id"] == writer.knowledge.store_id
        with writer() as db:
            assert db.connection().exec_driver_sql("PRAGMA query_only").scalar() == 0
            db.connection().exec_driver_sql("UPDATE products SET price=11 WHERE id=1")
            db.commit()
    for action in (
        lambda: OwnedSqlSessions(actor.principal, mixed=reader.mixed),
        lambda: resolve_owned_price_catalog(actor.principal, mixed=reader.mixed),
        lambda: provision_owned_price_catalog(actor.principal, confirmed=True, mixed=reader.mixed),
    ):
        with pytest.raises(ValueError):
            action()


@pytest.mark.parametrize("permission", ["product.view", "dataset.read"])
def test_read_revalidates_each_required_permission_on_nested_and_fresh_use(catalog, permission):
    from app.db.models.permission import Role

    _, reader, actor = catalog
    with reader.guard():
        with actor.factory.begin() as db:
            role = db.query(Role).filter_by(name="user").one()
            role.permissions = [item for item in role.permissions if item.code != permission]
        with pytest.raises(ValueError), reader():
            pytest.fail("nested read ignored permission revocation")
    with pytest.raises(ValueError):
        OwnedSqlSessions(actor.principal, mixed=reader.mixed, purpose=CatalogPurpose.READ)
    with pytest.raises(ValueError), reader():
        pytest.fail("fresh read ignored permission revocation")


@pytest.mark.parametrize("purpose", ["read", "READ", None, True, {"purpose": "read"}])
def test_purpose_is_an_explicit_server_enum_not_request_data(host, purpose):
    with pytest.raises(ValueError):
        OwnedSqlSessions(host.actor.principal, mixed=True, purpose=purpose)


@pytest.mark.parametrize(
    "change", ["tenant", "mod", "actor", "session", "epoch", "inode", "schema"]
)
def test_read_preserves_actor_owner_and_physical_source_guards(catalog, change):
    from app.db.models.user import Session as UserSession

    writer, reader, actor = catalog
    if change == "tenant":
        reader.principal = replace(reader.principal, tenant_id="8")
    elif change == "mod":
        reader.principal = replace(
            reader.principal,
            mod_authorization={**reader.principal.mod_authorization, "mod_id": "other-mod"},
        )
    elif change == "actor":
        reader.principal = replace(reader.principal, actor_authorization={})
    elif change == "session":
        with actor.factory.begin() as db:
            db.delete(db.get(UserSession, actor.session_row_id))
    elif change == "inode":
        copy = writer.target.with_suffix(".copy")
        copy.write_bytes(writer.target.read_bytes())
        copy.replace(writer.target)
    else:
        with sqlite3.connect(writer.target) as db:
            db.execute(
                "UPDATE etl_database_generation SET generation_id='changed'"
                if change == "epoch"
                else "CREATE TABLE unexpected(value TEXT)"
            )
    with (
        pytest.raises((ValueError, AgentModAuthorizationError, GenerationObservationError)),
        reader(),
    ):
        pytest.fail("changed actor/source reached read session")


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO products(id,tenant_id,name) VALUES(2,7,'bad')",
        "UPDATE products SET name='bad'",
        "DELETE FROM products",
        "DELETE FROM workflow_plans",
        "CREATE TABLE unexpected(value TEXT)",
        "CREATE TEMP TABLE products(value TEXT)",
        "PRAGMA query_only=OFF",
        "PRAGMA writable_schema=ON",
        "ATTACH DATABASE ':memory:' AS other",
    ],
)
def test_read_denies_raw_sql_mutations_and_escape_hatches(catalog, sql):
    writer, reader, _ = catalog
    with reader() as db:
        with pytest.raises(DatabaseError):
            db.connection().exec_driver_sql(sql)
        db.rollback()
        reader.validate(db)
        assert (
            db.connection().exec_driver_sql("SELECT name FROM products").scalar_one() == "original"
        )
    with writer() as db:
        assert (
            db.connection().exec_driver_sql("SELECT name FROM products").scalar_one() == "original"
        )


@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
def test_read_denies_orm_flush(catalog, operation):
    _, reader, _ = catalog
    with reader() as db, tenant_scope(7):
        product = db.get(Product, 1)
        if operation == "insert":
            db.add(Product(tenant_id=7, name="bad"))
        elif operation == "update":
            product.name = "bad"
        else:
            db.delete(product)
        with pytest.raises(DatabaseError):
            db.flush()
        db.rollback()
        assert db.get(Product, 1).name == "original"


def test_read_is_physically_readonly_even_without_authorizer_or_query_only(catalog):
    from app.application.etl.errors import EtlError

    _, reader, _ = catalog
    with reader() as db:
        physical = db.connection().connection.driver_connection
        physical.set_authorizer(None)  # Synthetic proof that mode=ro, not a flag, enforces main.
        physical.execute("PRAGMA query_only=OFF")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            physical.execute("UPDATE products SET name='bad'")
        assert physical.execute("SELECT name FROM products").fetchone() == ("original",)
        with pytest.raises(EtlError):
            reader.validate(db)


def test_explicit_read_session_cannot_delegate_to_writer(catalog):
    from app.application.etl.owned_sql_session import _fresh_target_session

    writer, reader, _ = catalog
    with (
        pytest.raises(GenerationObservationError),
        _fresh_target_session(writer, writer.target, read_only=True),
    ):
        pytest.fail("explicit read silently delegated to writable ETL factory")
    with _fresh_target_session(reader, reader.target) as db:
        with pytest.raises(DatabaseError):
            db.connection().exec_driver_sql("DELETE FROM products")


def test_read_rejects_rw_creator_disguised_with_ro_url(catalog):
    _, reader, _ = catalog
    substitute = create_engine("sqlite:///" + str(reader.target))
    substitute.url = reader.engine.url
    original = reader.raw_sessions
    reader.raw_sessions = sessionmaker(substitute)
    try:
        with pytest.raises(GenerationObservationError, match="connection arguments"), reader():
            pytest.fail("read engine metadata authorized a writable physical creator")
    finally:
        reader.raw_sessions = original
        substitute.dispose()


def test_public_run_redaction_preserves_signed_stored_and_in_memory_evidence(host):
    from app.application.agent_orchestrator.approval_grant import (
        issue_approval_grant,
        validate_approval_grant,
    )
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.db.models.agent import AgentRunRecord
    from app.fastapi_routes.domains.agent.route_support import PUBLIC_AGENT_ERROR, public_run_dict

    run = AgentRun(user_id=host.actor.principal.user_id, message="synthetic")
    step = AgentStep(node_id="n", tool_id="products", action="update", status="waiting_user")
    run.steps.append(step)
    token = issue_approval_grant(run, principal_id=run.user_id)["grant"]
    run.metadata = {
        "_tool_approval_grants": {step.step_id: token},
        "ordinary": {"value": 1},
        "nested": [{"error": "private traceback"}],
        "empty_error": "",
    }
    repository = SQLAlchemyAgentRunRepository(session_factory=host.actor.factory, auto_create=False)
    repository.save(run)
    original = deepcopy(run.to_dict())
    loaded = repository.get(run.run_id)
    with host.actor.factory() as db:
        stored = db.get(AgentRunRecord, run.run_id).payload_json
    for candidate in (run, loaded):
        for _ in range(2):
            response = public_run_dict(candidate)
            assert "_tool_approval_grants" not in response["metadata"]
            assert token not in json.dumps(response)
            assert response["metadata"]["ordinary"] == {"value": 1}
            assert response["metadata"]["nested"] == [{"error": PUBLIC_AGENT_ERROR}]
            response["metadata"]["ordinary"]["value"] = 2
            assert candidate.metadata["ordinary"] == {"value": 1}
            assert candidate.metadata["_tool_approval_grants"] == {step.step_id: token}
            validate_approval_grant(token, run=candidate, principal_id=run.user_id)
    assert run.to_dict() == original
    with host.actor.factory() as db:
        assert db.get(AgentRunRecord, run.run_id).payload_json == stored
    repository.save(loaded)
    assert repository.get(run.run_id).metadata["_tool_approval_grants"] == {step.step_id: token}
