"""Real SQLite catalog authority survives ordinary saves and lifecycle controls."""

from copy import deepcopy

import pytest

from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.business_action_ledger import BusinessActionLedger
from app.application.agent_orchestrator.catalog_authority_retention import catalog_retention
from app.application.agent_orchestrator.catalog_product_edit import (
    action_context,
    create_edit,
    journal,
    original,
    trusted_original,
    verify_receipt_authority,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.db.models.user import Session as UserSession
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_catalog_product_edits import (
    catalog as catalog,
)
from tests.test_application.test_catalog_product_edits import (
    dispatch,
    prepare,
    request,
)
from tests.test_application.test_owned_mixed_source_substrate import host as host

EVIDENCE = "_tool_approval_grants"


def host_rows(c):
    with c.actor.factory() as db:
        return {
            table: db.connection().exec_driver_sql("SELECT * FROM " + table).all()
            for table in (
                "agent_runs",
                "agent_tasks",
                "agent_task_executions",
                "agent_approval_consumptions",
                "agent_business_actions",
                "workflow_plans",
            )
        }


def unapproved(c):
    body = request(c)
    return create_edit(c.actor.principal, c.pid, body), body


def test_save_omissions_preserve_signed_evidence_and_binding(catalog):
    c = catalog
    run, body = prepare(c)
    expected = deepcopy(run.metadata)
    for key in (EVIDENCE, "catalog_price_binding", "catalog_operation_digest"):
        run.metadata.pop(key)
    c.runs.save(run)
    stored = original(c.actor.principal, body["operation_id"])[0]
    for key in (EVIDENCE, "catalog_price_binding", "catalog_operation_digest"):
        assert stored.metadata[key] == expected[key]
        assert stored.metadata[key] is not expected[key]


def test_stale_preapproval_save_cannot_rewind_consumed_authority(catalog):
    c = catalog
    stale, body = unapproved(c)
    prepare(c, body)
    before = host_rows(c)
    with pytest.raises(ValueError, match="original action missing"):
        c.runs.save(stale)
    assert host_rows(c) == before
    assert original(c.actor.principal, body["operation_id"])[0].metadata[EVIDENCE]


@pytest.mark.parametrize(
    "change",
    [
        "grant",
        "binding",
        "digest",
        "params",
        "step",
        "tool",
        "owner",
        "created",
        "actor",
        "extra-step",
    ],
)
def test_conflicting_catalog_save_is_atomic(catalog, change):
    c = catalog
    run, _ = prepare(c)
    before = host_rows(c)
    if change == "grant":
        run.metadata[EVIDENCE][run.steps[0].step_id] += "changed"
    elif change == "binding":
        run.metadata["catalog_price_binding"]["epoch"] = "changed"
    elif change == "digest":
        run.metadata["catalog_operation_digest"] = "0" * 64
    elif change == "params":
        run.steps[0].params["price"] = "999.00"
    elif change == "step":
        run.steps[0].step_id = "different"
    elif change == "tool":
        run.steps[0].tool_id = "products"
    elif change == "owner":
        run.user_id = "999"
    elif change == "created":
        run.created_at = "changed"
    elif change == "actor":
        run.metadata["runtime_context"]["_actor_authorization"]["role"] = "different"
    else:
        run.steps.append(AgentStep(node_id="extra", tool_id="products", action="list"))
    with pytest.raises(ValueError):
        c.runs.save(run)
    assert host_rows(c) == before


def test_signed_but_unconsumed_grant_cannot_be_saved(catalog):
    c = catalog
    run, _ = unapproved(c)
    before = host_rows(c)
    token = issue_approval_grant(run, principal_id=run.user_id)["grant"]
    run.metadata[EVIDENCE] = {run.steps[0].step_id: token}
    with pytest.raises(ValueError, match="approval/consumption"):
        c.runs.save(run)
    assert host_rows(c) == before


def test_unsigned_generic_catalog_run_cannot_poison_retention(catalog):
    c = catalog
    run = AgentRun(
        user_id=c.actor.principal.user_id,
        message="generic unbound plan",
        status="waiting_user",
        steps=[AgentStep(node_id="unbound", tool_id="catalog_products_v1", action="append_price")],
        metadata={"runtime_context": deepcopy(c.actor.context)},
    )
    before = host_rows(c)
    with pytest.raises(ValueError, match="operation unavailable"):
        c.runs.save(run)
    assert host_rows(c) == before
    ordinary = AgentRun(user_id=run.user_id, message="ordinary", metadata=run.metadata)
    c.runs.save(ordinary)
    assert c.runs.get(ordinary.run_id) is not None
    c.runs.clear()
    assert c.runs.get(ordinary.run_id) is None


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("status", ["paused", "cancelled", "failed", "blocked"])
def test_lifecycle_retention_does_not_release_or_dispatch(catalog, approved, status):
    c = catalog
    run, body = prepare(c) if approved else unapproved(c)
    run.status = status
    c.runs.save(run)
    stored, claim, state = original(c.actor.principal, body["operation_id"])
    assert state == "pending"
    with pytest.raises(ValueError, match="not running"):
        trusted_original(stored.steps[0].params, action_context(stored), writing=True)
    ordinary = AgentRun(
        user_id=run.user_id,
        message="unrelated disposable run",
        metadata={"runtime_context": deepcopy(c.actor.context)},
    )
    c.runs.save(ordinary)
    c.queue.enqueue(ordinary, requested_by=run.user_id)
    c.runs.clear()
    c.queue.clear()
    assert c.runs.get(ordinary.run_id) is None
    assert c.queue.get(ordinary.run_id) is None
    assert c.runs.get(run.run_id) is not None
    assert (c.queue.get(run.run_id) is not None) == approved
    with c.runs.transaction(read_only=True) as db:
        assert catalog_retention(db).run_ids == {run.run_id}
        head = journal(db, claim["head"])
        assert (head.status, head.runtime_context) == ("active", claim["operation_key"])
        assert (
            db.connection().exec_driver_sql("SELECT count(*) FROM agent_business_actions").scalar()
            == 0
        )


def test_same_owner_renewal_and_retired_session_preserve_evidence(catalog):
    c = catalog
    run, body = prepare(c)
    evidence = deepcopy(run.metadata[EVIDENCE])
    renewed = c.host.create_actor(user_id=c.actor.user_id, role="admin", mod_id="test-mod")
    run.metadata["runtime_context"] = deepcopy(renewed.context)
    c.runs.save(run)
    assert original(renewed.principal, body["operation_id"])[0].metadata[EVIDENCE] == evidence
    with c.actor.factory.begin() as db:
        db.delete(db.get(UserSession, c.actor.session_row_id))
        db.delete(db.get(UserSession, renewed.session_row_id))
    run.metadata["ordinary_note"] = "historical evidence remains"
    c.runs.save(run)  # Historical preservation does not require a still-live old session.
    c.runs.clear()
    c.queue.clear()
    assert c.runs.get(run.run_id).metadata[EVIDENCE] == evidence


def test_direct_ledger_claim_without_parent_worker_cannot_poison_operation(catalog):
    c = catalog
    run, _ = prepare(c)
    run.status = run.steps[0].status = "running"
    c.runs.save(run)
    before = host_rows(c)
    with pytest.raises(ValueError, match="worker lease"):
        BusinessActionLedger(c.actor.factory).claim(
            run.steps[0].tool_id, run.steps[0].action, run.steps[0].params, action_context(run)
        )
    assert host_rows(c) == before


@pytest.mark.parametrize("field", ["owner", "action_key", "fingerprint", "execution_count"])
@pytest.mark.parametrize("outcome", ["saved", "rejected_no_effect"])
def test_receipt_requires_original_effect_claim(catalog, field, outcome):
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.mod_sdk.catalog_product_store import RECEIPT, receipt_payload

    c = catalog
    run, body = prepare(c)
    if outcome == "rejected_no_effect":
        with c.factory() as db:
            db.connection().exec_driver_sql("UPDATE products SET name='changed after review'")
            db.commit()
    result, _ = dispatch(c, run)
    assert result["success"] is (outcome == "saved")
    _, claim, _ = original(c.actor.principal, body["operation_id"])
    with c.factory() as db:
        payload = receipt_payload(db, RECEIPT + canonical_hash(claim["operation_key"]))
    verify_receipt_authority(claim, payload)
    proof_field = "effect_claim" if outcome == "saved" else "no_effect"
    payload[proof_field][field] = True if field == "execution_count" else "changed"
    with pytest.raises(ValueError, match="receipt action proof"):
        verify_receipt_authority(claim, payload)
