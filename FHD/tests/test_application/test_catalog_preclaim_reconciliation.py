"""Explicit preclaim finalization against real HOST/source transactions only."""

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.business_action_ledger import (
    BusinessActionLedger,
    canonical_hash,
)
from app.application.agent_orchestrator.business_write_guard import worker_claim_scope
from app.application.agent_orchestrator.catalog_product_edit import action_context, original
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
from app.application.tool_execution_deadline import invocation_deadline
from app.db.models.agent import AgentTaskExecutionRecord
from app.db.models.agent_business_action import AgentBusinessActionRecord
from app.db.models.workflow import WorkflowPlan
from app.infrastructure.tenant_scope import tenant_scope
from app.mod_sdk import catalog_product_store as store
from tests.test_application.test_catalog_product_edits import (
    authority_images,
    dispatch,
    prepare,
    request,
    revoke_write_grants,
)
from tests.test_application.test_catalog_product_edits import catalog as catalog
from tests.test_application.test_catalog_product_edits import host as host
from tests.test_application.test_catalog_product_edits import trusted_actor as trusted_actor

KIND = "catalog_preclaim_finalization_v1"
BASE = "/api/elt/owned-mixed-v1/products"


def resolve(c, body, *, actor=None, confirmation=None):
    return c.client.post(
        f"{BASE}/edits/{body['operation_id']}/reconciliation",
        headers=(actor or c.actor).headers,
        json={"confirmed": True} if confirmation is None else confirmation,
    )


def observe(c, body):
    return c.client.get(
        f"{BASE}/edits/{body['operation_id']}/verification", headers=c.actor.headers
    )


def submit(c, body):
    return c.client.post(f"{BASE}/{c.pid}/edits", headers=c.actor.headers, json=body)


def business_image(c):
    with sqlite3.connect(c.factory.target) as db:
        return {
            table: db.execute("SELECT * FROM " + table).fetchall()
            for table in ("products", "product_price_history", "etl_price_dimensions")
        }


def physical_witness(c, claim):
    key = store.RECEIPT + canonical_hash(claim["operation_key"])
    with sqlite3.connect(c.factory.target) as db:
        rows = db.execute(
            "SELECT status,runtime_context FROM workflow_plans WHERE plan_id=?", (key,)
        ).fetchall()
    if not rows:
        return None
    assert len(rows) == 1 and rows[0][0] == "rejected"
    envelope = json.loads(rows[0][1])
    assert envelope["proof"] == store.proof(envelope["payload"])
    return envelope


def assert_finalized(c, body, claim, response):
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["verified"] is True
    assert data["receipt_kind"] == KIND
    assert data["outcome"] == "rejected_no_effect"
    assert data["reason_code"] == "preclaim_finalized"
    assert data["fresh_save"] is data["historical_effect_verified"] is False
    assert data["current_matches"] is False
    assert data["operation_id"] == body["operation_id"]
    assert data["run_id"] == claim["run_id"]
    assert data["request_digest"] == claim["request_digest"]
    with c.actor.factory() as db:
        assert db.query(AgentBusinessActionRecord).count() == 0
        operation = db.query(WorkflowPlan).filter_by(plan_id=claim["operation_key"]).one()
        assert operation.status == "finalized_no_effect"
        assert json.loads(operation.plan_json) == claim
        head = db.query(WorkflowPlan).filter_by(plan_id=claim["head"]).one()
        assert (head.status, head.runtime_context) == ("idle", "")
        queue = db.get(AgentTaskExecutionRecord, claim["run_id"])
        assert queue.state == "cancelled"
        assert queue.lease_owner is queue.lease_expires_at is None
    envelope = physical_witness(c, claim)
    payload = envelope["payload"]
    assert payload["receipt_kind"] == KIND
    assert payload["operation_digest"] == claim["operation_digest"]
    assert payload["binding"] == claim["binding"]
    assert payload["owner"] == claim["owner"]
    assert payload["params"] == claim["params"]
    assert "event" not in payload and "effect_claim" not in payload
    # A preclaim witness must not masquerade as the old worker-owned v1 proof.
    assert not {"owner", "execution_count"} <= set(payload.get("no_effect", {}))
    return envelope


@contextmanager
def fail_resolution_commit(c, claim, stage):
    """Interrupt real database commits, not resolver/verifier behavior."""
    reached = []

    def fail(db):
        is_host = db.get_bind().engine is c.host.engine
        is_source = db.info.get("etl_owned_source") == c.factory.binding
        if not is_host and not is_source:
            return
        db.flush()
        if is_host:
            value = (
                db.connection()
                .exec_driver_sql(
                    "SELECT status FROM workflow_plans WHERE plan_id=?", (claim["operation_key"],)
                )
                .scalar()
            )
            matches = value == {
                "fence": "resolving_no_effect",
                "finalization": "finalized_no_effect",
            }.get(stage)
        else:
            matches = (
                stage == "source"
                and db.connection()
                .exec_driver_sql(
                    "SELECT count(*) FROM workflow_plans WHERE plan_id=?",
                    (store.RECEIPT + canonical_hash(claim["operation_key"]),),
                )
                .scalar()
                == 1
            )
        if matches:
            reached.append(True)
            raise OSError("synthetic preclaim " + stage + " commit interruption")

    event.listen(Session, "before_commit", fail)
    try:
        yield reached
    finally:
        event.remove(Session, "before_commit", fail)


def test_explicit_preclaim_resolution_is_physical_no_effect_and_idempotent(catalog):
    c = catalog
    run, body = prepare(c)
    _, claim, _ = original(c.actor.principal, body["operation_id"])
    before = authority_images(c)
    business = business_image(c)
    assert observe(c, body).status_code == 409
    assert authority_images(c) == before
    another = request(c)
    assert submit(c, another).status_code == 409
    assert authority_images(c) == before

    witness = assert_finalized(c, body, claim, resolve(c, body))
    assert business_image(c) == business
    after = authority_images(c)
    assert_finalized(c, body, claim, observe(c, body))
    assert_finalized(c, body, claim, resolve(c, body))
    assert physical_witness(c, claim) == witness
    assert authority_images(c) == after
    repeated = AgentToolExecutor().execute(run.steps[0], runtime_context=action_context(run))
    assert repeated["success"] is False and repeated.get("fresh_save", False) is False
    assert authority_images(c) == after
    # The public task is terminal too, including a late worker's old snapshot.
    for stale_status in ("running", "completed"):
        run.status = run.steps[0].status = stale_status
        c.runs.save(run)
        single = c.client.get(f"/api/agent/runs/{run.run_id}", headers=c.actor.headers)
        assert single.status_code == 200, single.text
        public = single.json()["data"]
        assert public["status"] == "cancelled"
        assert public["metadata"]["non_retryable"] is True
        assert public["steps"][0]["status"] == "skipped"
        assert single.json()["execution"]["state"] == "cancelled"
        listing = c.client.get("/api/agent/runs", headers=c.actor.headers)
        assert listing.status_code == 200, listing.text
        listed = next(item for item in listing.json()["data"] if item["run_id"] == run.run_id)
        assert listed["status"] == "cancelled"
        assert original(c.actor.principal, body["operation_id"])[1] == claim
        assert physical_witness(c, claim) == witness
    # A different operation needs a new review; the old operation never executes.
    assert submit(c, request(c)).status_code == 202
    assert business_image(c) == business


@pytest.mark.parametrize("stop", ["deadline", "cancelled", "lock_timeout"])
def test_actual_source_wait_failure_can_only_be_explicitly_finalized(catalog, stop):
    c = catalog
    run, body = prepare(c)
    _, claim, _ = original(c.actor.principal, body["operation_id"])
    before_source = authority_images(c)[1]
    held, release = threading.Event(), threading.Event()

    def hold_source():
        with tenant_scope(c.actor.tenant_id), c.factory.guard():
            held.set()
            if stop == "lock_timeout":
                assert release.wait(8)
            else:
                time.sleep(0.25)
                if stop == "cancelled":
                    c.queue.transition(run.run_id, "cancelled")

    with ThreadPoolExecutor(max_workers=1) as pool:
        reader = pool.submit(hold_source)
        assert held.wait(3)
        try:
            if stop == "deadline":
                with invocation_deadline(time.monotonic() + 0.05), pytest.raises(TimeoutError):
                    dispatch(c, run)
            elif stop == "cancelled":
                with pytest.raises(WorkerLeaseLost):
                    dispatch(c, run)
            else:
                result, _ = dispatch(c, run)
                assert result["success"] is False and result["reconciliation_required"] is True
        finally:
            release.set()
            reader.result(timeout=3)
    assert authority_images(c)[1] == before_source
    before_get = authority_images(c)
    assert observe(c, body).status_code == 409
    assert authority_images(c) == before_get
    assert_finalized(c, body, claim, resolve(c, body))
    assert authority_images(c)[1]["products"] == before_source["products"]
    assert authority_images(c)[1]["product_price_history"] == before_source["product_price_history"]


@pytest.mark.parametrize("stage", ["fence", "source", "finalization"])
def test_every_resolution_commit_crash_retains_proof_and_head_until_confirmed(catalog, stage):
    c = catalog
    _, body = prepare(c)
    _, claim, _ = original(c.actor.principal, body["operation_id"])
    business = business_image(c)
    with fail_resolution_commit(c, claim, stage) as reached:
        assert resolve(c, body).status_code == 409
    assert reached, stage
    with c.actor.factory() as db:
        operation = db.query(WorkflowPlan).filter_by(plan_id=claim["operation_key"]).one()
        assert operation.status == ("pending" if stage == "fence" else "resolving_no_effect")
        head = db.query(WorkflowPlan).filter_by(plan_id=claim["head"]).one()
        assert (head.status, head.runtime_context) == ("active", claim["operation_key"])
        assert db.query(AgentBusinessActionRecord).count() == 0
    assert (physical_witness(c, claim) is not None) == (stage == "finalization")
    before = authority_images(c)
    response = observe(c, body)
    assert response.status_code == (200 if stage == "finalization" else 409)
    assert authority_images(c) == before
    another = {**body, "operation_id": str(uuid4())}
    assert submit(c, another).status_code == 409
    assert business_image(c) == business
    assert_finalized(c, body, claim, resolve(c, body))
    assert business_image(c) == business


def test_late_worker_and_direct_ledger_call_cannot_pass_resolution_fence(catalog):
    c = catalog
    run, body = prepare(c)
    execution = c.queue.claim("synthetic-worker", lease_seconds=60)
    run.status = run.steps[0].status = "running"
    c.runs.save(run)
    _, claim, _ = original(c.actor.principal, body["operation_id"])
    with fail_resolution_commit(c, claim, "source") as reached:
        assert resolve(c, body).status_code == 409
    assert reached
    before = authority_images(c)
    context = action_context(run)
    with worker_claim_scope(c.runs, execution, "synthetic-worker"):
        try:
            result = AgentToolExecutor().execute(run.steps[0], runtime_context=context)
        except WorkerLeaseLost:
            pass
        else:
            assert result["success"] is False and result.get("fresh_save", False) is False
        with pytest.raises((ValueError, WorkerLeaseLost)):
            BusinessActionLedger(session_factory=c.actor.factory).claim(
                store.TOOL, run.steps[0].action, run.steps[0].params, context
            )
    assert authority_images(c) == before
    assert_finalized(c, body, claim, resolve(c, body))


def test_private_source_admission_cannot_be_replaced_by_caller_fields(catalog):
    c = catalog
    run, _ = prepare(c)
    execution = c.queue.claim("synthetic-worker", lease_seconds=60)
    run.status = run.steps[0].status = "running"
    c.runs.save(run)
    context = {**action_context(run), "_catalog_source_admission": True}
    before = authority_images(c)
    with worker_claim_scope(c.runs, execution, "synthetic-worker"):
        with pytest.raises((ValueError, WorkerLeaseLost)):
            BusinessActionLedger(session_factory=c.actor.factory).claim(
                store.TOOL, run.steps[0].action, run.steps[0].params, context
            )
    assert authority_images(c) == before


def test_concurrent_owner_confirmations_make_one_immutable_witness(catalog):
    c = catalog
    _, body = prepare(c)
    _, claim, _ = original(c.actor.principal, body["operation_id"])
    business = business_image(c)
    start = threading.Barrier(2)

    def confirm():
        start.wait(timeout=3)
        return resolve(c, body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(confirm), pool.submit(confirm)]
        results = [future.result(timeout=12) for future in futures]
    assert 200 in [response.status_code for response in results]
    assert all(response.status_code in {200, 409} for response in results)
    witness = assert_finalized(c, body, claim, resolve(c, body))
    before = authority_images(c)
    assert_finalized(c, body, claim, resolve(c, body))
    assert physical_witness(c, claim) == witness and authority_images(c) == before
    assert business_image(c) == business


def test_host_only_rollback_does_not_readmit_claim_and_can_rejoin_witness(catalog):
    c = catalog
    run, body = prepare(c)
    _, claim, _ = original(c.actor.principal, body["operation_id"])
    with c.actor.factory() as db:
        operation = db.query(WorkflowPlan).filter_by(plan_id=claim["operation_key"]).one()
        original_context = operation.runtime_context
        queue = dict(db.execute(select(AgentTaskExecutionRecord.__table__)).mappings().one())
    witness = assert_finalized(c, body, claim, resolve(c, body))
    source = authority_images(c)[1]
    with c.actor.factory.begin() as db:
        db.query(WorkflowPlan).filter_by(plan_id=claim["operation_key"]).update(
            {"status": "pending", "runtime_context": original_context}
        )
        db.query(WorkflowPlan).filter_by(plan_id=claim["head"]).update(
            {"status": "active", "runtime_context": claim["operation_key"]}
        )
        db.execute(
            update(AgentTaskExecutionRecord)
            .where(AgentTaskExecutionRecord.run_id == run.run_id)
            .values(**queue)
        )
    result, _ = dispatch(c, run)
    assert result["success"] is False and result.get("fresh_save", False) is False
    with c.actor.factory() as db:
        assert db.query(AgentBusinessActionRecord).count() == 0
    assert authority_images(c)[1] == source
    assert_finalized(c, body, claim, resolve(c, body))
    assert physical_witness(c, claim) == witness and authority_images(c)[1] == source


def test_source_only_rollback_cannot_recreate_physical_witness_or_release_again(catalog):
    c = catalog
    _, body = prepare(c)
    _, claim, _ = original(c.actor.principal, body["operation_id"])
    assert_finalized(c, body, claim, resolve(c, body))
    another = request(c)
    with sqlite3.connect(c.factory.target) as db:
        db.execute(
            "DELETE FROM workflow_plans WHERE plan_id=?",
            (store.RECEIPT + canonical_hash(claim["operation_key"]),),
        )
    before = authority_images(c)
    assert observe(c, body).status_code == 409
    assert resolve(c, body).status_code == 409
    assert submit(c, another).status_code == 409
    assert authority_images(c) == before


@pytest.mark.parametrize("existing", ["unknown_claim", "saved_missing_ledger"])
def test_existing_claim_or_effect_is_never_retyped_as_preclaim_absence(catalog, existing):
    c = catalog
    run, body = prepare(c)
    if existing == "unknown_claim":
        reached = []

        def fail_source(db):
            if db.info.get("etl_owned_source") == c.factory.binding:
                reached.append(True)
                raise OSError("synthetic original source effect commit failure")

        event.listen(Session, "before_commit", fail_source)
        try:
            assert dispatch(c, run)[0]["outcome"] == "unknown"
        finally:
            event.remove(Session, "before_commit", fail_source)
        assert reached
    else:
        assert dispatch(c, run)[0]["success"] is True
        with c.actor.factory.begin() as db:
            db.query(AgentBusinessActionRecord).delete()
    before = authority_images(c)
    assert resolve(c, body).status_code == 409
    assert authority_images(c) == before


@pytest.mark.parametrize("revocation", ["permission", "session", "approval"])
def test_preclaim_resolution_rechecks_current_and_original_authority(catalog, revocation):
    c = catalog
    _, body = prepare(c)
    if revocation == "permission":
        revoke_write_grants(c)
    elif revocation == "session":
        from app.db.models.user import Session as UserSession

        with c.actor.factory.begin() as db:
            db.query(UserSession).filter_by(id=c.actor.session_row_id).delete()
    else:
        with c.actor.factory.begin() as db:
            db.connection().exec_driver_sql("DELETE FROM agent_approval_consumptions")
    before = authority_images(c)
    assert resolve(c, body).status_code in ({401, 403} if revocation == "session" else {409})
    assert authority_images(c) == before


@pytest.mark.parametrize("foreign", ["owner", "tenant", "mod"])
def test_only_original_owner_scope_can_finalize_preclaim(catalog, foreign):
    c = catalog
    _, body = prepare(c)
    actor = c.host.create_actor(
        role="admin",
        tenant_id=8 if foreign == "tenant" else 7,
        mod_id="other-mod" if foreign == "mod" else "test-mod",
    )
    before = authority_images(c)
    assert resolve(c, body, actor=actor).status_code == 409
    assert authority_images(c) == before


def test_unapproved_operation_and_nonboolean_confirmation_never_create_witness(catalog):
    c = catalog
    body = request(c)
    assert submit(c, body).status_code == 202
    before = authority_images(c)
    assert resolve(c, body).status_code == 409
    assert authority_images(c) == before
    for confirmation in (
        {},
        {"confirmed": False},
        {"confirmed": 1},
        {"confirmed": True, "retry": True},
    ):
        assert resolve(c, body, confirmation=confirmation).status_code == 409
        assert authority_images(c) == before


def test_preclaim_fence_preserves_failed_evidence_despite_late_attempt_increment(catalog):
    c = catalog
    run, body = prepare(c)
    run.status = run.steps[0].status = "failed"
    run.metadata["non_retryable"] = True
    run.steps[0].attempt_count = 1
    failed = {"success": False, "outcome": "unknown", "reconciliation_required": True}
    run.steps[0].output = dict(failed)
    c.runs.save(run)
    _, claim, _ = original(c.actor.principal, body["operation_id"])
    witness = assert_finalized(c, body, claim, resolve(c, body))
    source = authority_images(c)[1]
    run.status = run.steps[0].status = "completed"
    run.steps[0].attempt_count = 2
    run.steps[0].output = {"success": True}
    c.runs.save(run)
    retained, _, _ = original(c.actor.principal, body["operation_id"])
    assert retained.status == "cancelled" and retained.metadata["non_retryable"] is True
    assert retained.steps[0].status == "failed"
    assert retained.steps[0].attempt_count == 1 and retained.steps[0].output == failed
    assert physical_witness(c, claim) == witness and authority_images(c)[1] == source
