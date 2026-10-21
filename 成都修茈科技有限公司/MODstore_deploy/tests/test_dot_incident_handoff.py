"""Dot preserves trusted role evidence without reopening the raw-prompt boundary."""

import json
from types import SimpleNamespace

import pytest

from modstore_server import dot_ticket_dispatch as dot
from modstore_server import para_delegate_handler as para
from modstore_server.node_coordinator import incident_claim_scope
from tests.test_dot_ticket_dispatch import (
    CUSTOMER_FRAGMENTS,
    SENSITIVE_SUMMARY,
    _Client,
    _env,
    _payload,
    _req,
)
from tests.test_incident_team_escalation import _mutate_event
from tests.test_incident_team_escalation import _payload as event_payload
from tests.test_incident_team_escalation import incident as incident


def runtime(event_id, role, monkeypatch):
    from importlib import import_module

    # Production loads the public facade before its extracted implementation.
    import_module("modstore_server.incident_team_orchestrator")
    from modstore_server.incident_team_dispatch import member_runtime_input

    monkeypatch.setattr(
        "modstore_server.duty_workforce_contracts.duty_event_execution_input", lambda *a, **k: {}
    )
    rows = [
        {
            "role": name,
            "employee_id": "vibe-coding-maintainer",
            "attempt_id": value * 32,
            "ok": False,
            "status": "failed" if name == "fix" else "pending",
            "summary": SENSITIVE_SUMMARY,
            "handler_outputs": {
                "outputs": [
                    {
                        "handler": "para_delegate",
                        "accepted": True,
                        "completed": False,
                        "task_id": f"original-{name}-task",
                        "status": "para_task_accepted",
                        "ok": True,
                    }
                ]
            },
        }
        for name, value in (("scout", "a"), ("fix", "b"))
    ]

    def seed(payload):
        payload.update(summary="Export fails", intent="product_issue", contact_name="张三")
        payload["_team_claim"]["team"] = rows

    _mutate_event(event_id, seed)
    payload = event_payload(event_id)
    data = member_runtime_input(
        employee_id="vibe-coding-maintainer",
        role=role,
        event_id=event_id,
        team_plan={"execution_schema": 2},
        payload=payload,
        event_type="ops.intake.customer_ticket",
        source="customer_ticket",
        route={},
        attempt_id="c" * 32,
        fix_result=rows[1],
    )

    def start(payload):
        current = [r for r in payload["_team_claim"]["team"] if r["role"] != role]
        current.append(
            {
                "role": role,
                "employee_id": "vibe-coding-maintainer",
                "attempt_id": "c" * 32,
                "status": "dispatching",
            }
        )
        payload["_team_claim"]["team"] = current

    _mutate_event(event_id, start)
    data.update(
        tool_name="dolt",
        device_id="dot-dev",
        allow_tool_fallback="0",
        prompt="RAW PROMPT MUST NOT LEAVE " + SENSITIVE_SUMMARY,
    )
    return data


@pytest.mark.parametrize(
    "role,expected", [("scout", []), ("fix", ["scout"]), ("verify", ["scout", "fix"])]
)
def test_role_handoffs_are_persisted_redacted_and_bound_to_current_attempt(
    incident, monkeypatch, role, expected
):
    event_id = incident[0]
    data = runtime(event_id, role, monkeypatch)
    # Nested customer fields cannot replace the server selector or saved rows.
    data["incident"]["_incident_handoff"] = {"handoffs": [{"summary": "INJECTED"}]}
    req = para._build_request(
        task=data["prompt"], input_data=data, employee_id="vibe-coding-maintainer"
    )
    with incident_claim_scope(event_id):
        out = dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")
    prompt = out["prompt"]
    handoffs = json.loads(
        next(
            line.removeprefix("structured_handoffs: ")
            for line in prompt.splitlines()
            if line.startswith("structured_handoffs: ")
        )
    )
    assert [h["role"] for h in handoffs] == expected
    assert all(h["succeeded"] is False for h in handoffs)
    for handoff in handoffs:
        assert (
            handoff["identity"]["attempt_id"] == ("a" if handoff["role"] == "scout" else "b") * 32
        )
        assert handoff["references"] == [{"task_id": f"original-{handoff['role']}-task"}]
    assert "RAW PROMPT MUST NOT LEAVE" not in prompt and "INJECTED" not in prompt
    assert all(value not in prompt for value in CUSTOMER_FRAGMENTS)
    assert out["report_only"] is (role != "fix")
    assert '"codex_controls": "unsupported"' in prompt
    assert '"output_limit_enforced": false' in prompt
    if role == "fix":
        assert "push_preflight.py --fix" in prompt


def test_retry_retains_prior_failed_fix_before_row_replacement(incident, monkeypatch):
    data = runtime(incident[0], "fix", monkeypatch)
    data["is_transient_retry"] = True
    req = para._build_request(
        task=data["prompt"], input_data=data, employee_id="vibe-coding-maintainer"
    )
    with incident_claim_scope(incident[0]):
        prompt = dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")["prompt"]
    assert "original-fix-task" in prompt and '"status": "failed"' in prompt
    assert "b" * 32 in prompt


@pytest.mark.parametrize(
    "mutation", ["missing_selector", "stale_attempt", "wrong_owner", "wrong_revision", "no_claim"]
)
def test_missing_or_forged_runtime_is_blocked(incident, monkeypatch, mutation):
    data = runtime(incident[0], "verify", monkeypatch)
    if mutation == "missing_selector":
        data.pop("_incident_handoff")
    if mutation == "stale_attempt":
        data["_incident_handoff"]["attempt_id"] = data["attempt_id"] = "old-attempt"
    if mutation == "wrong_owner":
        data["user_id"] = data["tenant_id"] = 999
    if mutation == "wrong_revision":
        data["revision"] = "wrong-fix"
    req = para._build_request(
        task="private prompt", input_data=data, employee_id="vibe-coding-maintainer"
    )
    if mutation == "no_claim":
        with pytest.raises(dot.DoltIncidentContractError):
            dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")
    else:
        with incident_claim_scope(incident[0]), pytest.raises(dot.DoltIncidentContractError):
            dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")


def test_blocked_contract_never_posts_and_revokes_created_grant(monkeypatch):
    _env(monkeypatch)
    client = _Client("dolt")
    monkeypatch.setattr(para.httpx, "Client", lambda *a, **k: client)
    monkeypatch.setattr(
        "modstore_server.para_delegate_handler_part04._attach_credential_grant",
        lambda prompt, task: (prompt, SimpleNamespace(task_id=task)),
    )
    revoked = []
    monkeypatch.setattr(
        "modstore_server.cred_vault.revoke_task_grants",
        lambda task, **kw: revoked.append((task, kw)),
    )
    req = _req(_trusted_incident_team_execution=True, wait_for_para=False)
    result = para._post_para_api(req)
    assert result["status"] == "blocked_dolt_incident_contract"
    assert (
        result["accepted"] is False and result["queued"] is False and result["retryable"] is False
    )
    assert client.posted == [] and len(revoked) == 1


def test_legacy_customer_nested_contract_does_not_enable_incident_handoffs():
    req = _req()
    req["raw_input"]["incident"]["_incident_handoff"] = {"summary": "INJECTED"}
    out = dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")
    assert "structured_handoffs:" not in out["prompt"] and "INJECTED" not in out["prompt"]
