"""Real host specs/principals and durable claims, never business authorization."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.application.agent_orchestrator.business_action_ledger import (
    BusinessActionLedger,
    LedgerClaimError,
)
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.db.models.agent_business_action import AgentBusinessActionRecord as Record
from app.db.schema_migrations.business_action_ledger import (
    LedgerSchemaError,
    prepare_business_action_schema,
)
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def store(trusted_actor):
    actor = trusted_actor(permissions=["product.edit"])
    actor.context["business_action_id"] = "synthetic-original-action"
    with actor.factory.kw["bind"].begin() as conn:
        prepare_business_action_schema(Operations(MigrationContext.configure(conn)), opt_in=True)
    return actor, BusinessActionLedger()


def claim(ledger, actor, params=None):
    return ledger.claim("products", "create", params or {"name": "synthetic"}, actor.context)


def test_actual_specs_are_projected_without_claiming_reads(store):
    actor, ledger = store
    for tool, action in [("finance", "ledger_query"), ("products", "exists")]:
        spec = get_tool_action_spec(tool, action)
        assert spec.read_only and spec.version == "2" and spec.owner_mod_id == ""
        with pytest.raises(LedgerClaimError):
            ledger.claim(tool, action, {}, actor.context)
    assert not get_tool_action_spec("products", "create").read_only
    for tool, action in [("unknown", "create"), ("employee", "execute"), ("aiopen", "chat")]:
        with pytest.raises(LedgerClaimError):
            ledger.claim(tool, action, {}, actor.context)
    with actor.factory() as db:
        assert db.query(Record).count() == 0


def test_immutable_receipt_unknown_and_duplicates_never_authorize_replay(store):
    actor, ledger = store
    handle, prior = claim(ledger, actor)
    assert handle and prior is None
    assert claim(ledger, actor)[0] is None
    receipt = {"success": True, "data": {"id": 17}}
    for result in [
        ledger.record_receipt(handle, receipt, actor.context),
        ledger.record_receipt(handle, deepcopy(receipt), actor.context),
        ledger.mark_unknown(handle, actor.context),
        claim(ledger, actor)[1],
    ]:
        assert result["success"] is result["retryable"] is result["dispatch_authorized"] is False
        assert result["outcome"] == "unknown" and result["reconciliation_required"]
    with pytest.raises(LedgerClaimError):
        ledger.record_receipt(handle, {"success": True, "data": {"id": 18}}, actor.context)
    with actor.factory() as db:
        saved = db.get(Record, handle.action_key)
        assert (
            saved.state == "unknown"
            and "17" in saved.receipt_json
            and "18" not in saved.receipt_json
        )
    assert not hasattr(ledger, "finish") and not hasattr(ledger, "reconcile")


def test_actual_identity_and_parameter_conflicts_preserve_original(store, trusted_actor):
    actor, ledger = store
    handle, _ = claim(ledger, actor)
    with pytest.raises(LedgerClaimError):
        claim(ledger, actor, {"name": "changed"})
    other = trusted_actor(role="other-real-user", permissions=["product.edit"])
    other.context["business_action_id"] = actor.context["business_action_id"]
    with pytest.raises(LedgerClaimError):
        claim(ledger, other)
    with pytest.raises(LedgerClaimError):
        ledger.mark_unknown(handle, other.context)
    with pytest.raises(LedgerClaimError):
        ledger.mark_unknown(replace(handle, owner="wrong"), actor.context)
    with actor.factory() as db:
        assert db.get(Record, handle.action_key).state == "claimed"


def test_tenant_mod_namespaces_use_actual_session_bindings(store, trusted_actor):
    actor, ledger = store
    handle, _ = claim(ledger, actor)
    for other in [
        trusted_actor(tenant_id=8, role="other-tenant"),
        trusted_actor(user_id=actor.user_id, mod_id="synthetic-mod"),
    ]:
        other.context["business_action_id"] = actor.context["business_action_id"]
        second, _ = claim(ledger, other)
        assert second.action_key != handle.action_key
        with pytest.raises(LedgerClaimError):
            ledger.mark_unknown(handle, other.context)
    with actor.factory() as db:
        assert db.query(Record).count() == 3


@pytest.mark.parametrize("key", ["tenant_id", "user_id", "mod_id", "_runtime_context"])
def test_reserved_identity_overrides_rejected_before_claim(store, key):
    actor, ledger = store
    with pytest.raises(LedgerClaimError):
        claim(ledger, actor, {"payload": {key: "forged"}})
    with actor.factory() as db:
        assert db.query(Record).count() == 0


def test_revoked_after_claim_retains_uncertain_identity(store):
    from app.db.models.user import Session
    from app.utils.time import utc_now_naive

    actor, ledger = store
    handle, _ = claim(ledger, actor)
    with actor.factory.begin() as db:
        db.get(Session, actor.session_row_id).expires_at = utc_now_naive() - timedelta(seconds=1)
    with pytest.raises(AgentModAuthorizationError):
        ledger.record_receipt(handle, {"success": True}, actor.context)
    with pytest.raises(AgentModAuthorizationError):
        claim(ledger, actor)
    with actor.factory() as db:
        record = db.get(Record, handle.action_key)
        assert record.state == "claimed" and record.receipt_json == "{}"


def test_missing_schema_and_lost_claim_never_recreate_or_replay(trusted_actor):
    actor = trusted_actor()
    actor.context["business_action_id"] = "original"
    ledger = BusinessActionLedger()
    with pytest.raises(LedgerSchemaError):
        claim(ledger, actor)
    with actor.factory.kw["bind"].begin() as conn:
        prepare_business_action_schema(Operations(MigrationContext.configure(conn)), opt_in=True)
    handle, _ = claim(ledger, actor)
    with actor.factory.begin() as db:
        db.get(Record, handle.action_key).owner = "other-owner"
    with pytest.raises(LedgerClaimError):
        ledger.record_receipt(handle, {"success": True}, actor.context)
    retry, result = claim(ledger, actor)
    assert retry is None and result["retryable"] is False


def test_forged_actor_and_nested_sequence_override_never_claim(store):
    actor, ledger = store
    forged = deepcopy(actor.context)
    forged["_actor_authorization"]["proof"] = "not-signed"
    with pytest.raises(AgentModAuthorizationError):
        ledger.claim("products", "create", {"name": "synthetic"}, forged)
    for sequence in ([{"tenant_id": 8}], ({"tenant_id": 8},)):
        with pytest.raises(LedgerClaimError):
            claim(ledger, actor, {"payload": sequence})
    with actor.factory() as db:
        assert db.query(Record).count() == 0


def test_unknown_before_receipt_rejects_late_evidence_without_replay(store):
    actor, ledger = store
    handle, _ = claim(ledger, actor)
    ledger.mark_unknown(handle, actor.context)
    with pytest.raises(LedgerClaimError):
        ledger.record_receipt(handle, {"success": True, "id": 17}, actor.context)
    with actor.factory() as db:
        record = db.get(Record, handle.action_key)
        assert record.state == "unknown" and record.receipt_json == "{}"
    result = ledger.record_receipt(handle, {}, actor.context)
    assert result["success"] is result["retryable"] is False
    assert claim(ledger, actor)[0] is None
