"""Original SQL review identity, evidence fencing and compensation admission.

Synthetic fault injection does not establish real-model or customer acceptance."""

from __future__ import annotations

import asyncio
import copy
import time

import pytest

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import goal_verification_task as checkpoint
from app.application.agent_runtime.verification_budget import JOB_KEY
from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.goal_verification_task import _finish as _finish
from tests.fixtures.goal_verification_task import _review as _review
from tests.fixtures.goal_verification_task import review_task as review_task
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import fixture_goal_review
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


def test_checkpoint_and_settled_progress_survive_a_new_sql_repository(review_task):
    state = review_task
    response = {"id": "settled-original-response", "status": "completed", "output": []}
    progress = {
        "state": "response_received",
        "response": response,
        "response_digest": canonical_digest(response),
    }
    checkpoint.save_verification_progress(
        state.store,
        state.run_id,
        job_id=state.job["job_id"],
        generation=state.generation,
        progress=progress,
    )
    state.store.update(
        state.run_id,
        lambda run, metadata: checkpoint.interrupted_verification(
            run,
            metadata,
            cancelled=False,
        ),
    )
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=state.actor.factory))
    original = state.store.get(state.run_id).run
    recovered = reopened.get(state.run_id).run
    assert recovered.metadata[JOB_KEY]["output"] == state.output
    assert recovered.metadata[JOB_KEY]["progress"] == progress
    assert recovered.metadata[JOB_KEY]["state"] == "pending"
    assert recovered.metadata[JOB_KEY]["attempts"] == 1
    assert checkpoint.resumable_verification(recovered, [], now=time.time() + 30)
    assert recovered.tool_calls == original.tool_calls == []
    assert recovered.metadata["runtime_goal_contract"] == original.metadata["runtime_goal_contract"]


@pytest.mark.parametrize("control", ["cancel", "pause", "revoke_actor", "replace_generation"])
def test_late_review_cannot_override_original_control_or_authority(review_task, control):
    from app.db.models.user import User

    state = review_task
    report = _review(state)
    if control in {"cancel", "pause"}:
        state.repository.request_task_control(
            state.run_id,
            control,
            requested_by=str(state.actor.user_id),
        )
    elif control == "revoke_actor":
        with state.actor.factory.begin() as db:
            db.get(User, state.actor.user_id).is_active = False
    else:
        state.store.update(
            state.run_id,
            lambda _run, metadata: metadata.update(
                generation=metadata["generation"] + 1,
            ),
        )
    before = state.repository.get(state.run_id)
    with pytest.raises(XiaoxBindingError):
        _finish(state, report)
    after = state.repository.get(state.run_id)
    assert after.metadata.get("runtime_goal_verification") is None
    assert after.metadata[JOB_KEY] == before.metadata[JOB_KEY]
    assert after.status == before.status and after.status != "completed"


@pytest.mark.parametrize("review_task", ["conversation"], indirect=True)
def test_conversation_revision_fences_a_late_semantic_verdict(review_task):
    from app.db.models.ai import AIConversationSession

    state = review_task
    report = _review(state)
    with state.actor.factory.begin() as db:
        conversation = (
            db.query(AIConversationSession)
            .filter_by(
                session_id="verification-conversation",
                user_id=state.actor.user_id,
            )
            .one()
        )
        conversation.revision += 1
    with pytest.raises(XiaoxBindingError, match="会话"):
        _finish(state, report)
    parent = state.repository.get(state.run_id)
    assert parent.metadata.get("runtime_goal_verification") is None
    assert parent.status == "running"


@pytest.mark.parametrize(
    "changed", ["answer", "candidate", "verifier_version", "model_usage_unknown", "route_policy"]
)
def test_pending_review_cannot_reuse_stale_or_unsettled_evidence(review_task, monkeypatch, changed):
    state = review_task
    checkpoint.finish_verification(
        state.store,
        state.run_id,
        job_id=state.job["job_id"],
        generation=state.generation,
        review=_review(state, status="unavailable", error_code="goal_verification_timeout"),
    )
    run = state.repository.get(state.run_id)
    if changed == "answer":
        run.add_event("runtime.input_answered", "new answer", {"answer": "另一个定义"})
    elif changed == "candidate":
        run.metadata[JOB_KEY]["output"] = "已改写的成稿"
    elif changed == "verifier_version":
        monkeypatch.setattr(checkpoint, "VERIFIER_VERSION", checkpoint.VERIFIER_VERSION + 1)
    elif changed == "route_policy":
        run.metadata["xiaox_runtime"]["runtime_config"]["authorized_model_routes"] = ["changed"]
    else:
        run.metadata["xiaox_runtime"]["model_requests"] = {"lost": {"state": "unknown"}}
    assert not checkpoint.resumable_verification(run, [], now=time.time() + 30)


@pytest.mark.parametrize("review_task", ["fallback"], indirect=True)
def test_authorized_effective_fallback_preserves_original_review_identity_and_attempts(review_task):
    state = review_task
    _finish(state, _review(state, status="unavailable", error_code="goal_verification_timeout"))
    original = copy.deepcopy(state.repository.get(state.run_id).metadata[JOB_KEY])
    state.store.update(
        state.run_id,
        lambda run, _metadata: run.metadata.update(
            runtime_effective_model_route="qualified-fallback"
        ),
    )
    run = state.repository.get(state.run_id)
    assert checkpoint.resumable_verification(run, [], now=time.time() + 30)
    assert run.metadata[JOB_KEY] == original
    assert run.metadata[JOB_KEY]["attempts"] == 1


@pytest.mark.parametrize("artifact_type", ["file", "office_document"])
def test_recovery_reopens_original_file_bytes_even_when_metadata_is_unchanged(
    review_task,
    monkeypatch,
    tmp_path,
    artifact_type,
):
    from app.application.agent_orchestrator.artifact_files import artifact_path, store_run_file

    state = review_task
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "artifact-data"))
    artifact = store_run_file(
        "original_child",
        b"%PDF-1.4\noriginal\n%%EOF",
        name="original.pdf",
        owner_user_id=state.actor.user_id,
        tenant_id=str(state.actor.tenant_id),
    )
    artifact["artifact_type"] = artifact_type
    operation = {"tool_id": "generate_office_document", "action": "execute", "params": {}}
    rows = [
        {
            **operation,
            "call_id": "original-call",
            "child_run_id": "original_child",
            "child_task_id": "original-task",
            "state": "completed",
            "read_only": False,
            "fingerprint": canonical_digest(operation),
            "receipt": {
                "run_id": "original_child",
                "task_id": "original-task",
                "status": "completed",
                "success": True,
                "verified": True,
                "artifacts": [artifact],
                "verification": {
                    "accepted": True,
                    "steps": [
                        {
                            "checks": [
                                {
                                    "source": "run_artifact",
                                    "status": "passed",
                                    "evidence": {
                                        "run_id": "original_child",
                                        "artifact_id": artifact["artifact_id"],
                                        "sha256": artifact["metadata"]["sha256"],
                                    },
                                }
                            ]
                        }
                    ],
                },
            },
        }
    ]
    checkpoint.verify_artifact_bytes(rows)
    frozen = copy.deepcopy(rows)
    artifact_path("original_child", artifact["artifact_id"]).write_bytes(
        b"%PDF-1.4\nreplaced\n%%EOF"
    )
    with pytest.raises(XiaoxBindingError, match="文件"):
        checkpoint.verify_artifact_bytes(rows)
    assert rows == frozen, "verification must not rewrite the original artifact receipt"


def test_different_late_verdict_cannot_replace_an_already_finished_review(review_task):
    state = review_task
    positive = _review(state)
    _finish(state, positive)
    original = state.repository.get(state.run_id)
    negative = _review(state, status="needs_work", error_code="goal_verification_required")
    with pytest.raises(XiaoxBindingError):
        _finish(state, negative)
    after = state.repository.get(state.run_id)
    assert after.metadata["runtime_goal_verification"] == positive
    assert after.metadata[JOB_KEY] == original.metadata[JOB_KEY]


@pytest.mark.parametrize("gap", ["unmet_goal", "uncovered_source"])
def test_self_consistent_report_digest_cannot_publish_incomplete_goal_as_success(review_task, gap):
    state = review_task
    report = _review(state)
    if gap == "unmet_goal":
        report["review"]["goals"][0]["status"] = "unmet"
    else:
        report["review"]["uncovered_sources"] = ["request"]
    report["report_digest"] = canonical_digest(
        {key: value for key, value in report.items() if key != "report_digest"}
    )
    with pytest.raises(XiaoxBindingError):
        _finish(state, report)
    saved = state.repository.get(state.run_id)
    assert saved.metadata.get("runtime_goal_verification") is None
    assert saved.metadata[JOB_KEY]["state"] == "running"


def test_third_recoverable_timeout_is_explicitly_exhausted_and_cannot_claim_again(review_task):
    state = review_task
    report = _review(state, status="unavailable", error_code="goal_verification_timeout")
    for attempt in range(1, 4):
        if attempt > 1:
            state.job = checkpoint.begin_verification(
                state.store,
                state.run_id,
                generation=state.generation,
                rows=[],
                output=state.output,
            )
        result = _finish(state, report)
        assert result["attempts"] == attempt
        assert result["state"] == ("pending" if attempt < 3 else "blocked")
    saved = state.repository.get(state.run_id)
    assert saved.metadata[JOB_KEY]["error_code"] == "goal_verification_timeout"
    assert saved.metadata[JOB_KEY]["terminal_code"] == "goal_verification_budget_exhausted"
    assert saved.metadata[JOB_KEY]["output"] == state.output
    assert not checkpoint.resumable_verification(saved, [], now=time.time() + 120)
    with pytest.raises(XiaoxBindingError) as exhausted:
        checkpoint.begin_verification(
            state.store,
            state.run_id,
            generation=state.generation,
            rows=[],
            output=state.output,
        )
    assert exhausted.value.code == "goal_verification_budget_exhausted"


@pytest.mark.parametrize("control", ["eligible", "cancelled", "changed_evidence", "unbound_source"])
def test_original_sql_queue_admits_only_current_unmet_goal_compensation_once(
    review_task, runtime_entry, control
):
    state = review_task
    report = _review(state, status="needs_work")
    report["review"]["goals"][0].update(
        status="unmet", evidence_ids=[], reason="The original explanation still lacks an example."
    )
    report["report_digest"] = canonical_digest(
        {key: value for key, value in report.items() if key != "report_digest"}
    )
    _finish(state, report)
    if control == "unbound_source":
        # An old checkpoint can have matching hashes while asking for an action
        # absent from the frozen original goal. Validate meaning before enqueue.
        report["review"]["goals"][0].update(
            source_id="unrequested_purchase",
            source="另行创建采购订单",
        )
        report["report_digest"] = canonical_digest(
            {key: value for key, value in report.items() if key != "report_digest"}
        )

    def park(run, _metadata):
        run.status = "blocked"
        run.metadata[JOB_KEY]["next_attempt_at"] = 0
        run.final_output["xiaox_result"] = {"ok": False, "retryable": True}
        if control == "changed_evidence":
            run.add_event(
                "runtime.input_answered",
                "新增原目标补充说明",
                {
                    "question": "例子所需库存范围",
                    "answer": "只解释现货库存",
                    "input_data": {},
                },
            )
        elif control == "unbound_source":
            run.metadata["runtime_goal_verification"] = copy.deepcopy(report)
            run.metadata[JOB_KEY].update(
                report_digest=report["report_digest"],
                gaps=copy.deepcopy(report["review"]["goals"]),
            )

    state.store.update(state.run_id, park)
    state.store.close(state.run_id, "goal_verification_required", generation=state.generation)
    if control == "cancelled":
        state.repository.request_task_control(
            state.run_id, "cancel", requested_by=str(state.actor.user_id)
        )
    expected = int(control == "eligible")
    assert checkpoint.enqueue_pending_goal_verifications(repository=state.repository) == expected
    assert checkpoint.enqueue_pending_goal_verifications(repository=state.repository) == 0
    saved = state.repository.get(state.run_id)
    compensation = [
        entry
        for entry in saved.metadata.get("runtime_requests", {}).values()
        if entry.get("source") == "independent_goal_compensation"
    ]
    assert len(compensation) == expected
    if expected:
        assert runtime_entry.queue.get(state.run_id).state == "queued"
        assert saved.metadata[JOB_KEY]["gaps"] == report["review"]["goals"]
    assert saved.metadata["runtime_goal_verification"] == report
    assert saved.tool_calls == []
    if control == "unbound_source":
        assert saved.metadata[JOB_KEY]["report_digest"] == report["report_digest"]
        assert saved.metadata[JOB_KEY]["state"] == "needs_work"
        assert runtime_entry.queue.get(state.run_id) is None


@pytest.mark.parametrize(
    "failure", ["read", "write", "write_without_proof", "write_changed_binding"]
)
def test_compensation_uses_original_sql_no_effect_receipt_without_replaying_failed_child(
    dynamic_chat_runtime, local_tools, monkeypatch, failure
):
    from sqlalchemy import select

    from app.application.agent_orchestrator.approval_consumption_repository import (
        SQLAlchemyApprovalConsumptionRepository,
    )
    from app.application.agent_runtime import gateway
    from app.db.models.purchase_unit import PurchaseUnit
    from app.infrastructure.tenant_scope import tenant_scope
    from app.utils.resilience import rate_limiter
    from tests.test_application.test_agent_user_decision_pause import _approve_and_execute

    state = dynamic_chat_runtime
    action = "query" if failure == "read" else "create"
    kind = "read" if failure == "read" else "write"
    eligible = failure in {"read", "write"}
    monkeypatch.setattr(
        "app.application.customer_app_service.get_customers_session", state.actor.factory
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.approval_grant._consumption_repository",
        lambda: SQLAlchemyApprovalConsumptionRepository(state.actor.factory),
    )
    with state.actor.factory.begin() as db:
        PurchaseUnit.__table__.create(db.get_bind(), checkfirst=True)
    endpoint = f"agent-tool:customers.{action}"
    monkeypatch.setitem(
        rate_limiter._rate_limiters, endpoint, rate_limiter._InMemoryRateLimiter(120)
    )
    for _ in range(120):
        assert rate_limiter.check_rate_limit(str(state.actor.tenant_id), endpoint)["allowed"]
    if failure in {"read", "write_without_proof"}:
        monkeypatch.setattr(
            "app.application.agent_orchestrator.tool_executor._pre_dispatch_refusal",
            lambda result: result,
        )
    turns, failed_children = [], []

    def names():
        with tenant_scope(state.actor.tenant_id), state.actor.factory() as db:
            return list(db.scalars(select(PurchaseUnit.unit_name)))

    def script(_binding, _text):
        first = not turns
        turns.append(first)
        name = "rejected-customer" if first else "recovered-customer"
        call_id = "rejected-attempt" if first else "corrected-attempt"
        receipt = state.execute(
            "customers", action, {"keyword" if kind == "read" else "unit_name": name}, call_id
        )
        if receipt.get("pending_approval"):
            _approve_and_execute(
                state.bridge.orchestrator,
                state.repository.get(receipt["run_id"]),
                state.actor,
            )
        if first and failure == "write_changed_binding":
            child = state.repository.get(receipt["run_id"])
            child.tool_calls[0].metadata["verification_output_sha256"] = "0" * 64
            state.repository.save(child)
        receipt = state.bridge.invoke(state.token, "task_evidence", {"call_id": call_id})
        if first:
            assert receipt["status"] == ("failed" if eligible else "unknown"), receipt
            assert names() == []
            failed_children.append(copy.deepcopy(state.repository.get(receipt["run_id"]).to_dict()))
            monkeypatch.setitem(
                rate_limiter._rate_limiters, endpoint, rate_limiter._InMemoryRateLimiter(120)
            )
            return "原操作尚未完成，需要修正后核对。"
        assert receipt["verified"] is True, receipt
        return "原请求已完成并核对原业务回执。"

    state.script = script
    state.review = lambda prompt: fixture_goal_review(
        prompt,
        kind=kind,
        status="unmet" if len(turns) == 1 else "satisfied",
        feedback="仅修正未完成的原操作。",
    )
    result = asyncio.run(
        gateway.run_runtime_task_async(
            task=("查询" if kind == "read" else "创建") + "名为 recovered-customer 的客户",
            system_prompt="根据原请求、真实回执和独立核验继续。",
            runtime_context={**state.actor.context, "turn_id": "safe-failure-compensation"},
            completion_mode="auto",
            settings=state.settings,
        )
    )
    assert len(turns) == (2 if eligible else 1), result
    assert len(state.model_requests) == (2 if eligible else 0), result
    assert result["ok"] is eligible, result
    assert names() == (["recovered-customer"] if failure == "write" else [])
    reopened = SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
    original = failed_children[0]
    assert reopened.get(original["run_id"]).to_dict() == original
    assert len(original["tool_calls"]) == 1
    if eligible:
        parent = reopened.get(result["run_id"])
        assert parent.metadata[JOB_KEY]["state"] == "verified"
        assert len(parent.metadata["xiaox_runtime"]["calls"]) == 2
    else:
        assert result["reconciliation_required"] is True


def test_receipt_committed_between_snapshot_and_cas_invalidates_old_verdict(
    review_task, monkeypatch
):
    state = review_task
    report = _review(state)
    operation = {
        "tool_id": "products",
        "action": "query",
        "params": {"keyword": "a later independently requested observation"},
    }
    late_call = {
        **operation,
        "fingerprint": canonical_digest(operation),
        "read_only": True,
        "state": "running",
        "child_task_id": "later-original-child",
        "child_run_id": "later-original-run",
        "receipt": {
            "run_id": "later-original-run",
            "task_id": "later-original-child",
            "status": "running",
            "success": False,
            "verified": False,
        },
    }
    independent = XiaoxBindingStore(
        SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
    )
    original_update = state.store.update

    def race(run_id, mutation):
        # A different SQL writer publishes evidence after finish read the old
        # snapshot, before its CAS loop reads the current parent version.
        independent.update(
            run_id,
            lambda _run, metadata: metadata["calls"].update(
                {"concurrent-original-call": copy.deepcopy(late_call)}
            ),
        )
        monkeypatch.setattr(state.store, "update", original_update)
        return original_update(run_id, mutation)

    monkeypatch.setattr(state.store, "update", race)
    with pytest.raises(XiaoxBindingError) as changed:
        _finish(state, report)
    assert changed.value.code == "goal_verification_changed"
    saved = state.repository.get(state.run_id)
    assert saved.metadata.get("runtime_goal_verification") is None
    assert saved.metadata[JOB_KEY]["state"] == "running"
    assert saved.metadata["xiaox_runtime"]["calls"]["concurrent-original-call"] == late_call


@pytest.mark.parametrize("takeover", [False, True])
def test_expired_worker_lease_cannot_publish_a_late_semantic_verdict(review_task, takeover):
    from datetime import UTC, datetime, timedelta

    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
    from app.db.models.agent import AgentTaskExecutionRecord
    from app.infrastructure.xiaox.queued_runtime import _ClaimedRuntimeRepository

    state = review_task
    queue = SQLAlchemyTaskExecutionRepository(session_factory=state.actor.factory)
    queue.enqueue(state.repository.get(state.run_id))
    execution = queue.claim("original-verifier", lease_seconds=120)
    assert execution is not None and execution.run_id == state.run_id
    claimed = XiaoxBindingStore(
        _ClaimedRuntimeRepository(state.repository, execution, "original-verifier")
    )
    checkpoint.save_verification_progress(
        claimed,
        state.run_id,
        job_id=state.job["job_id"],
        generation=state.generation,
        progress={"state": "requesting"},
    )
    before = state.repository.get(state.run_id)
    report = _review(state)
    with state.actor.factory.begin() as db:
        db.get(AgentTaskExecutionRecord, state.run_id).lease_expires_at = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    if takeover:
        recovered = queue.claim("replacement-verifier", lease_seconds=120)
        assert recovered is not None
        assert recovered.execution_count == execution.execution_count + 1
    with pytest.raises(WorkerLeaseLost):
        _finish(state, report, store=claimed)
    after = state.repository.get(state.run_id)
    assert after.metadata.get("runtime_goal_verification") is None
    assert after.metadata[JOB_KEY] == before.metadata[JOB_KEY]
