"""Read immutable SSOT evidence back and replay classification after source changes."""

from __future__ import annotations

import copy
import json
import time
from datetime import UTC, datetime

import pytest

from app.application.agent_orchestrator.run_diagnostic_evidence import (
    build_reproduction,
    diagnostic_digest,
    replay_reproduction,
)
from app.application.agent_orchestrator.run_diagnostics import diagnose_run, scan_agent_diagnostics
from app.application.agent_orchestrator.run_models import AgentRun, ToolCall
from app.application.agent_orchestrator.task_execution_models import AgentTaskExecution
from tests.test_application.test_agent_run_diagnostics import _persist
from tests.test_application.test_agent_run_diagnostics import ledger as ledger


def _at(seconds):
    return datetime.fromtimestamp(seconds, UTC).isoformat()


@pytest.mark.parametrize(
    "case,layer,kind",
    [
        ("stalled", "runtime", "progress_stalled"),
        ("model_unknown", "model", "model_usage_unknown"),
        ("business_unknown", "tool", "business_outcome_unknown"),
        ("orphan", "collaboration", "child_receipt_missing"),
    ],
)
def test_real_ssot_retains_reproduction_after_original_sql_run_changes(ledger, case, layer, kind):
    from app.db.models.agent import AgentRunRecord

    repository, queue, factory, _, ssot = ledger
    missing_id = "run_" + "c" * 32
    runtime = {"model_reconciliation_required": case == "model_unknown"}
    if case == "orphan":
        runtime["calls"] = {"private call name": {"state": "submitted", "child_run_id": missing_id}}
    run = _persist(repository, factory, xiaox_runtime=runtime)
    if case.endswith("unknown"):
        with factory.begin() as db:
            record = db.get(AgentRunRecord, run.run_id)
            payload = json.loads(record.payload_json)
            payload["final_output"] = {
                "xiaox_result": {"ok": False, "execution_state": "unknown", "error": "private body"}
            }
            record.payload_json = json.dumps(payload)
        run = repository.get(run.run_id)
    before = run.to_dict()
    observed_at = time.time()
    assert (
        scan_agent_diagnostics(
            repository=repository, cursor={}, now=observed_at, stale_after_seconds=120.0
        )
        == 1
    )
    assert repository.get(run.run_id).to_dict() == before
    assert queue.get(run.run_id) is None

    context = ssot.list_work_orders()[0]["history"][0]["context"]
    evidence = context["diagnostic"]
    snapshot = evidence["reproduction"]
    expected = {"layer": layer, "kind": kind, "code": kind}
    if case == "orphan":
        expected["missing_child_refs"] = [missing_id]
    assert replay_reproduction(snapshot) == expected
    assert snapshot["scope"] == "diagnostic_classification"
    assert snapshot["inputs"]["now"] == observed_at
    assert snapshot["inputs"]["stale_after_seconds"] == 120.0
    assert evidence["source_payload_retained"] is evidence["business_replay_allowed"] is False
    assert context["evidence_ref"]["kind"] == "agent_diagnostic_classification_snapshot"
    assert context["evidence_ref"]["snapshot_sha256"] == snapshot["sha256"]
    assert context["evidence_ref"]["sha256"] == diagnostic_digest(evidence)

    run = repository.get(run.run_id)
    run.status = "waiting_user"
    run.message = "new private business input"
    run.final_output = {"ok": False, "pending_input": True, "output": "new private output"}
    repository.save(run)
    assert diagnose_run(repository.get(run.run_id), now=observed_at + 10000) is None
    restored = ssot.list_work_orders()[0]["history"][0]["context"]["diagnostic"]["reproduction"]
    assert restored == snapshot
    assert replay_reproduction(restored) == expected
    encoded = json.dumps(context)
    for private in (
        "private business prompt",
        "private body",
        "private call name",
        "account-private",
    ):
        assert private not in encoded


@pytest.mark.parametrize("wait", ["waiting_user", "waiting_auth", "child", "verification", "input"])
def test_legitimate_wait_replays_as_no_fault_even_after_live_state_changes(wait):
    now = 1_700_000_000.0
    run = AgentRun("u", "private", status="running", updated_at=_at(now - 10000))
    if wait.startswith("waiting_"):
        run.status = wait
    elif wait == "child":
        run.metadata["xiaox_runtime"] = {
            "coordinator_active": "false",
            "calls": {"secret label": {"state": "running"}},
        }
    elif wait == "verification":
        run.tool_calls = [
            ToolCall(
                "s",
                "n",
                "private tool",
                "write",
                status="completed",
                metadata={"verification": {"status": "pending"}},
            )
        ]
        run.metadata["verification_recovery"] = {"lease_until": now + 60}
    else:
        run.metadata["xiaox_runtime"] = {"waiting_input": {"question": "private question"}}
    before = run.to_dict()
    snapshot = build_reproduction(run, now=now)
    assert snapshot["expected"] is None
    assert run.to_dict() == before
    run.status = "failed"
    run.metadata.clear()
    run.tool_calls.clear()
    assert diagnose_run(run, now=now + 100000)["kind"] == "unclassified_failure"
    assert replay_reproduction(snapshot) is None


def test_unknown_external_codes_and_all_non_schema_payloads_are_excluded():
    now = 1_700_000_000.0
    secret = "sk-private-token-do-not-export"
    run = AgentRun(secret, secret, status="blocked", updated_at=_at(now - 10000))
    run.metadata = {
        "runtime_failure_stage": secret,
        "runtime_failure_kind": secret,
        "runtime_failure_reason": secret,
        "runtime_context": {"tenant_id": secret, "_mod_authorization": {"token": secret}},
        "xiaox_runtime": {"session": secret, "params": {"password": secret}},
    }
    run.final_output = {
        "xiaox_result": {
            "ok": False,
            "execution_state": "failed",
            "error_code": secret,
            "error": secret,
            "output": secret,
        }
    }
    run.tool_calls = [
        ToolCall("s", "n", secret, secret, params={"token": secret}, output={"data": secret})
    ]
    snapshot = build_reproduction(run, now=now)
    assert secret not in json.dumps(snapshot)
    assert replay_reproduction(snapshot) == {
        "layer": "unknown",
        "kind": "unclassified_failure",
        "code": "unclassified_failure",
    }


@pytest.mark.parametrize("mode", ["queue", "lease", "deadline", "verification", "model_request"])
def test_recorded_clocks_and_structured_states_replay_the_original_fault(mode):
    now = 1_700_000_000.0
    run = AgentRun("u", "m", status="running", updated_at=_at(now - 10000))
    execution = AgentTaskExecution(
        run.run_id, run.run_id, "u", state="running", heartbeat_at=_at(now - 10)
    )
    expected_kind = "deadline_exceeded"
    if mode == "queue":
        execution.state, execution.available_at = "queued", _at(now - 100)
        expected_kind = "queue_overdue"
    elif mode == "lease":
        execution.lease_expires_at = _at(now - 10)
        expected_kind = "lease_expired"
    elif mode == "deadline":
        run.metadata["xiaox_runtime"] = {"coordinator_active": True, "deadline_at": now - 10}
    elif mode == "verification":
        run.tool_calls = [
            ToolCall(
                "s",
                "n",
                "t",
                "a",
                status="completed",
                metadata={"verification": {"status": "pending"}},
            )
        ]
        run.metadata["verification_recovery"] = {"lease_until": _at(now - 10)}
    else:
        run.metadata["codex_runtime"] = {
            "model_requests": {"private request": {"state": "reserved", "authorization": "secret"}}
        }
        run.final_output = {"execution_state": "unknown"}
        expected_kind = "model_usage_unknown"
    snapshot = build_reproduction(run, execution, now=now, stale_after_seconds=60.0)
    assert replay_reproduction(snapshot)["kind"] == expected_kind
    assert snapshot["inputs"]["execution"]["heartbeat_at"] == now - 10
    assert "private request" not in json.dumps(snapshot)


@pytest.mark.parametrize(
    "mutation",
    ["clock", "version", "scope", "private_field", "nested_private_field", "expected", "nan"],
)
def test_replay_rejects_digest_schema_and_version_tampering(mutation):
    run = AgentRun("u", "m", status="running", updated_at=_at(1_699_999_000))
    snapshot = build_reproduction(run, now=1_700_000_000.0)
    changed = copy.deepcopy(snapshot)
    if mutation == "clock":
        changed["inputs"]["now"] += 1
    elif mutation == "version":
        changed["protocol"] = "xcagi.agent-diagnostic-reproduction.v2"
    elif mutation == "scope":
        changed["scope"] = "business_replay"
    elif mutation == "private_field":
        changed["inputs"]["run"]["message"] = "private prompt"
    elif mutation == "nested_private_field":
        changed["inputs"]["run"]["xiaox"]["authorization"] = {"token": "secret"}
    elif mutation == "expected":
        changed["expected"]["code"] = "permission_denied"
    else:
        changed["inputs"]["stale_after_seconds"] = float("nan")
    if mutation != "clock":
        changed["sha256"] = diagnostic_digest(
            {key: value for key, value in changed.items() if key != "sha256"}
        )
    with pytest.raises(ValueError):
        replay_reproduction(changed)
