"""The original dispatcher observes receipts without replay or session renewal."""

from __future__ import annotations

import copy
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    project_verification,
)
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2
from app.application.agent_orchestrator.verification_recovery import (
    VERIFICATION_RECOVERY_KEY,
    reconcile_pending_verifications,
    recover_stopped_verification,
)
from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord
from app.domain.task_lifecycle.control import SessionBook
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_kellai_verification_readback import delivery as delivery
from tests.test_application.test_verification_recovery import _add_failed_read, _run, _verified

KEY = VERIFICATION_RECOVERY_KEY


@pytest.fixture
def pending_receipt(trusted_actor, monkeypatch):
    actor = trusted_actor(user_id=17, tenant_id=7)
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    run = _run()
    run.metadata["runtime_context"] = copy.deepcopy(actor.context)
    project_verification(run)
    repository.save(run)
    queue.enqueue(run)
    queue.claim("original-worker", lease_seconds=60)
    queue.finish(run.run_id, "original-worker", "blocked")
    observed = []
    source = {"ready": True}

    def read(**kwargs):
        observed.append(copy.deepcopy(kwargs["context"]))
        return (
            _verified(**kwargs)
            if source["ready"]
            else {"status": "inconclusive", "code": "source_pending", "checks": []}
        )

    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        read,
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.AgentToolExecutor.execute",
        lambda *args, **kwargs: pytest.fail("observation/finalization must not dispatch a tool"),
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.resume_transaction.renew_approval_session",
        lambda *args, **kwargs: pytest.fail("automatic verification cannot renew authorization"),
    )
    return SimpleNamespace(
        actor=actor, repo=repository, queue=queue, run=run, observed=observed, source=source
    )


def test_dispatcher_observer_discovers_original_pending_receipt(pending_receipt):
    runtime = pending_receipt
    dispatcher = AgentTaskDispatcher(
        run_repository=runtime.repo, execution_repository=runtime.queue
    )
    dispatcher._recover_outcomes()
    dispatcher._outcome_worker.join(timeout=10)
    assert not dispatcher._outcome_worker.is_alive()
    assert len(runtime.observed) == 1
    assert runtime.repo.get(runtime.run.run_id).status == "queued"
    assert runtime.queue.get(runtime.run.run_id).state == "queued"


def _recover(runtime, *, now=1000, repository=None, limit=10):
    return reconcile_pending_verifications(
        repository=repository or runtime.repo, now=now, limit=limit
    )


def _persist(runtime, run, *, state="blocked", effects=()):
    project_verification(run)
    runtime.repo.save(run)
    runtime.queue.enqueue(run)
    owner = uuid.uuid4().hex
    runtime.queue.claim(owner, lease_seconds=60, run_id=run.run_id)
    for effect in effects:
        assert runtime.queue.mark_open_effect(run.run_id, effect, owner_id=owner)
    runtime.queue.finish(
        run.run_id, owner, state, error_code="needs_verification" if effects else ""
    )


def _another(runtime, *, unknown=False, failed_read=False):
    run = _run()
    run.run_id = "run_" + uuid.uuid4().hex
    run.metadata["runtime_context"] = copy.deepcopy(runtime.actor.context)
    step, call = run.steps[0], run.tool_calls[0]
    if unknown:
        step.status = call.status = "failed"
        step.output = {
            "success": False,
            "outcome": "unknown",
            "retryable": False,
            "reconciliation_required": True,
        }
        call.output = copy.deepcopy(step.output)
        run.metadata.update(
            non_retryable=True, recovery={"state": "manual_reconciliation_required"}
        )
    freeze_verification_contract(
        run,
        step,
        call,
        ToolActionSpecV2(
            tool_id=step.tool_id,
            action=step.action,
            read_only=True,
            output_schema={"type": "object"},
        ),
        run.metadata["runtime_context"],
    )
    bind_execution_receipt(call)
    if failed_read:
        _add_failed_read(run)
    return run


def test_pending_source_backoff_then_original_graph_finalizes_without_new_call(pending_receipt):
    runtime = pending_receipt
    original = runtime.repo.get(runtime.run.run_id)
    runtime.source["ready"] = False
    assert _recover(runtime) == 1
    waiting = runtime.repo.get(runtime.run.run_id)
    assert waiting.status == "blocked"
    assert waiting.metadata[KEY]["status"] == "pending"
    assert waiting.metadata[KEY]["next_attempt_at"] == 1010
    assert _recover(runtime, now=1001) == 0
    runtime.source["ready"] = True
    restarted = SQLAlchemyAgentRunRepository(session_factory=runtime.actor.factory)
    assert _recover(runtime, now=1011, repository=restarted) == 1
    queued = restarted.get(runtime.run.run_id)
    assert queued.status == "queued" and queued.metadata[KEY]["status"] == "queued"
    assert queued.metadata["runtime_context"] == original.metadata["runtime_context"]
    assert queued.steps == original.steps
    assert queued.tool_calls[0].output == original.tool_calls[0].output
    assert queued.tool_calls[0].cost_units == original.tool_calls[0].cost_units
    dispatcher = AgentTaskDispatcher(run_repository=restarted, execution_repository=runtime.queue)
    claim = runtime.queue.claim("finalization-only", lease_seconds=60, run_id=queued.run_id)
    dispatcher._execute_claim(claim, "finalization-only")
    finished = restarted.get(queued.run_id)
    assert finished.status == "completed", finished.to_dict()
    assert runtime.queue.get(queued.run_id).state == "succeeded"
    assert len(finished.tool_calls) == 1 and finished.steps[0].attempt_count == 1
    assert len(runtime.observed) == 2


def test_sql_due_filter_skips_unrelated_delayed_and_malformed_rows_before_limit(pending_receipt):
    runtime = pending_receipt
    for index in range(12):
        unrelated = AgentRun(user_id="17", message=f"other-{index}", status="blocked")
        runtime.repo.save(unrelated)
    delayed = _another(runtime)
    delayed.metadata[KEY] = {"status": "pending", "next_attempt_at": 2000}
    _persist(runtime, delayed)
    with runtime.actor.factory.begin() as db:
        db.get(AgentRunRecord, unrelated.run_id).payload_json = "invalid JSON"
    restarted = SQLAlchemyAgentRunRepository(session_factory=runtime.actor.factory)
    assert _recover(runtime, repository=restarted, limit=1) == 1
    assert restarted.get(runtime.run.run_id).status == "queued"
    assert restarted.get(delayed.run_id).status == "blocked"
    assert len(runtime.observed) == 1


def test_concurrent_observers_have_one_durable_claim_and_one_read(pending_receipt, monkeypatch):
    from app.application.agent_orchestrator import verification_recovery as observer

    runtime = pending_receipt
    barrier = threading.Barrier(2)
    save = observer._save_observation

    def competing_claim(repository, run, previous, proof):
        if run.metadata.get(KEY, {}).get("status") == "observing" and KEY not in previous.metadata:
            barrier.wait(timeout=5)
        return save(repository, run, previous, proof)

    monkeypatch.setattr(observer, "_save_observation", competing_claim)
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(_recover, runtime) for _ in range(2)]
        assert sorted(attempt.result(timeout=15) for attempt in attempts) == [0, 1]
    assert len(runtime.observed) == 1
    assert runtime.queue.get(runtime.run.run_id).state == "queued"
    saved = runtime.repo.get(runtime.run.run_id)
    assert saved.metadata[KEY]["attempt"] == 1
    assert sum(event.event_type == "verification.rechecked" for event in saved.events) == 1


def test_process_exit_after_claim_waits_for_observation_lease(pending_receipt, monkeypatch):
    from app.application.agent_orchestrator import verification_recovery as observer

    runtime = pending_receipt
    read = observer.reverify_run

    def die(*args, **kwargs):
        raise SystemExit("stopped before source read")

    monkeypatch.setattr(observer, "reverify_run", die)
    with pytest.raises(SystemExit):
        _recover(runtime)
    assert runtime.repo.get(runtime.run.run_id).metadata[KEY]["status"] == "observing"
    monkeypatch.setattr(observer, "reverify_run", read)
    assert _recover(runtime, now=1119) == 0
    assert _recover(runtime, now=1121) == 1
    assert len(runtime.observed) == 1
    assert runtime.repo.get(runtime.run.run_id).metadata[KEY]["attempt"] == 2


@pytest.mark.parametrize("state", ["blocked", "running"])
def test_live_queue_lease_blocks_automatic_read(pending_receipt, state):
    runtime = pending_receipt
    with runtime.actor.factory.begin() as db:
        row = db.get(AgentTaskExecutionRecord, runtime.run.run_id)
        row.state, row.lease_owner = state, "live-owner"
        row.lease_expires_at = "2099-01-01T00:00:00+00:00"
    assert _recover(runtime) == 0
    assert runtime.observed == []
    assert KEY not in runtime.repo.get(runtime.run.run_id).metadata


def test_queue_changed_during_read_cannot_save_or_finalize(pending_receipt, monkeypatch):
    runtime = pending_receipt

    def takeover(**kwargs):
        with runtime.actor.factory.begin() as db:
            row = db.get(AgentTaskExecutionRecord, runtime.run.run_id)
            row.state, row.lease_owner = "running", "replacement-owner"
            row.lease_expires_at = "2099-01-01T00:00:00+00:00"
            row.execution_count += 1
        return _verified(**kwargs)

    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        takeover,
    )
    assert _recover(runtime) == 1
    saved = runtime.repo.get(runtime.run.run_id)
    assert saved.status == "blocked"
    assert saved.tool_calls[0].metadata["verification"]["status"] == "pending"
    assert saved.steps == runtime.run.steps
    assert runtime.queue.get(saved.run_id).lease_owner == "replacement-owner"


def test_finalization_transaction_rechecks_cancellation_after_read(pending_receipt, monkeypatch):
    from app.application.agent_orchestrator import resume_transaction

    runtime = pending_receipt
    retry = resume_transaction.retry_and_enqueue

    def cancel_before_finalization(*args, **kwargs):
        current = runtime.repo.get(runtime.run.run_id)
        current.status = "cancelled"
        current.metadata["control"] = {"state": "cancelled"}
        runtime.repo.save(current)
        return retry(*args, **kwargs)

    monkeypatch.setattr(resume_transaction, "retry_and_enqueue", cancel_before_finalization)
    assert _recover(runtime) == 1
    assert runtime.repo.get(runtime.run.run_id).status == "cancelled"
    assert runtime.queue.get(runtime.run.run_id).state == "blocked"


def test_finalization_transaction_rechecks_latest_independent_verdict(pending_receipt, monkeypatch):
    from app.application.agent_orchestrator import resume_transaction
    from app.application.agent_orchestrator.verification_recovery import reverify_run

    runtime = pending_receipt
    retry = resume_transaction.retry_and_enqueue

    def competing_observation(*args, **kwargs):
        runtime.source["ready"] = False
        reverify_run(runtime.repo, runtime.run.run_id, require_stopped_queue=True)
        return retry(*args, **kwargs)

    monkeypatch.setattr(resume_transaction, "retry_and_enqueue", competing_observation)
    assert _recover(runtime) == 1
    saved = runtime.repo.get(runtime.run.run_id)
    assert saved.metadata["verification"]["accepted"] is False
    assert saved.metadata[KEY]["status"] == "pending"
    assert saved.status == "blocked"
    assert runtime.queue.get(saved.run_id).state == "blocked"


def test_stopped_failed_queue_finalizes_only_completed_successful_receipts(pending_receipt):
    runtime = pending_receipt
    run = _another(runtime)
    run.status = "failed"
    _persist(runtime, run, state="failed")
    assert runtime.queue.get(run.run_id).finished_at
    result = recover_stopped_verification(run.run_id, repository=runtime.repo, now=1000)
    assert result["status"] == "queued"
    assert runtime.repo.get(run.run_id).steps == run.steps
    assert runtime.queue.get(run.run_id).state == "queued"


def test_incomplete_parallel_read_is_observed_but_never_automatically_replayed(pending_receipt):
    runtime = pending_receipt
    run = _another(runtime, failed_read=True)
    _persist(runtime, run)
    original = runtime.repo.get(run.run_id)
    result = recover_stopped_verification(run.run_id, repository=runtime.repo, now=1000)
    assert result["status"] == "pending"
    saved = runtime.repo.get(run.run_id)
    assert saved.status == "blocked"
    assert saved.steps == original.steps
    assert saved.tool_calls[1] == original.tool_calls[1]
    assert runtime.queue.get(run.run_id).state == "blocked"


@pytest.mark.parametrize("queue_state", ["blocked", "unknown"])
def test_confirmed_receipt_does_not_clear_any_open_effect(pending_receipt, queue_state):
    runtime = pending_receipt
    run = _another(runtime)
    _persist(
        runtime, run, state=queue_state, effects=[run.steps[0].step_id, "unknown-child-effect"]
    )
    original_queue = runtime.queue.get(run.run_id).to_dict()
    with runtime.actor.factory() as db:
        original_effects = SessionBook(db).get("agent", "7", run.run_id)
    assert (
        recover_stopped_verification(run.run_id, repository=runtime.repo, now=1000)["status"]
        == "observed"
    )
    saved = runtime.repo.get(run.run_id)
    assert saved.metadata["verification"]["accepted"] is True
    assert saved.status == "blocked"
    assert runtime.queue.get(run.run_id).to_dict() == original_queue
    with runtime.actor.factory() as db:
        assert SessionBook(db).get("agent", "7", run.run_id) == original_effects


def test_unrecognized_unknown_raw_receipt_never_enters_readback_or_retry(pending_receipt):
    runtime = pending_receipt
    run = _another(runtime, unknown=True)
    _persist(runtime, run, state="unknown", effects=[run.steps[0].step_id])
    original = runtime.repo.get(run.run_id)
    queue = runtime.queue.get(run.run_id).to_dict()
    result = recover_stopped_verification(run.run_id, repository=runtime.repo, now=1000)
    assert result == {
        "status": "not_recoverable",
        "reason_code": "verification_receipt_not_observable",
    }
    saved = runtime.repo.get(run.run_id)
    assert saved.steps == original.steps and saved.tool_calls == original.tool_calls
    assert saved.metadata["non_retryable"] is True
    assert saved.metadata["recovery"] == original.metadata["recovery"]
    assert runtime.queue.get(run.run_id).to_dict() == queue
    assert runtime.observed == []


def test_expired_original_session_never_renews_or_reads_source(pending_receipt):
    from app.db.models.user import Session as UserSession
    from app.utils.time import utc_now_naive

    runtime = pending_receipt
    original = runtime.repo.get(runtime.run.run_id)
    with runtime.actor.factory.begin() as db:
        db.get(UserSession, runtime.actor.session_row_id).expires_at = utc_now_naive() - timedelta(
            seconds=1
        )
    assert _recover(runtime) == 1
    saved = runtime.repo.get(runtime.run.run_id)
    assert saved.metadata[KEY]["reason_code"] == "verification_authorization_unavailable"
    assert saved.metadata["runtime_context"] == original.metadata["runtime_context"]
    assert saved.status == "blocked" and runtime.observed == []


def _unknown_delivery(delivery, *, deadline_wrapper=False):
    from app import db as host_db

    case, receipt, _message, reads = delivery
    unknown = {
        "success": False,
        "outcome": "unknown",
        "retryable": False,
        "reconciliation_required": True,
        "data": {
            "request_id": receipt["request_id"],
            "delivery_receipt": {
                "request_id": receipt["request_id"],
                "status": "unknown",
            },
        },
    }
    case.step.output = (
        {
            "success": False,
            "outcome": "unknown",
            "retryable": False,
            "error_code": "tool_timeout_unknown",
            "reconciliation_required": True,
            "reconciliation_evidence": unknown,
        }
        if deadline_wrapper
        else unknown
    )
    case.call.output = copy.deepcopy(case.step.output)
    case.step.status = case.call.status = "failed"
    case.run.status = "failed"
    case.run.metadata.update(
        non_retryable=True, recovery={"state": "manual_reconciliation_required"}
    )
    bind_execution_receipt(case.call)
    repository = SQLAlchemyAgentRunRepository(session_factory=host_db.HostSessionLocal)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=host_db.HostSessionLocal)
    runtime = SimpleNamespace(repo=repository, queue=queue)
    _persist(runtime, case.run, state="unknown", effects=[case.step.step_id])
    if deadline_wrapper:
        with host_db.HostSessionLocal.begin() as db:
            db.get(
                AgentTaskExecutionRecord, case.run.run_id
            ).last_error_code = "tool_timeout_unknown"
    original = repository.get(case.run.run_id)
    queue_before = queue.get(case.run.run_id).to_dict()
    receipt["provider_state"] = "delivered"
    return case, repository, queue, original, queue_before, reads


@pytest.mark.parametrize("deadline_wrapper", [False, True])
def test_kellai_lost_ack_automatically_observes_original_delivery_only(delivery, deadline_wrapper):
    from app import db as host_db

    case, repository, queue, original, queue_before, reads = _unknown_delivery(
        delivery, deadline_wrapper=deadline_wrapper
    )
    assert reconcile_pending_verifications(repository=repository, now=1000) == 1
    saved = repository.get(case.run.run_id)
    report = saved.tool_calls[0].metadata["verification"]
    assert report["code"] == "original_delivery_observed_execution_unsettled", (
        saved.metadata.get(KEY),
        reads,
    )
    assert report["accepted"] is False
    assert report["checks"][0]["evidence"]["delivery_verified"] is True
    assert saved.steps == original.steps
    assert saved.tool_calls[0].output == original.tool_calls[0].output
    assert saved.metadata["non_retryable"] is True
    assert saved.status == "failed" and saved.metadata[KEY]["status"] == "observed"
    assert queue.get(saved.run_id).to_dict() == queue_before
    with host_db.HostSessionLocal() as db:
        assert SessionBook(db).get("agent", str(case.context["tenant_id"]), saved.run_id)[
            "effects"
        ] == [case.step.step_id]
    assert len(reads) == 2 and all("send" not in path for path in reads)
    assert reconcile_pending_verifications(repository=repository, now=2000) == 0


def test_unknown_delivery_observation_loses_to_original_run_cas(delivery, monkeypatch):
    from app.infrastructure import kellai_client

    case, repository, queue, original, queue_before, reads = _unknown_delivery(delivery)
    read = kellai_client.request_kellai

    def concurrent_update(path, connection, body=None):
        response = read(path, connection, body)
        if len(reads) == 1:
            current = repository.get(case.run.run_id)
            current.metadata["concurrent_note"] = "original task changed while reading"
            repository.save(current)
        return response

    monkeypatch.setattr(kellai_client, "request_kellai", concurrent_update)
    assert reconcile_pending_verifications(repository=repository, now=1000) == 1
    saved = repository.get(case.run.run_id)
    assert saved.metadata["concurrent_note"] == "original task changed while reading"
    assert saved.tool_calls == original.tool_calls and saved.steps == original.steps
    assert saved.metadata["verification"]["accepted"] is False
    assert queue.get(saved.run_id).to_dict() == queue_before


@pytest.mark.parametrize("changed", ["accepted", "output_hash", "contract_hash", "call_cost"])
def test_unknown_receipt_rejects_forged_observation_and_reprojects_retained_call(delivery, changed):
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash

    case, repository, queue, _original, queue_before, _reads = _unknown_delivery(delivery)
    assert reconcile_pending_verifications(repository=repository, now=1000) == 1
    before = repository.get(case.run.run_id)
    forged = copy.deepcopy(before)
    call = forged.tool_calls[0]
    report = call.metadata["verification"]
    if changed == "accepted":
        report.update(status="verified", accepted=True)
    elif changed == "output_hash":
        report["output_sha256"] = "0" * 64
    elif changed == "contract_hash":
        report["contract_sha256"] = "0" * 64
    else:
        call.cost_units += 1
    report["report_sha256"] = canonical_hash(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    forged.metadata["verification"] = {"status": "verified", "accepted": True}
    forged.final_output["verification"] = {"status": "verified", "accepted": True}
    assert repository.save_if_unchanged(forged, before)
    saved = repository.get(case.run.run_id)
    assert saved.tool_calls == before.tool_calls
    assert saved.steps == before.steps
    assert saved.metadata["verification"]["accepted"] is False
    assert saved.final_output["verification"] == saved.metadata["verification"]
    assert saved.metadata["non_retryable"] is True
    assert queue.get(saved.run_id).to_dict() == queue_before
