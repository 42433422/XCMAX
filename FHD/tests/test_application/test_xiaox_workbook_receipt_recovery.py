"""Original workbook receipt recovery and independent numerical evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator.artifact_files import artifact_path, read_verified_run_file
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.infrastructure.tenant_scope import tenant_scope
from app.infrastructure.xiaox.binding import XiaoxBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_workbook_runtime import workbook_runtime as workbook_runtime


@pytest.mark.parametrize(
    "child_status, expected",
    [
        ("running", "running"),
        ("blocked", "unknown"),
    ],
)
def test_writer_receipt_waits_for_independent_qc_without_latching_unknown(
    workbook_runtime, child_status, expected
):
    from app.infrastructure.xiaox.receipts import read_call_receipt

    state = workbook_runtime
    admitted = state.invoke("qc-race", state.params)
    child = state.approve(admitted)
    assert child.status == "completed"
    child = copy.deepcopy(child)
    child.status = child_status
    child.tool_calls[0].metadata["verification"] = {
        "status": "pending",
        "accepted": False,
        "checks": [],
    }
    binding = state.store.get(state.parent.run_id)
    call = binding.metadata["calls"]["qc-race"]
    store = SimpleNamespace(
        repository=SimpleNamespace(get=lambda run_id: child if run_id == child.run_id else None),
        _validate_goal=lambda _run, _metadata: None,
    )

    receipt = read_call_receipt(store, binding, call)

    assert receipt["status"] == expected
    assert receipt["reconciliation_required"] is (expected == "unknown")
    assert receipt["verified"] is False


@pytest.mark.parametrize("replaced_attempt", [False, True])
@pytest.mark.parametrize("interrupted_parent", [False, True])
def test_verified_original_writer_can_reconcile_a_provisional_parent_lock(
    workbook_runtime, replaced_attempt, interrupted_parent
):
    from app.db.models.agent import AgentTaskRecord

    state = workbook_runtime
    child = state.approve(state.invoke("qc-recovery", state.params))
    assert child.status == "completed"
    state.store.close(state.parent.run_id, reason="waiting_user")
    rows = state.store.receipt_snapshot(state.parent.run_id)
    assert len(rows) == 1 and rows[0]["receipt"]["verified"] is True
    prior = copy.deepcopy(rows[0])
    prior.update(state="running")
    prior["receipt"].update(status="running", success=False, verified=False)
    parent = state.repository.get(state.parent.run_id)
    parent.metadata["xiaox_runtime"]["runtime_status"] = "completed"
    parent.metadata.update(
        runtime_completion_mode="auto",
        non_retryable=True,
        recovery={"state": "manual_reconciliation_required"},
    )
    parent.final_output["xiaox_result"] = {
        "exit_status": "running",
        "business_receipts": [prior],
    }
    if interrupted_parent:
        parent.status = "unknown"
        parent.error = "启动清扫误判等待中的父任务"
    state.repository.save(parent)
    if replaced_attempt:
        with state.actor.factory.begin() as db:
            task = db.query(AgentTaskRecord).filter_by(task_id=rows[0]["child_task_id"]).one()
            task.run_count = 2

    current = state.repository.get(parent.run_id)
    reconciled = state.queue.reconcile_xiaox_receipts(state.repository, current)
    if replaced_attempt:
        assert reconciled is None
        assert (
            state.repository.get(parent.run_id).metadata["recovery"]["state"]
            == "manual_reconciliation_required"
        )
    else:
        assert reconciled is not None
        assert reconciled.final_output["xiaox_result"]["exit_status"] == "continuation_pending"
        assert "recovery" not in reconciled.metadata
        assert "non_retryable" not in reconciled.metadata
        assert state.repository.get(child.run_id).status == "completed"


def test_reverify_original_child_releases_scoped_file_without_dispatch(
    workbook_runtime, monkeypatch
):
    from app.application.agent_orchestrator import verification_workbook
    from app.fastapi_routes.domains.agent import agent_routes, artifact_routes

    state = workbook_runtime
    parent = state.repository.get(state.parent.run_id)
    parent.metadata["runtime_context"]["chat_approval_mode"] = "auto"
    state.repository.save(parent)
    params = copy.deepcopy(state.params)
    params["input"]["plan"]["phases"] = [
        {"phase": "insert_rows", "sheet": "Data", "row": 1, "count": 1}
    ]
    real_qc = verification_workbook.verify_workbook

    def reject_first_qc(*args, **kwargs):
        report = real_qc(*args, **kwargs)
        assert report["status"] == "verified"
        report["checks"][-1]["status"] = "failed"
        return {**report, "status": "failed", "code": "result_workbook_qc_unmet"}

    with monkeypatch.context() as old_qc:
        old_qc.setattr(verification_workbook, "verify_workbook", reject_first_qc)
        receipt = state.invoke("write-once", params)
        if receipt.get("pending_approval"):
            state.approve(receipt)
            receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    child = state.repository.get(receipt["run_id"])
    assert child.status == "blocked" and not child.artifacts
    [call] = child.tool_calls
    [original] = call.output["artifacts"]
    original_bytes = read_verified_run_file(child.run_id, original)
    assert receipt["status"] == "unknown"
    assert state.store.get(parent.run_id).run.metadata["non_retryable"] is True
    assert child.metadata["runtime_context"]["parent_run_id"] == parent.run_id
    assert state.queue.get(child.run_id).state == "unknown"
    assert not state.queue.get(child.run_id).lease_owner

    def forbid_retry(*args, **kwargs):
        pytest.fail("rechecking an original file must not dispatch its graph")

    monkeypatch.setattr(AgentOrchestrator, "retry_run", forbid_retry)
    app = FastAPI()
    assert agent_routes.router is artifact_routes.router
    app.include_router(agent_routes.router)
    path = f"/api/agent/runs/{child.run_id}/verify"
    with TestClient(app) as anonymous:
        assert anonymous.post(path).status_code in (401, 403)
        assert anonymous.get(original["uri"]).status_code in (401, 403)
    with TestClient(app, headers=state.actor.headers) as client:
        assert client.get(original["uri"]).status_code == 404
        checked = client.post(path)
        assert checked.status_code == 200, checked.text
        assert checked.json()["verification"]["accepted"] is True
        downloaded = client.get(original["uri"])
    assert downloaded.status_code == 200 and downloaded.content == original_bytes
    assert hashlib.sha256(downloaded.content).hexdigest() == original["metadata"]["sha256"]
    reopened = state.repository.get(child.run_id)
    assert reopened.status == "blocked" and state.queue.get(child.run_id).state == "blocked"
    assert [artifact.artifact_id for artifact in reopened.artifacts] == [original["artifact_id"]]
    assert len(reopened.tool_calls) == 1 and not reopened.llm_calls
    assert reopened.tool_calls[0].output == call.output
    assert state.repository.get(parent.run_id).metadata["non_retryable"] is True


@pytest.mark.parametrize("workbook_runtime", [(1, "original-conversation")], indirect=True)
def test_interrupted_original_turn_shows_verified_file_without_replaying(
    workbook_runtime, monkeypatch
):
    from app.application.agent_runtime.chat import runtime_chat_payload
    from app.application.ai_chat.conversation_history import persist_chat_turn
    from app.application.task_conversation_store import TaskConversationStore
    from app.domain.shared_services.conversation_service import ConversationService
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
    from app.fastapi_routes.domains.agent.artifact_routes import router as artifacts
    from app.infrastructure.xiaox.queued_runtime import stage_queued_request

    state = workbook_runtime
    parent = state.repository.get(state.parent.run_id)
    context = parent.metadata["runtime_context"]
    context["chat_approval_mode"] = "auto"
    state.repository.save(parent)
    params = copy.deepcopy(state.params)
    params["input"]["plan"]["phases"] = [
        {"phase": "set_column_width", "sheet": "Data", "column": "B", "width": 22},
    ]
    receipt = state.invoke("write-original", params)
    if receipt.get("pending_approval"):
        state.approve(receipt)
        receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    assert receipt["verified"] and receipt["status"] == "completed", receipt
    [artifact] = receipt["artifacts"]
    child = state.repository.get(receipt["run_id"])
    original = read_verified_run_file(child.run_id, artifact)

    session, turn = context["session_id"], context["turn_id"]
    request_key = canonical_digest({"turn_id": turn, "owner": parent.user_id})
    worker_turn = "queue_" + canonical_digest([parent.run_id, request_key])
    parent = state.repository.get(parent.run_id)
    parent.metadata["runtime_requests"] = {
        request_key: {"turn_id": turn, "state": "admitted"},
        canonical_digest({"turn_id": worker_turn, "owner": parent.user_id}): {
            "turn_id": worker_turn,
            "state": "admitted",
        },
    }
    queued = stage_queued_request(parent, request_key, {})
    ledger = parent.metadata["xiaox_runtime"]
    parent.metadata["_xiaox_queued_request"]["generation"] = ledger["generation"] - 1
    ledger.update(coordinator_active=False, revoked=True)
    parent.status = "failed"
    parent.metadata.update(non_retryable=True, recovery={"state": "manual_reconciliation_required"})
    state.repository.save(parent)
    state.queue.enqueue(parent, requested_by=parent.user_id)
    assert (claim := state.queue.claim("stopped-worker", lease_seconds=60)).run_id == parent.run_id
    conversations = TaskConversationStore()
    with tenant_scope(state.actor.tenant_id):
        ack = persist_chat_turn(
            "owner",
            "Original question",
            context,
            runtime_chat_payload(
                queued,
                conversation_id=session,
            ),
        )
    assert ack["status"] == "saved"

    def fail_replay(*args, **kwargs):
        pytest.fail("history read must not dispatch or persist a replacement")

    monkeypatch.setattr(AgentOrchestrator, "retry_run", fail_replay)
    monkeypatch.setattr(XiaoxBindingStore, "claim_call", fail_replay)
    monkeypatch.setattr(ConversationService, "settle_queued_reply", fail_replay)

    def assistant(*, user_id=state.actor.user_id, tenant=state.actor.tenant_id, session_id=session):
        with tenant_scope(tenant):
            history = conversations.get_history(
                session_id=session_id, user_id=user_id, turn_id=turn
            )
        return next((row for row in history["messages"] if row["role"] == "assistant"), None)

    stale = assistant()
    assert json.loads(stale["metadata"])["summary"]["status"] == "queued"
    stopped = state.queue.finish(
        parent.run_id,
        "stopped-worker",
        "unknown",
        error_code="needs_verification",
        execution_count=claim.execution_count,
    )
    assert stopped.state == "unknown" and not stopped.lease_owner
    parent_before, child_before = (
        state.repository.get(parent.run_id),
        state.repository.get(child.run_id),
    )
    restored = assistant()
    assert assistant() == restored
    assert restored["id"] == stale["id"] and restored["content"] != stale["content"]
    meta = json.loads(restored["metadata"])
    assert meta["summary"]["status"] == "unknown" and meta["summary"]["success"] is False
    assert meta["ui"]["runtimeContinuation"]["runId"] is None
    assert meta["ui"]["execution"] == {"effect": "unknown", "outcome": "unknown"}
    [file] = meta["ui"]["outputArtifacts"]
    assert (file["run_id"], file["uri"], file["metadata"]["sha256"]) == (
        child.run_id,
        artifact["uri"],
        hashlib.sha256(original).hexdigest(),
    )
    assert state.repository.get(parent.run_id).to_dict() == parent_before.to_dict()
    assert state.repository.get(child.run_id).to_dict() == child_before.to_dict()
    assert state.queue.get(parent.run_id).to_dict() == stopped.to_dict()

    assert assistant(user_id=state.actor.user_id + 1) is None
    assert assistant(session_id="another-conversation") is None
    with tenant_scope(state.actor.tenant_id + 1):
        wrong_tenant = assistant(tenant=state.actor.tenant_id + 1)
    assert (
        wrong_tenant is None or "outputArtifacts" not in json.loads(wrong_tenant["metadata"])["ui"]
    )

    forged = copy.deepcopy(parent_before)
    call = next(iter(forged.metadata["xiaox_runtime"]["calls"].values()))
    call["child_task_id"] += "-forged"
    state.repository.save(forged)
    assert assistant() == stale
    state.repository.save(parent_before)
    assert assistant() == restored

    app = FastAPI()
    app.include_router(artifacts)
    with TestClient(app, headers=state.actor.headers) as client:
        assert client.get(file["uri"]).content == original
        artifact_path(child.run_id, artifact["artifact_id"]).write_bytes(b"damaged original result")
        assert client.get(file["uri"]).status_code == 410
        assert assistant() == stale
    with tenant_scope(state.actor.tenant_id):
        persisted = conversations.get_conversation(session_id=session, user_id=state.actor.user_id)
    original_message = next(row for row in persisted["messages"] if row["role"] == "assistant")
    assert original_message == stale


def test_numerical_contract_failure_keeps_original_write_receipt(workbook_runtime):
    state = workbook_runtime
    params = copy.deepcopy(state.params)
    params["input"]["plan"]["expected"] = {
        "formula_values": [{"sheet": "Data", "ref": "C2", "value": 10}]
    }
    pending = state.invoke("write-numerical", params)
    assert pending["pending_approval"] is True, pending
    child = state.approve(pending)
    [call] = child.tool_calls
    assert call.output["success"] is True and len(call.output["artifacts"]) == 1
    proof = call.metadata["verification"]
    assert (
        proof["accepted"] is False and proof["code"] == "formula_recalculation_engine_unavailable"
    ), proof
    artifact = call.output["artifacts"][0]
    raw = read_verified_run_file(child.run_id, artifact)
    assert hashlib.sha256(raw).hexdigest() == artifact["metadata"]["sha256"]
    assert len(child.tool_calls) == 1


def test_artifact_replaced_during_formula_review_cannot_use_private_copy_proof(
    workbook_runtime, monkeypatch
):
    from app.application.agent_orchestrator import workbook_recalculation as recalc

    state = workbook_runtime
    pending = state.invoke("write-concurrent-change", state.params)
    assert pending["pending_approval"] is True

    def replace_original(path, plan, **kwargs):
        child = state.repository.get(pending["run_id"])
        original = child.tool_calls[0].output["artifacts"][0]
        artifact_path(child.run_id, original["artifact_id"]).write_bytes(b"concurrent replacement")
        return {"status": "verified", "formula_recalculation_verified": True}

    monkeypatch.setattr(recalc, "recalculate_workbook", replace_original)
    child = state.approve(pending)
    assert child.status != "completed" and len(child.tool_calls) == 1
    [call] = child.tool_calls
    assert call.output["success"] is True
    assert call.metadata["verification"]["accepted"] is False
    assert not child.artifacts


def test_real_calc_is_used_by_existing_approved_writer_and_qc(workbook_runtime, monkeypatch):
    from app.application.agent_orchestrator import workbook_recalculation as recalc

    engine = shutil.which("soffice") or shutil.which("libreoffice")
    if not engine or os.name != "posix":
        pytest.skip("real LibreOffice with owned process-group cleanup required")
    state = workbook_runtime
    monkeypatch.setattr(recalc, "_engine_path", lambda: engine)
    version = subprocess.run([engine, "--version"], capture_output=True, text=True, timeout=5)
    assert version.returncode == 0
    monkeypatch.setenv("LIBREOFFICE_EXPECTED_VERSION", version.stdout.strip())
    params = copy.deepcopy(state.params)
    params["input"]["plan"]["expected"] = {
        "formula_values": [{"sheet": "Data", "ref": "C2", "value": 10}]
    }
    pending = state.invoke("write-numerical", params)
    assert pending["pending_approval"] is True, pending
    child = state.approve(pending)
    receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    assert child.status == "completed" and receipt["verified"] is True, json.dumps(
        {
            "error": child.error,
            "verification": [call.metadata.get("verification") for call in child.tool_calls],
        },
        ensure_ascii=False,
    )
    [artifact] = receipt["artifacts"]
    checks = receipt["verification"]["steps"][0]["checks"]
    quality = next(row["evidence"] for row in checks if row["source"] == "workbook_qc")
    numeric = quality["formula_recalculation"]
    assert quality["formula_recalculation_verified"] is True, numeric
    assert numeric["expected_values_verified"] is True and numeric["values"][0]["value"] == 10
    delivered = read_verified_run_file(child.run_id, artifact)
    assert numeric["artifact_sha256"] == hashlib.sha256(delivered).hexdigest()
    assert numeric["output_sha256"] != numeric["artifact_sha256"]
    assert len(child.tool_calls) == 1 and not child.llm_calls
    assert state.workspace_copy.read_bytes() == state.original
