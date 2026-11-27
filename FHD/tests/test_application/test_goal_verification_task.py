"""Original SQL review checkpoints survive outages without a second business action.

The isolated upstream and SDK fixtures are fault-injection tests, not evidence
that a real model or the customer's original workbook has passed acceptance.
"""

from __future__ import annotations

import asyncio
import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import goal_verification_task as checkpoint
from app.application.agent_runtime.verification_budget import JOB_KEY
from app.domain.task_lifecycle.agent_runtime_contract import (
    GOAL_PROTOCOL,
    build_goal_contract,
    canonical_digest,
    goal_answers,
    goal_evidence_snapshot,
)
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import fixture_goal_review
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


@pytest.fixture
def review_task(trusted_actor, request):
    actor = trusted_actor(role="admin")
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    run = AgentRun(str(actor.user_id), "解释库存的含义", status="running", intent="xiaox.runtime")
    run.metadata.update(runtime_type="xiaox", runtime_context=copy.deepcopy(actor.context))
    if getattr(request, "param", "") == "conversation":
        from app.application.task_conversation_store import task_conversation_store

        revision = task_conversation_store.prepare_revision(
            session_id="verification-conversation",
            user_id=actor.user_id,
        )
        run.metadata["runtime_context"].update(
            session_id="verification-conversation",
            conversation_id="verification-conversation",
            local_user_id=actor.user_id,
            _conversation_revision=revision,
        )
    contract = build_goal_contract(run)
    run.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(run)
    store = XiaoxBindingStore(repository)
    grant = store.create(
        run.run_id, runtime_config={"provider_id": "fixture", "route_identity": "fixed"}
    )
    store.update(
        run.run_id,
        lambda _run, metadata: metadata.update(
            active_seconds=0,
            active_started_at=time.time(),
            deadline_at=time.time() + 60,
        ),
    )
    output = "库存表示当前持有的货物数量。"
    job = checkpoint.begin_verification(
        store,
        run.run_id,
        generation=grant.binding.metadata["generation"],
        rows=[],
        output=output,
    )
    return SimpleNamespace(
        actor=actor,
        repository=repository,
        run_id=run.run_id,
        store=store,
        grant=grant,
        generation=grant.binding.metadata["generation"],
        output=output,
        job=job,
    )


def _review(state, *, status="verified", error_code=""):
    run = state.store.get(state.run_id).run
    contract = run.metadata["runtime_goal_contract"]
    snapshot = goal_evidence_snapshot(contract, [], state.output, goal_answers(run))
    body = {
        "protocol": GOAL_PROTOCOL,
        "verifier_version": checkpoint.VERIFIER_VERSION,
        "goal_digest": contract["digest"],
        "evidence_digest": snapshot["digest"],
        "response_digest": canonical_digest(state.output),
        "status": status,
        "accepted": status == "verified",
        "mode": "reply",
        "error_code": error_code,
        "attempts": [],
        "feedback": "Synthetic semantic verdict; host checks the original identities.",
        "review": {
            "goals": [
                {
                    "goal_id": "original",
                    "source_id": "request",
                    "source": run.message,
                    "kind": "reply",
                    "status": "satisfied",
                    "evidence_ids": ["response"],
                    "reason": "The candidate explains the original term.",
                }
            ],
            "violations": [],
            "uncovered_sources": [],
            "feedback": "",
        }
        if status in {"verified", "needs_work"}
        else None,
    }
    return {**body, "report_digest": canonical_digest(body)}


def _finish(state, report=None, *, store=None):
    return checkpoint.finish_verification(
        store or state.store,
        state.run_id,
        job_id=state.job["job_id"],
        generation=state.generation,
        review=report or _review(state),
    )


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
    "changed", ["answer", "candidate", "verifier_version", "model_usage_unknown"]
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
    else:
        run.metadata["xiaox_runtime"]["model_requests"] = {"lost": {"state": "unknown"}}
    assert not checkpoint.resumable_verification(run, [], now=time.time() + 30)


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


@pytest.fixture
def pending_business_review(dynamic_chat_runtime, local_tools, monkeypatch, request):
    """Commit one real customer, then fail only the independent model review."""
    from sqlalchemy import select

    from app.application.agent_orchestrator.approval_consumption_repository import (
        SQLAlchemyApprovalConsumptionRepository,
    )
    from app.application.agent_runtime import gateway, goal_verifier, xiaox_runtime
    from app.db.models.purchase_unit import PurchaseUnit
    from app.domain.shared_services import tools_workflow_dispatch
    from app.infrastructure.tenant_scope import tenant_scope
    from tests.test_application.test_agent_user_decision_pause import _approve_and_execute

    state = dynamic_chat_runtime
    state.dispatches = []
    name = "verification-only-customer"
    fault = getattr(request, "param", "settled_timeout")
    after_commit = "_after_" in fault
    reply_only = fault.endswith("_after_reply")
    if "process_loss" in fault:
        finish = xiaox_runtime.finish_verification

        def capture_before_finalize(store, run_id, **kwargs):
            from app.db.models.agent import AgentTaskExecutionRecord
            from app.domain.task_lifecycle.control import SessionBook

            if after_commit:
                if fault.endswith("_after_blocked"):
                    store.update(
                        run_id, lambda run, _metadata: run.metadata[JOB_KEY].update(attempts=3)
                    )
                finish(store, run_id, **kwargs)
            state.crash_run = copy.deepcopy(store.get(run_id).run)
            with state.actor.factory() as db:
                queued = db.get(AgentTaskExecutionRecord, run_id)
                state.crash_control = copy.deepcopy(
                    SessionBook(db).get("agent", str(state.actor.tenant_id), run_id)
                )
                state.crash_queue = (
                    {
                        column.name: getattr(queued, column.name)
                        for column in queued.__table__.columns
                    }
                    if queued is not None
                    else None
                )
            if after_commit:
                raise XiaoxBindingError(
                    "injected_process_loss_after_verification", "fault injection"
                )
            return finish(store, run_id, **kwargs)

        monkeypatch.setattr(xiaox_runtime, "finish_verification", capture_before_finalize)
    monkeypatch.setattr(
        "app.application.customer_app_service.get_customers_session",
        state.actor.factory,
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.approval_grant._consumption_repository",
        lambda: SQLAlchemyApprovalConsumptionRepository(state.actor.factory),
    )
    original_dispatch = tools_workflow_dispatch.execute_registered_workflow_tool

    def dispatch(tool, action, params):
        state.dispatches.append((tool, action, copy.deepcopy(params)))
        return original_dispatch(tool, action, params)

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        dispatch,
    )

    def names():
        with tenant_scope(state.actor.tenant_id), state.actor.factory() as db:
            return list(
                db.scalars(
                    select(PurchaseUnit.unit_name).where(
                        PurchaseUnit.tenant_id == state.actor.tenant_id,
                    )
                )
            )

    def script(_binding, _text):
        if reply_only:
            return "库存表示当前持有的货物数量。"
        receipt = state.execute("customers", "create", {"unit_name": name}, "original-write")
        if receipt.get("pending_approval"):
            _approve_and_execute(
                state.bridge.orchestrator,
                state.repository.get(receipt["run_id"]),
                state.actor,
            )
        receipt = state.bridge.invoke(state.token, "task_evidence", {"call_id": "original-write"})
        child = state.repository.get(receipt["run_id"])
        assert receipt["verified"] is True, child.metadata.get("verification")
        assert names() == [name]
        return "原客户已创建并由原业务读回确认。"

    state.script = script
    clock = SimpleNamespace(offset=0.0)
    actual_time = goal_verifier.time
    monkeypatch.setattr(
        goal_verifier,
        "time",
        SimpleNamespace(
            time=time.time,
            monotonic=lambda: time.monotonic() + clock.offset,
        ),
    )

    def review(prompt):
        if fault in {"unknown_transport", "queued_process_loss_unknown"}:
            import httpx

            raise httpx.ReadTimeout("injected response loss after request admission")
        value = fixture_goal_review(prompt, kind="reply" if reply_only else "write")
        if fault.endswith("_after_needs_work"):
            value["goals"].append(
                {
                    "goal_id": "missing-explanation",
                    "source_id": "request",
                    "source": prompt["original_request"]["text"],
                    "kind": "reply",
                    "status": "unmet",
                    "evidence_ids": [],
                    "reason": "The original business purpose still needs explaining.",
                }
            )
        # Metering completes in the real gateway, but the local verifier sees
        # its own deadline elapse before accepting the response. No wall sleep.
        if not after_commit or fault.endswith(("_after_pending", "_after_blocked")):
            clock.offset = 1000.0
        return value

    state.review = review
    if fault.startswith("queued_"):
        accepted = state.client.post(
            "/api/agent/runs",
            json={
                "message": "解释库存的含义" if reply_only else f"创建客户 {name} 并解释其业务用途",
                "request_id": "original-before-process-loss",
            },
        )
        assert accepted.status_code == 202, accepted.text
        result = state.drain(accepted.json()["data"]["run_id"]).final_output["xiaox_result"]
    else:
        result = asyncio.run(
            gateway.run_runtime_task_async(
                task=f"创建客户 {name}",
                system_prompt="按原授权执行，并独立核对真实回执。",
                runtime_context={**state.actor.context, "turn_id": "wg06-original-turn"},
                completion_mode="auto",
                settings=state.settings,
            )
        )
    monkeypatch.setattr(goal_verifier, "time", actual_time)
    if "process_loss" in fault:
        monkeypatch.setattr(xiaox_runtime, "finish_verification", finish)
    state.review = lambda _prompt: pytest.fail("a settled original review must not be billed again")
    state.parent_id = result["run_id"]
    state.first_result = result
    state.original_parent = state.repository.get(state.parent_id)
    state.names = names
    state.original_rows = XiaoxBindingStore(state.repository).receipt_snapshot(state.parent_id)
    assert names() == ([] if reply_only else [name])
    assert len(state.dispatches) == len(state.original_rows) == (0 if reply_only else 1)
    if not reply_only:
        assert state.original_rows[0]["receipt"]["verified"] is True, state.original_rows[0]
    if not fault.endswith(("_after_verified", "_after_reply")):
        assert not result["business_completed"] and not result["ok"], result
    return state


def _make_due(state):
    XiaoxBindingStore(state.repository).update(
        state.parent_id,
        lambda run, _metadata: run.metadata[JOB_KEY].update(next_attempt_at=0),
    )


def _forbid_execution(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("verification recovery must not create/resume an SDK thread or dispatch tools")

    monkeypatch.setattr("app.infrastructure.xiaox.XiaoxTransport", forbidden)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.AgentToolExecutor.execute",
        forbidden,
    )


@pytest.mark.parametrize(
    "pending_business_review", ["settled_timeout", "queued_timeout"], indirect=True
)
def test_settled_timeout_recovers_only_verification_and_original_business_receipt(
    pending_business_review,
    monkeypatch,
):
    state = pending_business_review
    _forbid_execution(monkeypatch)
    _make_due(state)
    reopened = SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
    assert checkpoint.enqueue_pending_goal_verifications(repository=reopened) == 1
    saved = state.drain(state.parent_id)
    result = saved.final_output["xiaox_result"]
    assert result["ok"] and result["business_completed"], result
    assert saved.metadata[JOB_KEY]["state"] == "verified"
    assert saved.metadata[JOB_KEY]["attempts"] == 2
    assert len(state.transports) == 1 and len(state.dispatches) == 1
    assert len(state.model_requests) == 1, "parsing a settled response must not repeat billing"
    assert state.names() == ["verification-only-customer"]
    current_rows = XiaoxBindingStore(reopened).receipt_snapshot(state.parent_id)
    assert current_rows == state.original_rows
    assert (
        saved.metadata["runtime_goal_contract"]
        == state.original_parent.metadata["runtime_goal_contract"]
    )
    assert state.queue.get(state.parent_id).state == "succeeded"


def test_concurrent_recovery_scanners_publish_one_original_queue_request(
    pending_business_review,
    monkeypatch,
):
    from app.infrastructure.xiaox import queued_runtime

    state = pending_business_review
    _forbid_execution(monkeypatch)
    _make_due(state)
    barrier = threading.Barrier(2)
    enqueue = queued_runtime.enqueue_resume

    def simultaneous(*args, **kwargs):
        barrier.wait(timeout=10)
        return enqueue(*args, **kwargs)

    with monkeypatch.context() as racing:
        racing.setattr(queued_runtime, "enqueue_resume", simultaneous)

        def scan():
            return checkpoint.enqueue_pending_goal_verifications(
                repository=SQLAlchemyAgentRunRepository(session_factory=state.actor.factory),
            )

        with ThreadPoolExecutor(max_workers=2) as workers:
            pending = [workers.submit(scan) for _ in range(2)]
            outcomes = [future.result(timeout=15) for future in pending]
    assert sorted(outcomes) == [0, 1]
    run = state.repository.get(state.parent_id)
    assert (
        sum(
            entry.get("source") == "independent_goal_verification"
            for entry in run.metadata["runtime_requests"].values()
        )
        == 1
    )
    saved = state.drain(state.parent_id)
    assert saved.final_output["xiaox_result"]["business_completed"] is True
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1


def test_scanner_cursor_reaches_a_due_review_after_an_incompatible_older_checkpoint(
    pending_business_review, review_task, monkeypatch
):
    state = pending_business_review
    stale = review_task
    report = _review(stale, status="unavailable", error_code="goal_verification_timeout")
    _finish(stale, report)

    def block(run, _metadata):
        run.status = "blocked"
        run.metadata[JOB_KEY]["next_attempt_at"] = 0
        run.metadata[JOB_KEY]["version"] = "retired-verifier-version"

    stale.store.update(stale.run_id, block)
    stale.store.close(stale.run_id, "goal_verification_timeout", generation=stale.generation)
    _make_due(state)  # The recoverable row is deliberately later than the incompatible one.
    _forbid_execution(monkeypatch)
    cursor = {}
    assert (
        checkpoint.enqueue_pending_goal_verifications(
            repository=state.repository, cursor=cursor, limit=1
        )
        == 0
    )
    assert cursor["run_id"] == stale.run_id
    assert (
        checkpoint.enqueue_pending_goal_verifications(
            repository=state.repository, cursor=cursor, limit=1
        )
        == 1
    )
    assert cursor["run_id"] == state.parent_id
    assert (
        checkpoint.enqueue_pending_goal_verifications(
            repository=state.repository, cursor=cursor, limit=1
        )
        == 0
    )
    assert cursor == {}, "an exhausted scan must wrap instead of abandoning older pending rows"
    saved = state.drain(state.parent_id)
    assert saved.final_output["xiaox_result"]["business_completed"] is True
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1
    assert stale.repository.get(stale.run_id).metadata[JOB_KEY]["attempts"] == 1


@pytest.mark.parametrize("pending_business_review", ["unknown_transport"], indirect=True)
def test_unknown_model_charge_does_not_schedule_another_review_or_business_action(
    pending_business_review,
    monkeypatch,
):
    state = pending_business_review
    _forbid_execution(monkeypatch)
    _make_due(state)
    parent = state.repository.get(state.parent_id)
    assert parent.metadata["xiaox_runtime"]["model_reconciliation_required"] is True
    assert any(
        entry["state"] == "unknown"
        for entry in parent.metadata["xiaox_runtime"]["model_requests"].values()
    )
    before = copy.deepcopy(parent.metadata["xiaox_runtime"]["model_requests"])
    for _ in range(2):
        assert (
            checkpoint.enqueue_pending_goal_verifications(
                repository=SQLAlchemyAgentRunRepository(session_factory=state.actor.factory),
            )
            == 0
        )
    after = state.repository.get(state.parent_id)
    assert after.metadata["xiaox_runtime"]["model_requests"] == before
    assert not after.final_output["xiaox_result"]["business_completed"]
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1
    assert (
        XiaoxBindingStore(state.repository).receipt_snapshot(state.parent_id) == state.original_rows
    )


@pytest.mark.parametrize("control", ["cancel", "pause", "revoke_actor"])
def test_recovery_queue_rechecks_controls_without_dispatch(
    pending_business_review, monkeypatch, control
):
    from app.db.models.user import User

    state = pending_business_review
    _forbid_execution(monkeypatch)
    _make_due(state)
    if control in {"cancel", "pause"}:
        state.repository.request_task_control(
            state.parent_id,
            control,
            requested_by=str(state.actor.user_id),
        )
    else:
        with state.actor.factory.begin() as db:
            db.get(User, state.actor.user_id).is_active = False
    assert checkpoint.enqueue_pending_goal_verifications(repository=state.repository) == 0
    saved = state.repository.get(state.parent_id)
    assert not saved.final_output["xiaox_result"]["ok"]
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1
    assert state.names() == ["verification-only-customer"]


def _restore_last_pre_crash_commit(state):
    """Restore the actual SQL snapshot captured before any runtime finalization."""
    import json
    from datetime import UTC, datetime, timedelta

    from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord
    from app.domain.task_lifecycle.control import SessionBook

    original = copy.deepcopy(state.crash_run)
    metadata = original.metadata["xiaox_runtime"]
    job = original.metadata[JOB_KEY]
    # Move only the owner's clocks back to represent downtime. Frozen business
    # receipts remain byte-for-byte identical to the actual committed operation.
    elapsed = 3600
    for key in ("active_started_at", "deadline_at", "execution_deadline_at", "expires_at"):
        if metadata.get(key) is not None:
            metadata[key] -= elapsed
    for key in ("started_at", "observed_at"):
        if job.get(key) is not None:
            job[key] -= elapsed
    observed = datetime.fromisoformat(original.updated_at) - timedelta(seconds=elapsed)
    original.updated_at = observed.isoformat()
    with state.actor.factory.begin() as db:
        record = db.get(AgentRunRecord, state.parent_id)
        record.status = original.status
        record.updated_at = original.updated_at
        record.payload_json = json.dumps(original.to_dict(), ensure_ascii=False)
        SessionBook(db).put(
            "agent", str(state.actor.tenant_id), state.parent_id, copy.deepcopy(state.crash_control)
        )
        if state.crash_queue:
            queued = db.get(AgentTaskExecutionRecord, state.parent_id)
            for name, value in state.crash_queue.items():
                setattr(queued, name, value)
            queued.lease_expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    return original


@pytest.mark.parametrize("pending_business_review", ["queued_process_loss"], indirect=True)
def test_startup_and_new_queue_lease_recover_a_process_loss_after_settled_review_response(
    pending_business_review, monkeypatch
):
    from app.application.agent_orchestrator import stale_run_reconciler
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher

    state = pending_business_review
    before = _restore_last_pre_crash_commit(state)
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    assert state.repository.get(state.parent_id).status == "running"
    old_count = state.queue.get(state.parent_id).execution_count
    recovered = state.queue.claim("restarted-verifier", lease_seconds=120)
    if recovered is None:
        from app.domain.task_lifecycle.control import SessionBook

        with state.actor.factory() as db:
            current = SessionBook(db).get("agent", str(state.actor.tenant_id), state.parent_id)
        pytest.fail(str({"original_control": state.crash_control, "current_control": current}))
    assert recovered.execution_count == old_count + 1
    AgentTaskDispatcher(
        execution_repository=state.queue, run_repository=state.repository
    )._execute_claim(recovered, "restarted-verifier")
    after = state.repository.get(state.parent_id)
    assert after.final_output["xiaox_result"]["business_completed"] is True, after.final_output
    assert after.metadata[JOB_KEY]["state"] == "verified"
    assert after.metadata[JOB_KEY]["attempts"] == 2
    assert (
        after.metadata["xiaox_runtime"]["active_seconds"]
        >= before.metadata["xiaox_runtime"]["active_seconds"]
    )
    assert after.metadata["xiaox_runtime"]["active_seconds"] < 120
    assert state.queue.get(state.parent_id).state == "succeeded"
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1
    assert (
        XiaoxBindingStore(state.repository).receipt_snapshot(state.parent_id) == state.original_rows
    )


@pytest.mark.parametrize("pending_business_review", ["direct_process_loss"], indirect=True)
def test_startup_parks_expired_synchronous_review_then_original_scanner_recovers(
    pending_business_review, monkeypatch
):
    from app.application.agent_orchestrator import stale_run_reconciler

    state = pending_business_review
    _restore_last_pre_crash_commit(state)
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert state.crash_queue is None
    assert stale_run_reconciler.reconcile_stale_running_runs() == 1
    recovered = state.repository.get(state.parent_id)
    assert recovered.status == "blocked"
    assert recovered.metadata[JOB_KEY]["state"] == "pending"
    assert recovered.metadata["xiaox_runtime"]["coordinator_active"] is False
    assert checkpoint.enqueue_pending_goal_verifications(repository=state.repository) == 1
    after = state.drain(state.parent_id)
    assert after.final_output["xiaox_result"]["business_completed"] is True
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1


@pytest.mark.parametrize("pending_business_review", ["queued_process_loss_unknown"], indirect=True)
def test_process_loss_does_not_clear_an_unknown_model_charge_or_start_a_new_review(
    pending_business_review, monkeypatch
):
    from app.application.agent_orchestrator import stale_run_reconciler

    state = pending_business_review
    original = _restore_last_pre_crash_commit(state)
    before = copy.deepcopy(original.metadata["xiaox_runtime"]["model_requests"])
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    after = state.drain(state.parent_id)
    assert after.final_output["xiaox_result"]["reconciliation_required"] is True
    assert after.metadata["xiaox_runtime"]["model_requests"] == before
    assert not after.final_output["xiaox_result"]["ok"]
    assert checkpoint.enqueue_pending_goal_verifications(repository=state.repository) == 0
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1


@pytest.mark.parametrize("pending_business_review", ["queued_process_loss"], indirect=True)
@pytest.mark.parametrize("exhausted", ["attempts", "active_time"])
def test_process_loss_exhaustion_is_terminal_without_dispatching_another_review(
    pending_business_review, monkeypatch, exhausted
):
    from app.application.agent_orchestrator import stale_run_reconciler

    state = pending_business_review
    # The same last pre-crash write is replayed with the already-consumed recovery
    # count. No goal, response, ledger receipt or billing row is changed.
    if exhausted == "attempts":
        state.crash_run.metadata[JOB_KEY]["attempts"] = 3
    else:
        runtime = state.crash_run.metadata["xiaox_runtime"]
        runtime["active_seconds"] = runtime["runtime_config"]["max_active_seconds"]
    _restore_last_pre_crash_commit(state)
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    after = state.drain(state.parent_id)
    job = after.metadata[JOB_KEY]
    assert job["state"] == "blocked" and job["attempts"] == (3 if exhausted == "attempts" else 1)
    assert job["terminal_code"] == (
        "goal_verification_budget_exhausted"
        if exhausted == "attempts"
        else "runtime_budget_exhausted"
    )
    assert after.final_output["xiaox_result"]["retryable"] is False
    assert not after.final_output["xiaox_result"].get("reconciliation_required", False)
    assert checkpoint.enqueue_pending_goal_verifications(repository=state.repository) == 0
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1


@pytest.mark.parametrize("pending_business_review", ["queued_process_loss"], indirect=True)
@pytest.mark.parametrize("tamper", ["child_output", "child_parent", "intent", "step_id"])
def test_crash_recovery_never_clears_a_child_effect_from_parent_verified_flags_alone(
    pending_business_review, monkeypatch, tamper
):
    from app.domain.task_lifecycle.control import SessionBook

    state = pending_business_review
    _restore_last_pre_crash_commit(state)
    _forbid_execution(monkeypatch)
    parent = state.repository.get(state.parent_id)
    call = next(iter(parent.metadata["xiaox_runtime"]["calls"].values()))
    assert call["receipt"]["verified"] is True
    if tamper in {"child_output", "child_parent"}:
        child = state.repository.get(call["child_run_id"])
        if tamper == "child_output":
            import json

            from app.db.models.agent import AgentRunRecord

            # Normal repository saves correctly reject alteration of a verified
            # receipt; inject storage corruption to exercise the recovery reader.
            child.tool_calls[0].output["success"] = False
            with state.actor.factory.begin() as db:
                db.get(AgentRunRecord, child.run_id).payload_json = json.dumps(
                    child.to_dict(), ensure_ascii=False
                )
        else:
            child.metadata["runtime_context"]["parent_run_id"] = "another-original-parent"
            state.repository.save(child)
    elif tamper == "intent":
        call["params"]["unit_name"] = "a-different-business-intent"
        call["fingerprint"] = canonical_digest(
            {key: call[key] for key in ("tool_id", "action", "params")}
        )
        state.repository.save(parent)
    else:
        with state.actor.factory.begin() as db:
            book = SessionBook(db)
            body = book.get("agent", str(state.actor.tenant_id), state.parent_id)
            body["effects"] = [f"child:{call['child_run_id']}:a-different-step"]
            book.put("agent", str(state.actor.tenant_id), state.parent_id, body)
    with state.actor.factory() as db:
        before = SessionBook(db).get("agent", str(state.actor.tenant_id), state.parent_id)[
            "effects"
        ]
    assert before
    assert state.queue.claim("restarted-verifier", lease_seconds=120) is None
    with state.actor.factory() as db:
        after = SessionBook(db).get("agent", str(state.actor.tenant_id), state.parent_id)["effects"]
    assert after == before
    assert state.queue.get(state.parent_id).state == "unknown"
    assert len(state.transports) == len(state.model_requests) == len(state.dispatches) == 1


@pytest.mark.parametrize(
    "pending_business_review",
    [
        "queued_process_loss_after_pending",
        "queued_process_loss_after_verified",
        "queued_process_loss_after_reply",
        "queued_process_loss_after_blocked",
    ],
    indirect=True,
)
def test_committed_review_recovers_after_process_loss_before_runtime_finalization(
    pending_business_review, monkeypatch
):
    from app.application.agent_orchestrator import stale_run_reconciler

    state = pending_business_review
    original_state = state.crash_run.metadata[JOB_KEY]["state"]
    if original_state == "verified":
        # An already verified third attempt must only publish its committed
        # verdict, never require a forbidden fourth attempt to acknowledge it.
        state.crash_run.metadata[JOB_KEY]["attempts"] = 3
    original = _restore_last_pre_crash_commit(state)
    _forbid_execution(monkeypatch)
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    saved = state.drain(state.parent_id)
    result = saved.final_output["xiaox_result"]
    assert len(state.transports) == len(state.model_requests) == 1
    assert len(state.dispatches) == len(state.original_rows)
    assert (
        XiaoxBindingStore(state.repository).receipt_snapshot(state.parent_id) == state.original_rows
    )
    if original_state == "blocked":
        assert saved.metadata[JOB_KEY]["state"] == "blocked"
        assert not result["ok"] and result["retryable"] is False
        assert result["terminal_code"] == "goal_verification_budget_exhausted"
    else:
        assert result["ok"] and saved.metadata[JOB_KEY]["state"] == "verified", result
        assert bool(result["business_completed"]) is bool(state.original_rows)
        assert bool(result["reply_completed"]) is not bool(state.original_rows)
        if original_state == "verified":
            assert saved.metadata[JOB_KEY]["attempts"] == 3
            assert (
                saved.metadata["runtime_goal_verification"]
                == original.metadata["runtime_goal_verification"]
            )


@pytest.mark.parametrize(
    "pending_business_review", ["queued_process_loss_after_needs_work"], indirect=True
)
def test_committed_gap_report_recovers_to_original_compensation_without_repeating_the_write(
    pending_business_review, monkeypatch
):
    from app.application.agent_orchestrator import stale_run_reconciler

    state = pending_business_review
    assert state.crash_run.metadata[JOB_KEY]["state"] == "needs_work"
    original = _restore_last_pre_crash_commit(state)

    def no_more_writes(*_args, **_kwargs):
        pytest.fail("the persisted gap only needs an explanation, not another business write")

    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.AgentToolExecutor.execute", no_more_writes
    )
    state.script = lambda _binding, _text: "该客户用于记录业务往来；原客户已创建并核验。"
    state.review = lambda prompt: fixture_goal_review(prompt, kind="write")
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "0")
    assert stale_run_reconciler.reconcile_stale_running_runs() == 0
    saved = state.drain(state.parent_id)
    assert saved.final_output["xiaox_result"]["business_completed"] is True, saved.final_output
    assert len(state.dispatches) == 1 and state.names() == ["verification-only-customer"]
    assert len(state.transports) == len(state.model_requests) == 2
    assert any(
        entry.get("source") == "independent_goal_compensation"
        for entry in saved.metadata["runtime_requests"].values()
    )
    assert (
        saved.metadata["xiaox_runtime"]["thread_id"]
        == original.metadata["xiaox_runtime"]["thread_id"]
    )
    assert (
        XiaoxBindingStore(state.repository).receipt_snapshot(state.parent_id) == state.original_rows
    )
