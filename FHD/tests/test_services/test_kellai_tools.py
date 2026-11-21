"""Authority and uncertainty regressions for the existing Agent tool boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application.tools import kellai

PARAMS = {
    "customer_id": 7,
    "channel_type": "chatwoot",
    "contact_id": "conversation-28",
    "content": "请查收已确认的回复",
}


@pytest.fixture()
def authorized(monkeypatch, tmp_path):
    from app.domain.shared_services import kellai_binding_store as store

    monkeypatch.setattr(store, "_store_path", lambda: tmp_path / "binding.json")
    store.start_pairing(
        actor=9,
        tenant_id="tenant-a",
        requested_scopes=[scope["id"] for scope in store.ALLOWED_SCOPES],
    )
    pending = store.pending_for_kellai()
    store.approve_pairing(
        request_id=pending["request_id"],
        authorization_secret=pending["authorization_secret"],
        accepted_scopes=[scope["id"] for scope in pending["requested_scopes"]],
        access_token="private-token-" + "x" * 40,
        authorized_by={"id": "kellai-owner"},
    )
    monkeypatch.setattr(kellai, "_bound_actor", lambda _: SimpleNamespace(id=9))
    return {
        "user_id": "9",
        "tenant_id": "tenant-a",
        "run_id": "run-kellai",
        "step_id": "step-kellai",
    }


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


def test_missing_actor_and_other_tenant_cannot_read_customer_data(monkeypatch, authorized):
    def no_actor(_context):
        raise kellai.AgentModAuthorizationError("no sealed actor")

    monkeypatch.setattr(kellai, "_bound_actor", no_actor)
    assert (
        kellai.execute_kellai("channels", {}, authorized)["error_code"] == "tool_identity_required"
    )
    monkeypatch.setattr(kellai, "_bound_actor", lambda _: SimpleNamespace(id=9))
    result = kellai.execute_kellai("customers", {}, {**authorized, "tenant_id": "tenant-b"})
    assert result["error_code"] == "kellai_scope_required"


def test_send_without_persisted_approval_never_calls_transport(monkeypatch, authorized):
    from app.application.agent_orchestrator import run_repository

    monkeypatch.setattr(
        run_repository, "get_agent_run_repository", lambda: SimpleNamespace(get=lambda _id: None)
    )
    monkeypatch.setattr(
        kellai, "request_kellai", lambda *_args: pytest.fail("unapproved external write")
    )
    assert kellai.execute_kellai("send", PARAMS, authorized)["error_code"] == "approval_required"


def test_persisted_approval_binds_exact_recipient_content_and_consumption(monkeypatch, authorized):
    from app import db
    from app.application.agent_orchestrator import run_repository
    from app.application.agent_orchestrator.approval_grant import _params_hash
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep

    step = AgentStep(
        tool_id="kellai",
        action="send",
        node_id="send",
        step_id=authorized["step_id"],
        params=dict(PARAMS),
        risk="high",
    )
    run = AgentRun(
        user_id="9",
        message="发送已确认回复",
        run_id=authorized["run_id"],
        status="running",
        steps=[step],
        metadata={
            "runtime_context": {"tenant_id": "tenant-a"},
            "approval_receipt": {
                "grant_id": "approved-grant",
                "step_id": step.step_id,
                "tool_id": "kellai",
                "action": "send",
                "approved_by": "9",
                "params_sha256": _params_hash(step),
                "kellai_connection_sha256": kellai.binding.connection_identity_sha256(),
            },
        },
    )
    monkeypatch.setattr(
        run_repository, "get_agent_run_repository", lambda: SimpleNamespace(get=lambda _id: run)
    )

    class ApprovedSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _model, key):
            return (
                SimpleNamespace(run_id=run.run_id, step_id=step.step_id)
                if key == "approved-grant"
                else None
            )

    monkeypatch.setattr(db, "HostSessionLocal", ApprovedSession)
    request_id = kellai._approved_request_id(PARAMS, authorized)
    assert request_id == kellai._approved_request_id(PARAMS, authorized)
    assert request_id.startswith("agent_")
    for field, value in [("contact_id", "other-recipient"), ("content", "unapproved-content")]:
        with pytest.raises(PermissionError):
            kellai._approved_request_id({**PARAMS, field: value}, authorized)
    run.metadata["approval_receipt"]["grant_id"] = "not-consumed"
    with pytest.raises(PermissionError):
        kellai._approved_request_id(PARAMS, authorized)
    run.metadata["approval_receipt"]["grant_id"] = "approved-grant"
    from app.domain.shared_services import kellai_binding_store as store

    store.start_pairing(
        actor=9, tenant_id="tenant-a", requested_scopes=[row["id"] for row in store.ALLOWED_SCOPES]
    )
    pending = store.pending_for_kellai()
    store.approve_pairing(
        request_id=pending["request_id"],
        authorization_secret=pending["authorization_secret"],
        accepted_scopes=[row["id"] for row in pending["requested_scopes"]],
        access_token="different-team-token-" + "x" * 40,
        authorized_by={"id": "another-kellai-owner"},
    )
    monkeypatch.setattr(
        kellai, "request_kellai", lambda *_args: pytest.fail("old approval sent to new team")
    )
    assert kellai.execute_kellai("send", PARAMS, authorized)["error_code"] == "approval_required"


def test_accepted_is_not_delivered_and_unknown_keeps_reconciliation_id(monkeypatch, authorized):
    monkeypatch.setattr(kellai, "_approved_request_id", lambda *_args: "agent_stable_request_123")
    calls = []

    def accepted(path, connection, body):
        calls.append((path, body))
        return {
            "success": True,
            "data": {
                "request_id": body["client_request_id"],
                "status": "accepted",
                "persisted": False,
                "provider_message_id": "p-9",
            },
        }

    monkeypatch.setattr(kellai, "request_kellai", accepted)
    result = kellai.execute_kellai("send", PARAMS, authorized)
    assert result["success"] is True
    assert result["data"]["delivery_receipt"]["status"] == "accepted"
    assert result["data"]["delivery_receipt"]["persisted"] is False
    assert result["message"] == "渠道已受理，尚无送达确认"

    def lost_response(*_args):
        raise kellai.KellaiRequestError("result unknown")

    monkeypatch.setattr(kellai, "request_kellai", lost_response)
    unknown = kellai.execute_kellai("send", PARAMS, authorized)
    assert unknown["outcome"] == "unknown" and unknown["retryable"] is False
    assert unknown["data"]["request_id"] == calls[0][1]["client_request_id"]


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
    result = kellai.execute_kellai("receipt", {"client_request_id": request_id}, authorized)
    assert result["success"] is success
    assert result["message"] == message
    assert result["data"]["delivery_receipt"] == data and result["retryable"] is False
    assert calls == [(f"messages/requests/{request_id}", None)]
    if status == "unknown":
        assert result["outcome"] == "unknown" and result["reconciliation_required"] is True
