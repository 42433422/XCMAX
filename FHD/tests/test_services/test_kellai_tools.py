"""Kellai contracts use live host grants, shared approvals and independent reads."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.application.tools import kellai
from app.domain.shared_services import kellai_binding_store as store
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

PARAMS = {
    "customer_id": 7,
    "channel_type": "chatwoot",
    "contact_id": "conversation-28",
    "content": "已确认的回复",
}


@pytest.fixture
def authorized(trusted_actor, monkeypatch, tmp_path):
    actor = trusted_actor(permissions=[])
    monkeypatch.setattr(store, "_store_path", lambda: tmp_path / "binding.json")

    def pair(scopes=None):
        store.start_pairing(
            actor=actor.user_id,
            tenant_id=str(actor.tenant_id),
            requested_scopes=scopes or [row["id"] for row in store.ALLOWED_SCOPES],
        )
        pending = store.pending_for_kellai()
        store.approve_pairing(
            request_id=pending["request_id"],
            authorization_secret=pending["authorization_secret"],
            accepted_scopes=[row["id"] for row in pending["requested_scopes"]],
            access_token="test-token-" + "x" * 40,
            authorized_by={"id": "provider-owner"},
        )

    pair()
    actor.pair = pair
    return actor


@pytest.fixture
def approved(authorized, monkeypatch):
    from app.application.agent_orchestrator import InMemoryAgentRunRepository
    from app.application.agent_orchestrator.approval_grant import (
        consume_approval_grant,
        issue_approval_grant,
    )
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    step = AgentStep(
        tool_id="kellai",
        action="send",
        params=deepcopy(PARAMS),
        risk="high",
        status="waiting_user",
        node_id="send",
    )
    run = AgentRun(
        user_id=str(authorized.user_id),
        message="发送已确认回复",
        status="waiting_user",
        steps=[step],
        metadata={"runtime_context": deepcopy(authorized.context)},
    )
    run.plan_id = "original-kellai-plan"
    run.metadata["plan"] = plan_to_dict(
        PlanGraph(
            plan_id=run.plan_id,
            intent="发送原消息",
            nodes=[
                WorkflowNode(
                    node_id=step.node_id,
                    tool_id="kellai",
                    action="send",
                    params=deepcopy(PARAMS),
                    risk="high",
                    idempotent=False,
                )
            ],
        )
    )
    grant = issue_approval_grant(run, principal_id=run.user_id)
    claims = consume_approval_grant(grant["grant"], run=run, principal_id=run.user_id)
    run.metadata["approval_receipt"] = {
        **claims,
        "grant_id": claims["jti"],
        "approved_by": run.user_id,
    }
    run.status = "running"
    step.status = "running"
    repository = InMemoryAgentRunRepository()
    repository.save(run)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
        lambda: repository,
    )
    return (
        authorized,
        run,
        step,
        {**authorized.context, "run_id": run.run_id, "step_id": step.step_id},
    )


def test_registry_and_live_binding_are_the_only_available_grant(authorized):
    from app.application.agent_orchestrator.tool_spec import (
        get_tool_action_spec,
        validate_tool_call,
    )
    from app.application.capability_catalog import discover_capabilities

    spec = get_tool_action_spec("kellai", "send")
    assert spec.risk == "high" and not spec.read_only and not spec.idempotent
    assert spec.retry == {"max_attempts": 0} and spec.policy["requires_write_approval"]
    assert validate_tool_call("kellai", "send", PARAMS).ok
    assert not validate_tool_call("kellai", "send", {**PARAMS, "approved": True}).ok
    assert not validate_tool_call("kellai", "receipt", {"client_request_id": "../../other"}).ok
    result = discover_capabilities(authorized.context, query="kellai")
    assert "kellai.send" in {row["capability_id"] for row in result["capabilities"]}
    authorized.pair(list(store.DEFAULT_SCOPES))
    result = discover_capabilities(authorized.context, query="kellai")
    assert {row["capability_id"] for row in result["capabilities"]} == {
        "kellai.customers",
        "kellai.conversations",
        "kellai.data_status",
    }
    store.disconnect()
    assert discover_capabilities(authorized.context, query="kellai")["capabilities"] == []


def test_unbound_or_other_account_never_reaches_provider(authorized, trusted_actor, monkeypatch):
    monkeypatch.setattr(
        kellai, "request_kellai", lambda *_a, **_k: pytest.fail("unauthorized provider read")
    )
    assert kellai.execute_kellai("channels", {}, {})["error_code"] == "tool_identity_required"
    other = trusted_actor(user_id=99, tenant_id=88, permissions=[])
    assert (
        kellai.execute_kellai("channels", {}, other.context)["error_code"]
        == "kellai_scope_required"
    )


def test_send_requires_shared_persisted_approval(authorized, monkeypatch):
    from app.application.agent_orchestrator import InMemoryAgentRunRepository

    monkeypatch.setattr(
        "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
        InMemoryAgentRunRepository,
    )
    monkeypatch.setattr(kellai, "request_kellai", lambda *_a, **_k: pytest.fail("unapproved send"))
    context = {**authorized.context, "run_id": "missing", "step_id": "missing"}
    assert kellai.execute_kellai("send", PARAMS, context)["error_code"] == "approval_required"


@pytest.mark.parametrize("change", ["content", "contact_id", "connection"])
def test_approved_message_and_connection_cannot_change(approved, monkeypatch, change):
    actor, _, _, context = approved
    params = deepcopy(PARAMS)
    if change == "connection":
        actor.pair()
    else:
        params[change] = "different"
    monkeypatch.setattr(
        kellai, "request_kellai", lambda *_a, **_k: pytest.fail("changed approval sent")
    )
    assert kellai.execute_kellai("send", params, context)["error_code"] == "approval_required"


def test_send_requires_original_durable_approval_consumption(approved, monkeypatch):
    from app.db.models.agent_approval import AgentApprovalConsumption

    actor, run, step, context = approved
    original_id = kellai._approved_request_id(PARAMS, context)
    assert original_id == kellai._approved_request_id(PARAMS, context)
    assert original_id == kellai.delivery_request_id(run.run_id, step.step_id)
    with actor.factory.begin() as db:
        consumption = db.get(AgentApprovalConsumption, run.metadata["approval_receipt"]["grant_id"])
        assert consumption is not None
        db.delete(consumption)
    monkeypatch.setattr(kellai, "request_kellai", lambda *_a, **_k: pytest.fail("unconsumed send"))
    assert kellai.execute_kellai("send", PARAMS, context)["error_code"] == "approval_required"


def _provider(context, state, calls, *, message_change=None):
    request_id = kellai.delivery_request_id(context["run_id"], context["step_id"])
    receipt = {
        "request_id": request_id,
        "message_id": "delivery-1",
        "provider_message_id": "provider-1",
        "status": "accepted",
        "provider_state": state,
        "persisted": True,
    }

    def request(path, connection, body=None):
        calls.append((path, body))
        if "/conversations?message_id=delivery-1&limit=1" in path:
            message = {
                "id": "delivery-1",
                **PARAMS,
                "direction": "outbound",
                "metadata": {
                    "delivery_request_id": request_id,
                    "provider_message_id": "provider-1",
                },
                **(message_change or {}),
            }
            return {"success": True, "data": {"customer_id": 7, "messages": [message]}}
        return {"success": True, "data": deepcopy(receipt)}

    return request


def _mock_transport(monkeypatch, request):
    monkeypatch.setattr(kellai, "request_kellai", request)
    monkeypatch.setattr("app.infrastructure.kellai_client.request_kellai", request)


def _observe(run, step, context, output):
    from app.application.agent_orchestrator.result_verification import (
        bind_execution_receipt,
        freeze_verification_contract,
        verify_step_result,
    )
    from app.application.agent_orchestrator.run_models import ToolCall
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    call = ToolCall(
        tool_id=step.tool_id,
        action=step.action,
        params=deepcopy(step.params),
        step_id=step.step_id,
        node_id=step.node_id,
        output=deepcopy(output),
    )
    step.output = deepcopy(output)
    freeze_verification_contract(run, step, call, get_tool_action_spec("kellai", "send"), context)
    bind_execution_receipt(call)
    return verify_step_result(run=run, step=step, call=call, context=context)


@pytest.mark.parametrize("state", ["accepted", "sent", "delivered", "read"])
def test_only_independently_matched_delivery_completes(approved, monkeypatch, state):
    _, run, step, context = approved
    calls = []
    _mock_transport(monkeypatch, _provider(context, state, calls))
    result = kellai.execute_kellai("send", PARAMS, context)
    assert result["success"] is False and result["execution_state"] == "pending"
    assert result["provider_receipt"]["status"] == "accepted"
    assert result["data"]["delivery_receipt"] == result["provider_receipt"]
    assert result["request_id"] == calls[0][1]["client_request_id"]
    assert [path for path, body in calls if body is not None] == ["messages/send"]
    calls.clear()
    evidence = _observe(run, step, context, result)
    assert evidence["accepted"] is (state in {"delivered", "read"})
    if evidence["accepted"]:
        assert evidence["checks"][0]["evidence"]["message_id"] == "delivery-1"
        assert len(calls) == 2
    assert calls and all(body is None for _, body in calls)
    assert result["success"] is False  # Independent evidence never rewrites the original receipt.


@pytest.mark.parametrize(
    "change",
    [{"content": "other"}, {"contact_id": "other"}, {"customer_id": 8}, {"direction": "inbound"}],
)
def test_delivery_claim_without_original_message_is_not_success(approved, monkeypatch, change):
    _, run, step, context = approved
    calls = []
    _mock_transport(monkeypatch, _provider(context, "delivered", calls, message_change=change))
    result = kellai.execute_kellai("send", PARAMS, context)
    assert result["success"] is False and result["execution_state"] == "pending"
    evidence = _observe(run, step, context, result)
    assert evidence["status"] == "failed" and not evidence["accepted"]
    assert result["request_id"] == kellai.delivery_request_id(run.run_id, step.step_id)
    assert result["retryable"] is False
    assert [path for path, body in calls if body is not None] == ["messages/send"]


def test_lost_response_keeps_original_request_and_does_not_retry(approved, monkeypatch):
    _, _, _, context = approved
    calls = []

    def lost(path, connection, body=None):
        calls.append((path, body))
        raise kellai.KellaiRequestError("unavailable")

    monkeypatch.setattr(kellai, "request_kellai", lost)
    result = kellai.execute_kellai("send", PARAMS, context)
    assert result["execution_state"] == "unknown" and result["reconciliation_required"]
    assert result["data"]["delivery_receipt"]["request_id"] == result["request_id"]
    assert result["retryable"] is False and result["request_id"] == calls[0][1]["client_request_id"]
    assert len(calls) == 1


@pytest.mark.parametrize("receipt", [True, "accepted", None])
def test_malformed_provider_receipt_stays_unknown_without_resending(approved, monkeypatch, receipt):
    _, _, _, context = approved
    calls = []

    def send(path, connection, body=None):
        calls.append((path, body))
        return {"success": True, "data": receipt}

    monkeypatch.setattr(kellai, "request_kellai", send)
    result = kellai.execute_kellai("send", PARAMS, context)
    assert result["success"] is False and result["execution_state"] == "unknown"
    assert result["reconciliation_required"] is True and result["retryable"] is False
    assert result["request_id"] == calls[0][1]["client_request_id"]
    assert len(calls) == 1


def test_transport_cannot_follow_redirects_or_arbitrary_paths():
    from app.infrastructure.kellai_client import _NoRedirect, request_kellai

    with pytest.raises(kellai.KellaiRequestError):
        _NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid")
    for path in ("https://other.invalid", "../secret", "messages/requests/../../other"):
        with pytest.raises(kellai.KellaiRequestError):
            request_kellai(path, {"access_token": "must-not-leak"})


@pytest.mark.parametrize("message_id", ["delivery-1", "provider%2Fmessage%3A1"])
def test_transport_allows_exact_original_message_readback(message_id):
    from io import BytesIO

    from app.infrastructure.kellai_client import request_kellai

    path = f"customers/7/conversations?message_id={message_id}&limit=1"
    calls = []

    def open_original(request, **kwargs):
        calls.append(request)
        return BytesIO(b'{"success":true,"data":{"customer_id":7,"messages":[]}}')

    assert request_kellai(path, {"access_token": "private-token"}, opener=open_original)["success"]
    assert len(calls) == 1 and calls[0].method == "GET"
    assert calls[0].full_url.endswith(path)


def test_pending_send_converges_on_original_run_without_resending(approved, monkeypatch):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.result_verification import (
        bind_execution_receipt,
        freeze_verification_contract,
        verify_step_result,
    )
    from app.application.agent_orchestrator.run_models import ToolCall
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.agent_orchestrator.verification_recovery import (
        reverify_run,
        verification_can_finalize,
        verification_report,
    )
    from app.domain.task_lifecycle.results import execution_result_error

    actor, run, step, context = approved
    run.metadata["task_context"] = {
        "task_id": "original-kellai-task",
        "root_run_id": run.run_id,
        "turn_id": "original-kellai-turn",
        "attempt": 1,
    }
    feedback = []
    monkeypatch.setattr(
        "app.application.agent_runtime.pipeline.agent_runtime_hooks_enabled", lambda: True
    )
    monkeypatch.setattr(
        "app.application.agent_runtime.pipeline.remember_run_outcome",
        lambda **kwargs: feedback.append(kwargs) or True,
    )
    repository = get_agent_run_repository()
    step.attempt_count = 1
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id="kellai",
        action="send",
        params=deepcopy(PARAMS),
        metadata={"attempt_count": 1},
    )
    run.tool_calls = [call]
    freeze_verification_contract(run, step, call, get_tool_action_spec("kellai", "send"), context)
    repository.save(run)
    calls = []
    _mock_transport(monkeypatch, _provider(context, "accepted", calls))
    original = kellai.execute_kellai("send", PARAMS, context)
    assert original["success"] is False and original["execution_state"] == "pending"
    step.output, call.output = deepcopy(original), deepcopy(original)
    step.status = call.status = "completed"
    bind_execution_receipt(call)
    first = verify_step_result(run=run, step=step, call=call, context=context)
    assert first["accepted"] is False
    original_digest = call.metadata["verification_output_sha256"]
    run.status = "blocked"
    run.metadata.update(
        non_retryable=True,
        recovery={"state": "result_pending", "step_ids": [step.step_id]},
        execution={"state": "idle"},
    )
    repository.save(run)
    from app.application.agent_orchestrator.task_execution_repository import (
        InMemoryTaskExecutionRepository,
    )

    queue = InMemoryTaskExecutionRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.task_execution_repository.get_task_execution_repository",
        lambda: queue,
    )
    queue.enqueue(run)
    queue.claim("original-worker", lease_seconds=60)
    queue.mark_open_effect(run.run_id, step.step_id)
    from app.application.agent_orchestrator.task_execution_models import dispatched_run_state

    state, code = dispatched_run_state(run)
    queue.finish(run.run_id, "original-worker", state, error_code=code)
    assert queue.get(run.run_id).state == "unknown"

    _mock_transport(monkeypatch, _provider(context, "delivered", calls))
    observed = reverify_run(repository, run.run_id, runtime_context=actor.context)
    assert observed.run_id == run.run_id
    assert verification_report(observed)["accepted"] is True
    assert queue.get(run.run_id).state == "blocked"
    assert queue.get(run.run_id).last_error_code == "result_verified"
    from app.application.agent_orchestrator.run_lifecycle import safe_continuation_error

    assert verification_can_finalize(observed), safe_continuation_error(observed)
    completed = AgentOrchestrator(repository=repository).retry_run(
        run.run_id, requested_by=run.user_id
    )
    assert completed.status == "completed", completed.error
    assert execution_result_error(completed.final_output) == ""
    assert dispatched_run_state(completed) == ("succeeded", "")
    assert completed.steps[0].output == original
    assert completed.tool_calls[0].output == original
    assert completed.tool_calls[0].metadata["verification_output_sha256"] == original_digest
    assert len(completed.tool_calls) == 1 and completed.steps[0].attempt_count == 1
    assert len(feedback) == 1 and feedback[0]["success"] is True
    assert feedback[0]["metadata"]["task_id"] == "original-kellai-task"
    assert feedback[0]["metadata"]["turn_id"] == "original-kellai-turn"
    assert feedback[0]["metadata"]["run_id"] == run.run_id
    assert feedback[0]["metadata"]["verification_status"] == "verified"
    assert "独立业务证据核验完成" in feedback[0]["summary"]
    assert [path for path, body in calls if body is not None] == ["messages/send"]


def test_registered_send_is_approval_required_and_not_auto_retryable():
    from app.application.agent_orchestrator.tool_spec import (
        get_tool_action_spec,
        validate_tool_call,
    )
    from resources.config.risk_actions_loader import requires_write_approval

    spec = get_tool_action_spec("kellai", "send")
    assert spec.risk == "high" and spec.idempotent is False
    assert spec.retry == {"max_attempts": 0}
    assert requires_write_approval("kellai", "send")
    assert validate_tool_call("kellai", "send", PARAMS).ok
    assert not validate_tool_call("kellai", "send", {**PARAMS, "approved": True}).ok
    assert not validate_tool_call("kellai", "send", {**PARAMS, "user_id": "9"}).ok
    assert not validate_tool_call("kellai", "send", {**PARAMS, "content": "x" * 8001}).ok
    assert not validate_tool_call(
        "kellai", "receipt", {"client_request_id": "../../another/request"}
    ).ok


@pytest.mark.parametrize(
    ("status", "provider_state", "success", "message"),
    [
        ("accepted", "sent", True, "渠道已发送，尚无送达确认"),
        ("accepted", "delivered", True, "渠道确认送达"),
        ("accepted", "read", True, "渠道确认已读"),
        ("accepted", "failed", False, "渠道确认发送失败"),
        ("accepted", "unrecognized", True, "渠道已受理，尚无送达确认"),
        ("accepted", ["read"], True, "渠道已受理，尚无送达确认"),
        ("unknown", "delivered", False, "渠道状态：unknown"),
    ],
)
def test_receipt_reports_provider_outcome_without_rewriting_dispatch_state(
    monkeypatch, authorized, status, provider_state, success, message
):
    request_id = "agent_stable_request_123"
    data = {"request_id": request_id, "status": status, "provider_state": provider_state}
    calls = []

    def query(path, connection, body):
        calls.append((path, body))
        return {"success": True, "data": data}

    monkeypatch.setattr(kellai, "request_kellai", query)
    result = kellai.execute_kellai("receipt", {"client_request_id": request_id}, authorized.context)
    assert result["success"] is success
    assert result["message"] == message
    assert result["data"]["delivery_receipt"] == data and result["retryable"] is False
    assert calls == [(f"messages/requests/{request_id}", None)]
    if status == "unknown":
        assert result["outcome"] == "unknown" and result["reconciliation_required"] is True
