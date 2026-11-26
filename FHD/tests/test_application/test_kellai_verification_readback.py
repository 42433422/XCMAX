"""Customer delivery needs a scoped original receipt and the exact message."""

from __future__ import annotations

import copy
import json

import pytest

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.agent_orchestrator.verification_recovery import reverify_run
from app.application.tools.kellai import delivery_request_id
from app.domain.shared_services import kellai_binding_store as binding
from app.domain.task_lifecycle.results import normalize_execution_result
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_verification_readback import invocation


@pytest.fixture
def delivery(trusted_actor, monkeypatch, tmp_path):
    actor = trusted_actor(role="admin")
    params = {
        "customer_id": 17,
        "contact_id": "conversation-28",
        "channel_type": "chatwoot",
        "content": "已确认的私有客户回复",
    }
    case = invocation(actor, tool="kellai", action="send", params=params)
    monkeypatch.setattr(binding, "_store_path", lambda: tmp_path / "binding.json")
    scopes = ["messages.send", "customer_profiles.read", "customer_conversations.read"]
    binding.start_pairing(
        actor=actor.user_id, tenant_id=str(actor.tenant_id), requested_scopes=scopes
    )
    pending = binding.pending_for_kellai()
    binding.approve_pairing(
        request_id=pending["request_id"],
        authorization_secret=pending["authorization_secret"],
        accepted_scopes=scopes,
        access_token="synthetic-local-token-" + "x" * 40,
        authorized_by={"id": "synthetic-kellai-owner"},
    )
    request_id = delivery_request_id(case.run.run_id, case.step.step_id)
    receipt = {
        "success": True,
        "request_id": request_id,
        "status": "accepted",
        "message_id": "delivery-original",
        "provider_message_id": "provider-original",
        "provider_state": "accepted",
        "persisted": True,
    }
    message = {
        **params,
        "id": receipt["message_id"],
        "direction": "outbound",
        "metadata": {
            "delivery_request_id": request_id,
            "provider_message_id": receipt["provider_message_id"],
        },
    }
    calls = []

    def read(path, connection, body=None):
        assert body is None, "Independent verification must never send a message"
        calls.append(path)
        if path == f"messages/requests/{request_id}":
            return {"success": True, "data": copy.deepcopy(receipt)}
        assert path == "customers/17/conversations?message_id=delivery-original&limit=1"
        return {"success": True, "data": {"customer_id": 17, "messages": [copy.deepcopy(message)]}}

    monkeypatch.setattr("app.infrastructure.kellai_client.request_kellai", read)
    case.step.status = case.call.status = "completed"
    case.run.status = "blocked"
    case.step.output = normalize_execution_result(
        {
            "success": True,
            "data": {"request_id": request_id, "delivery_receipt": copy.deepcopy(receipt)},
            "retryable": False,
        }
    )
    case.call.output = copy.deepcopy(case.step.output)
    freeze_verification_contract(
        case.run, case.step, case.call, get_tool_action_spec("kellai", "send"), case.context
    )
    bind_execution_receipt(case.call)
    return case, receipt, message, calls


def verify(delivery):
    case = delivery[0]
    return verify_step_result(run=case.run, step=case.step, call=case.call, context=case.context)


def test_accepted_waits_for_original_delivery_then_recovers_without_resending(delivery):
    case, receipt, _message, calls = delivery
    assert case.call.output["success"] is True
    assert verify(delivery)["code"] == "result_delivery_confirmation_pending"
    repository = InMemoryAgentRunRepository()
    repository.save(case.run)
    original = copy.deepcopy(case.call.output)
    receipt["provider_state"] = "delivered"
    recovered = reverify_run(repository, case.run.run_id)
    assert recovered.tool_calls[0].output == original
    report = recovered.tool_calls[0].metadata["verification"]
    assert report["accepted"] is True
    assert report["checks"][0]["evidence"]["delivery_verified"] is True
    assert case.step.params["content"] not in json.dumps(report, ensure_ascii=False)
    assert calls == [
        f"messages/requests/{receipt['request_id']}",
        f"messages/requests/{receipt['request_id']}",
        "customers/17/conversations?message_id=delivery-original&limit=1",
    ]


@pytest.mark.parametrize("state", ["accepted", "sent", "unknown", "failed"])
def test_unconfirmed_or_failed_delivery_never_passes(delivery, state):
    delivery[1]["provider_state"] = state
    report = verify(delivery)
    assert report["accepted"] is False
    assert len(delivery[3]) == 1


@pytest.mark.parametrize("field", ["content", "contact_id", "channel_type", "customer_id"])
def test_provider_receipt_cannot_verify_another_message(delivery, field):
    delivery[1]["provider_state"] = "read"
    delivery[2][field] = 99 if field == "customer_id" else "different-original-message"
    assert verify(delivery)["code"] == "result_delivery_message_mismatch"


def test_claimed_request_identity_is_not_used_as_the_read_target(delivery):
    case = delivery[0]
    case.call.output["data"]["delivery_receipt"]["request_id"] = "another-request"
    case.step.output = copy.deepcopy(case.call.output)
    bind_execution_receipt(case.call)
    assert verify(delivery)["code"] == "result_delivery_identity_mismatch"
    assert delivery[3] == []


def test_revocation_blocks_even_delivered_receipt_readback(delivery):
    delivery[1]["provider_state"] = "delivered"
    binding.disconnect()
    assert verify(delivery)["accepted"] is False
    assert delivery[3] == []


@pytest.mark.parametrize("when", ["before_receipt", "between_reads"])
def test_personal_plan_blocks_original_delivery_reads(delivery, monkeypatch, when):
    from app.db import HostSessionLocal
    from app.db.models.user import User
    from app.infrastructure import kellai_client

    case, receipt, _message, calls = delivery
    receipt["provider_state"] = "delivered"

    def downgrade():
        with HostSessionLocal.begin() as db:
            db.get(User, int(case.run.user_id)).account_tier = "personal"

    if when == "before_receipt":
        downgrade()
    else:
        original_read = kellai_client.request_kellai

        def read_then_downgrade(*args, **kwargs):
            result = original_read(*args, **kwargs)
            downgrade()
            return result

        monkeypatch.setattr(kellai_client, "request_kellai", read_then_downgrade)
    assert verify(delivery)["accepted"] is False
    assert len(calls) == (0 if when == "before_receipt" else 1)


def test_missing_original_message_keeps_delivery_unverified(delivery):
    delivery[1]["provider_state"] = "delivered"
    delivery[2]["id"] = "other-message"
    assert verify(delivery)["code"] == "result_delivery_message_unavailable"


@pytest.mark.parametrize("when", ["before_receipt", "between_reads"])
def test_repairing_to_another_team_cannot_rebind_original_evidence(delivery, monkeypatch, when):
    from app.infrastructure import kellai_client

    case, receipt, _message, calls = delivery
    receipt["provider_state"] = "delivered"
    original = copy.deepcopy(case.call.output)
    old = binding.connection_credentials()

    def rebind():
        binding.start_pairing(
            actor=old["xcmax_user_id"],
            tenant_id=old["xcmax_tenant_id"],
            requested_scopes=old["authorized_scopes"],
        )
        pending = binding.pending_for_kellai()
        binding.approve_pairing(
            request_id=pending["request_id"],
            authorization_secret=pending["authorization_secret"],
            accepted_scopes=old["authorized_scopes"],
            access_token="another-team-token-" + "x" * 40,
            authorized_by={"id": "another-team-owner"},
        )

    if when == "before_receipt":
        rebind()
    else:
        original_read = kellai_client.request_kellai

        def read_then_rebind(*args, **kwargs):
            result = original_read(*args, **kwargs)
            rebind()
            return result

        monkeypatch.setattr(kellai_client, "request_kellai", read_then_rebind)
    assert verify(delivery)["code"] == "result_delivery_connection_changed"
    assert case.call.output == original
    assert len(calls) == (0 if when == "before_receipt" else 1)


@pytest.mark.parametrize("deadline_wrapper", [False, True])
def test_lost_ack_can_observe_delivery_without_accepting_or_replaying_unknown(
    delivery, deadline_wrapper
):
    from app.application.agent_orchestrator.verification_recovery import verification_can_finalize

    case, receipt, _message, calls = delivery
    unknown = {
        "success": False,
        "outcome": "unknown",
        "retryable": False,
        "reconciliation_required": True,
        "data": {
            "request_id": receipt["request_id"],
            "delivery_receipt": {"request_id": receipt["request_id"], "status": "unknown"},
        },
    }
    case.step.output = (
        {
            "success": False,
            "outcome": "unknown",
            "error_code": "tool_timeout_unknown",
            "retryable": False,
            "reconciliation_required": True,
            "reconciliation_evidence": unknown,
        }
        if deadline_wrapper
        else unknown
    )
    case.call.output = copy.deepcopy(case.step.output)
    original = copy.deepcopy(case.call.output)
    case.step.status = case.call.status = "failed"
    case.run.status = "failed"
    case.run.metadata["non_retryable"] = True
    bind_execution_receipt(case.call)
    receipt["provider_state"] = "delivered"
    report = verify(delivery)
    assert report["code"] == "original_delivery_observed_execution_unsettled"
    assert report["accepted"] is False and report["status"] == "inconclusive"
    assert report["checks"][0]["evidence"]["delivery_verified"] is True
    assert case.call.output == case.step.output == original
    assert case.run.metadata["non_retryable"] is True
    assert not verification_can_finalize(case.run)
    assert len(calls) == 2 and all("send" not in path for path in calls)
