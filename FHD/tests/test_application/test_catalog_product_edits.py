"""Real enrolled source, authenticated HTTP, approval queue and immutable receipts.

No model/network calls or mocked business services. Synthetic SQLite only.
"""

import json
import sqlite3
from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
from app.application.agent_orchestrator.catalog_product_edit import (
    action_context,
    create_edit,
    original,
)
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.etl.batch_owned_source import OwnedSqlSessions
from app.db.models.agent_business_action import AgentBusinessActionRecord
from app.db.models.owned_source import EtlPriceDimension, ProductPriceHistory
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.workflow import WorkflowPlan
from app.infrastructure.tenant_scope import tenant_scope
from app.mod_sdk import catalog_product_store as store
from app.mod_sdk.owned_price_catalog import provision_owned_price_catalog
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_owned_mixed_source_substrate import host as host


@pytest.fixture
def catalog(host, monkeypatch):
    # Real fresh session with canonical product.view added to the already-reviewed host fixture.
    actor = host.create_actor(
        role="admin",
        mod_id="test-mod",
        permissions=[
            "etl.execute",
            "product.view",
            "product.edit",
            "dataset.read",
            "dataset.write",
            "etl.template.manage",
        ],
    )
    from app.db.models.permission import Permission, Role

    with actor.factory.begin() as db:
        role = db.query(Role).filter_by(name="admin").one()
        permission = db.query(Permission).filter_by(code="product.view").one_or_none()
        if permission is None:
            permission = Permission(code="product.view", name="View product")
            db.add(permission)
        if permission not in role.permissions:
            role.permissions.append(permission)
    runs = SQLAlchemyAgentRunRepository(session_factory=actor.factory, auto_create=False)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory, auto_create=False)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository._agent_run_repository", runs
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.task_execution_repository._task_execution_repository",
        queue,
    )
    provision_owned_price_catalog(actor.principal, confirmed=True, mixed=True)
    factory = OwnedSqlSessions(actor.principal, mixed=True)
    with tenant_scope(actor.tenant_id), factory() as db:
        db.add(PurchaseUnit(tenant_id=actor.tenant_id, unit_name="synthetic customer"))
        product = Product(
            tenant_id=actor.tenant_id,
            name="Synthetic product",
            model_number="SYN-1",
            unit="synthetic customer",
            price=Decimal("10.00"),
        )
        db.add(product)
        db.flush()
        pid = product.id
        db.add(
            EtlPriceDimension(
                tenant_id=actor.tenant_id,
                product_id=pid,
                currency="CNY",
                price_unit="kg",
                source_digest="a" * 64,
                reviewer_id=actor.user_id,
            )
        )
        db.add(
            ProductPriceHistory(
                tenant_id=actor.tenant_id,
                product_id=pid,
                owner_user_id=actor.user_id,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 2, 1),
                period_label="January",
                price=Decimal("10.00"),
                source_key="b" * 64,
                provenance_json='[{"kind":"synthetic_import"}]',
            )
        )
        db.commit()
    from app.fastapi_routes.domains.agent.agent_routes import router

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield SimpleNamespace(
            actor=actor, host=host, runs=runs, queue=queue, factory=factory, pid=pid, client=client
        )
    factory.engine.dispose()


def request(c, *, actor=None, price="12.00", period=("2026-02-01", "2026-03-01")):
    actor = actor or c.actor
    with tenant_scope(actor.tenant_id):
        view = store.read_products(actor.principal, product_id=c.pid)
    return {
        "operation_id": str(uuid4()),
        "revision": view["revision"],
        "action": "append_price",
        "price": price,
        "period_start": period[0],
        "period_end": period[1],
        "selected_sources": [],
        "reason": "Reviewed synthetic amount",
        "confirmed": True,
    }


def prepare(c, body=None, *, actor=None):
    actor = actor or c.actor
    body = body or request(c, actor=actor)
    response = c.client.post(
        f"/api/etl/owned-mixed-v1/products/{c.pid}/edits", headers=actor.headers, json=body
    )
    if response.status_code != 202:
        create_edit(
            actor.principal, c.pid, body
        )  # Diagnose actual routed failure without stubbing it.
    assert response.status_code == 202, response.text
    run = original(actor.principal, body["operation_id"])[0]
    grant = issue_approval_grant(run, principal_id=actor.principal.user_id)["grant"]
    run = approve_and_enqueue(
        c.runs,
        c.queue,
        run_id=run.run_id,
        token=grant,
        principal_id=actor.principal.user_id,
        runtime_context=actor.context,
        authenticated_binding=actor.principal.mod_authorization,
    )
    return run, body


def dispatch(c, run):
    execution = c.queue.claim("synthetic-worker", lease_seconds=60)
    assert execution and execution.run_id == run.run_id
    run = c.runs.get(run.run_id)
    run.status = "running"
    run.steps[0].status = "running"
    c.runs.save(run)
    with worker_claim_scope(c.runs, execution, "synthetic-worker"):
        result = AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))
    return result, run


def rows(c):
    with c.factory() as db:
        return list(db.connection().execute(select(ProductPriceHistory.__table__)).mappings())


def test_real_http_approval_effect_receipt_and_no_replay(catalog):
    c = catalog
    run, body = prepare(c)
    result, run = dispatch(c, run)
    assert result.get("success") is True, result
    assert len(rows(c)) == 2
    verified = c.client.get(
        f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/verification",
        headers=c.actor.headers,
    )
    assert verified.status_code == 200, verified.text
    again = AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))
    assert again.get("success") is True, again
    assert len(rows(c)) == 2
    response = c.client.get(
        f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}", headers=c.actor.headers
    )
    assert "_tool_approval_grants" not in response.text
    assert c.runs.get(run.run_id).metadata["_tool_approval_grants"]


def authority_images(c):
    with c.actor.factory() as db:
        host = {
            table: [tuple(row) for row in db.connection().exec_driver_sql("SELECT * FROM " + table)]
            for table in (
                "agent_runs",
                "agent_task_executions",
                "agent_approval_consumptions",
                "agent_business_actions",
                "workflow_plans",
            )
        }
    with sqlite3.connect(c.factory.target) as db:
        source = {
            table: db.execute("SELECT * FROM " + table).fetchall()
            for table in ("products", "product_price_history", "workflow_plans")
        }
    return host, source


def revoke_write_grants(c):
    from app.db.models.permission import Role

    with c.actor.factory.begin() as db:
        role = db.query(Role).filter_by(name="admin").one()
        role.permissions = [
            p for p in role.permissions if p.code in {"product.view", "dataset.read"}
        ]


def test_reader_can_observe_saved_original_without_host_or_source_writes(catalog):
    c = catalog
    run, body = prepare(c)
    assert dispatch(c, run)[0]["success"]
    revoke_write_grants(c)
    before = authority_images(c)
    assert (
        c.client.get("/api/etl/owned-mixed-v1/products", headers=c.actor.headers).status_code == 200
    )
    response = c.client.get(
        f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/verification",
        headers=c.actor.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["outcome"] == "saved"
    result = AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))
    assert result["success"] is True
    denied = c.client.post(
        f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/reconciliation",
        headers=c.actor.headers,
        json={"confirmed": True},
    )
    assert denied.status_code == 409
    assert authority_images(c) == before


def interrupt_host_finalization(c):
    """Fail the actual HOST commit after the real source effect has committed."""
    observed = []

    def fail(db):
        if (
            db.get_bind().engine is c.host.engine
            and db.connection()
            .exec_driver_sql(
                "SELECT count(*) FROM agent_business_actions WHERE state IN ('completed', 'rejected')"
            )
            .scalar()
        ):
            observed.append(True)
            raise OSError("synthetic host-finalization interruption")

    event.listen(Session, "before_commit", fail)
    return fail, observed


def committed_but_unknown(c, *, rejected=False):
    run, body = prepare(c)
    if rejected:
        with c.factory() as db:
            db.connection().exec_driver_sql("UPDATE products SET name='changed after review'")
            db.commit()
    fail, observed = interrupt_host_finalization(c)
    try:
        result, run = dispatch(c, run)
    finally:
        event.remove(Session, "before_commit", fail)
    assert observed and result["outcome"] == "unknown", result
    assert len(rows(c)) == (1 if rejected else 2)
    with c.actor.factory() as db:
        assert db.query(AgentBusinessActionRecord).one().state == "unknown"
    return run, body


def test_committed_unknown_is_read_only_until_explicit_owner_reconciliation(catalog):
    c = catalog
    run, body = committed_but_unknown(c)
    before = authority_images(c)
    response = c.client.get(
        f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/verification",
        headers=c.actor.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["outcome"] == "saved"
    assert AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))["success"]
    assert authority_images(c) == before  # No automatic UNKNOWN->completed CAS or re-effect.
    for confirmation in ({}, {"confirmed": False}, {"confirmed": 1}):
        denied = c.client.post(
            f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/reconciliation",
            headers=c.actor.headers,
            json=confirmation,
        )
        assert denied.status_code == 409
        assert authority_images(c) == before
    alternate = {
        **body,
        "operation_id": str(uuid4()),
        "revision": response.json()["data"]["product"]["revision"],
    }
    assert (
        c.client.post(
            f"/api/etl/owned-mixed-v1/products/{c.pid}/edits",
            headers=c.actor.headers,
            json=alternate,
        ).status_code
        == 409
    )
    assert authority_images(c) == before
    reconciled = c.client.post(
        f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/reconciliation",
        headers=c.actor.headers,
        json={"confirmed": True},
    )
    assert reconciled.status_code == 200, reconciled.text
    assert authority_images(c)[1] == before[1]
    with c.actor.factory() as db:
        assert db.query(AgentBusinessActionRecord).one().state == "completed"
    assert (
        c.client.get("/api/etl/owned-mixed-v1/products", headers=c.actor.headers).status_code == 200
    )


@pytest.mark.parametrize("rejected", [False, True])
def test_replaced_ledger_owner_cannot_adopt_original_signed_effect(catalog, rejected):
    c = catalog
    run, body = committed_but_unknown(c, rejected=rejected)
    with c.actor.factory.begin() as db:
        db.query(AgentBusinessActionRecord).one().owner = "replacement-not-original-worker"
    before = authority_images(c)
    for method, suffix, kwargs in (
        (c.client.get, "verification", {}),
        (c.client.post, "reconciliation", {"json": {"confirmed": True}}),
    ):
        response = method(
            f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/{suffix}",
            headers=c.actor.headers,
            **kwargs,
        )
        assert response.status_code == 409, response.text
        assert authority_images(c) == before
    assert (
        AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))["outcome"]
        == "unknown"
    )
    assert authority_images(c) == before
    alternate = {**body, "operation_id": str(uuid4())}
    assert (
        c.client.post(
            f"/api/etl/owned-mixed-v1/products/{c.pid}/edits",
            headers=c.actor.headers,
            json=alternate,
        ).status_code
        == 409
    )
    assert (
        c.client.get("/api/etl/owned-mixed-v1/products", headers=c.actor.headers).status_code == 409
    )
    assert authority_images(c) == before


def test_source_transaction_rollback_keeps_claim_unknown_and_never_replays(catalog):
    c = catalog
    run, body = prepare(c)
    observed = []

    def fail(db):
        if db.info.get("etl_owned_source") == c.factory.binding:
            observed.append(True)
            raise OSError("synthetic source commit failure")

    event.listen(Session, "before_commit", fail)
    try:
        result, run = dispatch(c, run)
    finally:
        event.remove(Session, "before_commit", fail)
    assert observed and result["outcome"] == "unknown"
    assert len(rows(c)) == 1
    before = authority_images(c)
    assert (
        AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))["outcome"]
        == "unknown"
    )
    assert (
        c.client.post(
            f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/reconciliation",
            headers=c.actor.headers,
            json={"confirmed": True},
        ).status_code
        == 409
    )
    assert authority_images(c) == before


@pytest.mark.parametrize(
    "authority", ["receipt", "event", "run", "approval", "operation", "ledger", "epoch"]
)
def test_missing_or_rolled_back_authority_is_unknown_without_new_effect(catalog, authority):
    c = catalog
    run, body = prepare(c)
    assert dispatch(c, run)[0]["success"]
    if authority in {"receipt", "event", "epoch"}:
        with sqlite3.connect(c.factory.target) as db:
            db.execute(
                {
                    "receipt": "DELETE FROM workflow_plans WHERE intent='catalog_products_v1'",
                    "event": "DELETE FROM product_price_history WHERE id>1",
                    "epoch": "UPDATE etl_database_generation SET generation_id='old-generation'",
                }[authority]
            )
    else:
        with c.actor.factory.begin() as db:
            db.connection().exec_driver_sql(
                {
                    "run": "DELETE FROM agent_runs",
                    "approval": "DELETE FROM agent_approval_consumptions",
                    "operation": "DELETE FROM workflow_plans WHERE plan_id LIKE 'catalog-price-operation-v1:%'",
                    "ledger": "DELETE FROM agent_business_actions",
                }[authority]
            )
    before = authority_images(c)
    response = c.client.get(
        f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/verification",
        headers=c.actor.headers,
    )
    assert response.status_code == 409, response.text
    assert (
        AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))["outcome"]
        == "unknown"
    )
    assert authority_images(c) == before


@pytest.mark.parametrize("foreign", ["owner", "tenant", "mod"])
def test_foreign_actor_cannot_read_or_reconcile_original(catalog, foreign):
    c = catalog
    run, body = committed_but_unknown(c)
    actor = c.host.create_actor(
        role="admin",
        tenant_id=8 if foreign == "tenant" else 7,
        mod_id="other-mod" if foreign == "mod" else "test-mod",
    )
    before = authority_images(c)
    assert (
        c.client.get(
            f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/verification",
            headers=actor.headers,
        ).status_code
        == 409
    )
    assert (
        c.client.post(
            f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/reconciliation",
            headers=actor.headers,
            json={"confirmed": True},
        ).status_code
        == 409
    )
    assert authority_images(c) == before


@pytest.mark.parametrize("kind", ["missing", "expired", "replaced"])
def test_missing_or_stale_worker_cannot_even_claim_fresh_action(catalog, kind):
    from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
    from app.db.models.agent import AgentTaskExecutionRecord

    c = catalog
    run, _ = prepare(c)
    execution = c.queue.claim("synthetic-worker", lease_seconds=60)
    run.status = "running"
    run.steps[0].status = "running"
    c.runs.save(run)
    if kind != "missing":
        with c.actor.factory.begin() as db:
            row = db.get(AgentTaskExecutionRecord, run.run_id)
            if kind == "expired":
                row.lease_expires_at = "2000-01-01T00:00:00+00:00"
            else:
                row.execution_count += 1
    before = authority_images(c)
    if kind == "missing":
        assert (
            AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))[
                "outcome"
            ]
            == "unknown"
        )
    else:
        with pytest.raises(WorkerLeaseLost):
            with worker_claim_scope(c.runs, execution, "synthetic-worker"):
                AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))
    assert authority_images(c) == before
    with c.actor.factory() as db:
        assert db.query(AgentBusinessActionRecord).count() == 0


def test_verified_historical_save_and_rejection_are_not_unknown(catalog):
    c = catalog
    first, first_body = prepare(c)
    first_result = dispatch(c, first)[0]
    assert first_result["success"] and first_result["fresh_save"]
    second, _ = prepare(c, request(c, price="14.00", period=("2026-03-01", "2026-04-01")))
    assert dispatch(c, second)[0]["success"]
    before = authority_images(c)
    prior = AgentToolExecutor().execute(first.steps[0], runtime_context=action_context(first))
    assert prior["success"] is False and prior["operation_outcome"] == "saved"
    assert prior["outcome"] == "historical_saved"
    assert prior["historical_effect_verified"] is True and prior["fresh_save"] is False
    assert prior["current_matches"] is False
    response = c.client.get(
        f"/api/etl/owned-mixed-v1/products/edits/{first_body['operation_id']}/verification",
        headers=c.actor.headers,
    )
    data = response.json()["data"]
    # Existing catalog UI understands saved + current_matches=false, not a new enum.
    assert data["outcome"] == "saved" and data["current_matches"] is False
    assert data["historical_effect_verified"] is True and data["fresh_save"] is False
    assert authority_images(c) == before
    assert_historical_consumer(c, first, prior)
    assert authority_images(c)[1] == before[1]  # Immutable source receipt; no replay.

    rejected, _ = prepare(c, request(c, price="16.00", period=("2026-04-01", "2026-05-01")))
    with c.factory() as db, tenant_scope(7):
        db.get(Product, c.pid).description = "changed after review"
        db.commit()
    result, rejected = dispatch(c, rejected)
    assert result["outcome"] == "rejected_no_effect", result
    assert result["business_verification"]["verified"] is True
    before = authority_images(c)
    again = AgentToolExecutor().execute(rejected.steps[0], runtime_context=action_context(rejected))
    assert again["outcome"] == "rejected_no_effect"
    assert authority_images(c) == before


def assert_historical_consumer(c, run, result):
    """Real orchestration/formatter consume an independently read historical result."""
    from app.application.agent_orchestrator.business_harness import ensure_terminal_business_result
    from app.application.agent_orchestrator.run_usage import RunUsageLedger
    from app.application.agent_orchestrator.step_execution import StepExecution

    dependencies = SimpleNamespace(
        action_spec=lambda *_: SimpleNamespace(cost_units=0, permission="", timeout_seconds=2),
        validate=lambda *_: SimpleNamespace(ok=True),
        refresh_budget=lambda _: None,
    )
    execution = StepExecution(
        c.runs,
        SimpleNamespace(execute_with_deadline=lambda *a, **kw: result),
        RunUsageLedger(dependencies),
        dependencies,
        attach_artifacts=lambda *a, **kw: None,
        observe=lambda *a, **kw: {"observation_id": "synthetic-historical-observation"},
    )
    execution.execute_step(run, run.steps[0], runtime_context=action_context(run), node_outputs={})
    persisted = c.runs.get(run.run_id)
    assert persisted.steps[0].status == persisted.tool_calls[-1].status == "failed"
    assert persisted.steps[0].output == result
    assert persisted.metadata["non_retryable"] is True
    assert "recovery" not in persisted.metadata
    assert "tool.completed" not in [e.event_type for e in persisted.events]
    persisted.status = "failed"
    persisted.error = persisted.steps[0].error
    summary = ensure_terminal_business_result(persisted)
    assert summary["success"] is False
    assert "本次未保存" in summary["summary"]
    persisted.status = "completed"
    persisted.final_output["business_result"] = {**summary, "success": True, "status": "completed"}
    assert ensure_terminal_business_result(persisted)["success"] is False
    # Other tools and genuine unresolved outcomes retain the existing warning.
    persisted.status = "failed"
    persisted.final_output.pop("business_result")
    persisted.steps[0].tool_id = "other_tool"
    assert "待核对" in ensure_terminal_business_result(persisted)["summary"]
    persisted.final_output.pop("business_result")
    persisted.steps[0].tool_id = "catalog_products_v1"
    persisted.steps[0].output = {"success": False, "outcome": "unknown", "retryable": False}
    assert "待核对" in ensure_terminal_business_result(persisted)["summary"]


@pytest.mark.parametrize("revocation", ["permission", "session", "approval"])
def test_original_approval_cannot_fresh_write_after_revocation(catalog, revocation):
    from app.db.models.user import Session as UserSession

    c = catalog
    run, _ = prepare(c)
    execution = c.queue.claim("synthetic-worker", lease_seconds=60)
    run.status = run.steps[0].status = "running"
    c.runs.save(run)
    if revocation == "permission":
        revoke_write_grants(c)
    elif revocation == "session":
        with c.actor.factory.begin() as db:
            db.query(UserSession).filter_by(id=c.actor.session_row_id).delete()
    else:
        with c.actor.factory.begin() as db:
            db.connection().exec_driver_sql("DELETE FROM agent_approval_consumptions")
    before = authority_images(c)
    with worker_claim_scope(c.runs, execution, "synthetic-worker"):
        result = AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))
    assert result["outcome"] == "unknown"
    assert authority_images(c) == before
    with sqlite3.connect(f"file:{c.factory.target}?mode=ro", uri=True) as db:
        assert db.execute("SELECT count(*) FROM product_price_history").fetchone()[0] == 1
    with c.actor.factory() as db:
        assert db.query(AgentBusinessActionRecord).count() == 0


@pytest.mark.parametrize("parent_claim", [True, False])
def test_spawn_requires_parent_only_verified_worker_claim(catalog, monkeypatch, parent_claim):
    import time
    from contextlib import nullcontext

    from app.application.agent_orchestrator.tool_process import execute_isolated

    c = catalog
    run, _ = prepare(c)
    execution = c.queue.claim("synthetic-spawn-worker", lease_seconds=90)
    run.status = run.steps[0].status = "running"
    c.runs.save(run)
    # Synthetic server config only: child must re-verify the same physical host.
    monkeypatch.setenv("XCAGI_OWNED_SOURCE_PROFILE", "guarded-host-v1")
    context = action_context(run)
    context.update(
        catalog_claim=[run.run_id, "synthetic-spawn-worker", execution.execution_count],
        catalog_profile="guarded-host-v1",
        purpose="READ",
        worker_claim=True,
    )
    before = authority_images(c)
    with (
        worker_claim_scope(c.runs, execution, "synthetic-spawn-worker")
        if parent_claim
        else nullcontext()
    ):
        result = execute_isolated(AgentToolExecutor(), run.steps[0], context, time.monotonic() + 45)
    if parent_claim:
        assert result.get("success") is True, result
        assert result["fresh_save"] is True
        assert len(rows(c)) == 2
        verified = store.verify_operation(c.actor.principal, run.steps[0].params["operation_id"])
        assert verified["verified"] and verified["current_matches"]
    else:
        assert result.get("success") is not True, result
        assert authority_images(c) == before
        assert len(rows(c)) == 1


def test_registered_catalog_routes_require_auth_and_reject_client_authority(catalog):
    c = catalog
    base = "/api/etl/owned-mixed-v1/products"
    paths = {
        base,
        base + "/{product_id}",
        base + "/{product_id}/edits",
        base + "/edits/{operation_id}",
        base + "/edits/{operation_id}/verification",
        base + "/edits/{operation_id}/reconciliation",
    }
    assert paths <= set(c.client.app.openapi()["paths"])
    before = authority_images(c)
    for method, path in (
        ("get", base),
        ("get", base + f"/{c.pid}"),
        ("post", base + f"/{c.pid}/edits"),
        ("get", base + "/edits/unknown"),
        ("get", base + "/edits/unknown/verification"),
        ("post", base + "/edits/unknown/reconciliation"),
    ):
        response = getattr(c.client, method)(
            path, **({"json": {"confirmed": True}} if method == "post" else {})
        )
        assert response.status_code == 401, response.text
    body = request(c)
    for field in ("purpose", "worker_claim", "_catalog_claim_owner"):
        response = c.client.post(
            base + f"/{c.pid}/edits",
            headers=c.actor.headers,
            json={**body, field: "caller-provided"},
        )
        assert response.status_code == 409, response.text
    assert authority_images(c) == before
