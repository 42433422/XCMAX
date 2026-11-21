"""Evidence-only recovery preserves original execution and task ownership."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import (
    AgentOrchestrator,
    InMemoryAgentRunRepository,
)
from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verification_blocked,
    verify_step_result,
)
from app.application.agent_orchestrator.run_lifecycle import safe_continuation_error
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_sql_repository import (
    SQLAlchemyAgentRunRepository,
)
from app.application.agent_orchestrator.runtime_context import (
    RuntimeContextOwnershipError,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2
from app.application.agent_orchestrator.verification_recovery import (
    VerificationRecoveryError,
    reverify_run,
    verification_can_finalize,
    verification_report,
)
from app.application.workflow.workflow_types import (
    PlanGraph,
    WorkflowNode,
    plan_from_dict,
    plan_to_dict,
)
from app.infrastructure.auth.agent_principal import (
    AgentPrincipal,
    require_agent_principal,
)


def _run(*, status="blocked", mod_id=""):
    context = {"user_id": "17", "actor_id": "17", "tenant_id": "7"}
    if mod_id:
        context.update(mod_id=mod_id, _mod_authorization={"mod_id": mod_id, "session": "old"})
    step = AgentStep(
        node_id="read",
        tool_id="products",
        action="query",
        params={"keyword": "red"},
        status="completed",
        idempotent=True,
        attempt_count=1,
        output={"success": True, "data": [{"id": 9}]},
    )
    plan = PlanGraph(
        plan_id="verification-plan",
        intent="read",
        todo_steps=[],
        nodes=[
            WorkflowNode(
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=copy.deepcopy(step.params),
                idempotent=True,
                risk="low",
            )
        ],
    )
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=copy.deepcopy(step.params),
        status="completed",
        output=copy.deepcopy(step.output),
        cost_units=3,
        metadata={"attempt_count": 1, "billing_status": "charged"},
    )
    run = AgentRun(
        run_id="run_verification_recovery",
        user_id="17",
        message="查询商品",
        status=status,
        plan_id=plan.plan_id,
        steps=[step],
        tool_calls=[call],
        metadata={
            "runtime_context": context,
            "execution": {"state": "idle"},
            "plan": plan_to_dict(plan),
        },
    )
    spec = ToolActionSpecV2(
        tool_id=step.tool_id,
        action=step.action,
        read_only=True,
        idempotent=True,
        output_schema={
            "type": "object",
            "required": ["success"],
            "properties": {"success": {"const": True}},
        },
    )
    freeze_verification_contract(run, step, call, spec, context)
    bind_execution_receipt(call)
    return run


def _verified(**kwargs):
    return {
        "status": "verified",
        "code": "independent_source_matched",
        "checks": [
            {
                "check_id": "readback",
                "status": "passed",
                "source": "separate_test_source",
                "evidence": {"version": 3},
            }
        ],
    }


def _add_failed_read(run, *, unknown=False):
    step = AgentStep(
        node_id="other_read",
        tool_id="products",
        action="query",
        params={"keyword": "blue"},
        status="completed" if unknown else "failed",
        idempotent=True,
        attempt_count=1,
        output=(
            {"success": True, "outcome": "unknown", "reconciliation_required": True}
            if unknown
            else {"success": False, "error_code": "temporary_read_failure"}
        ),
    )
    call = ToolCall(
        step_id=step.step_id,
        node_id=step.node_id,
        tool_id=step.tool_id,
        action=step.action,
        params=copy.deepcopy(step.params),
        status=step.status,
        output=copy.deepcopy(step.output),
        metadata={"attempt_count": 1},
    )
    run.steps.append(step)
    run.tool_calls.append(call)
    plan = plan_from_dict(run.metadata["plan"])
    plan.nodes.append(
        WorkflowNode(
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=copy.deepcopy(step.params),
            idempotent=True,
            risk="low",
        )
    )
    run.metadata["plan"] = plan_to_dict(plan)
    context = run.metadata["runtime_context"]
    freeze_verification_contract(
        run,
        step,
        call,
        ToolActionSpecV2(
            tool_id=step.tool_id,
            action=step.action,
            read_only=True,
            idempotent=True,
            output_schema={"type": "object"},
        ),
        context,
    )
    bind_execution_receipt(call)
    verify_step_result(run=run, step=step, call=call, context=context)
    return step, call


@pytest.fixture
def readback(monkeypatch):
    observed = []

    def verify(**kwargs):
        observed.append(copy.deepcopy(kwargs["context"]))
        return _verified(**kwargs)

    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        verify,
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.AgentToolExecutor.execute",
        lambda *args, **kwargs: pytest.fail("verification must not dispatch a business action"),
    )
    return observed


def test_reopen_sqlite_receipt_and_reverify_without_execution(tmp_path, readback):
    path = f"sqlite:///{tmp_path / 'runs.sqlite'}"
    engine = create_engine(path)
    original = _run()
    SQLAlchemyAgentRunRepository(session_factory=sessionmaker(bind=engine)).save(original)
    engine.dispose()
    reopened = create_engine(path)
    repo = SQLAlchemyAgentRunRepository(
        session_factory=sessionmaker(bind=reopened), auto_create=False
    )
    try:
        before = repo.get(original.run_id)
        verified = reverify_run(repo, original.run_id)
        assert verified.status == "blocked"
        assert verification_report(verified)["status"] == "verified"
        assert verification_can_finalize(verified)
        assert verified.steps[0].to_dict() == before.steps[0].to_dict()
        assert verified.tool_calls[0].output == before.tool_calls[0].output
        assert verified.tool_calls[0].cost_units == 3
        assert verified.tool_calls[0].metadata["attempt_count"] == 1
        assert verified.tool_calls[0].metadata["billing_status"] == "charged"
        assert len(readback) == 1
        assert (
            readback[0]["idempotency_key"]
            == f"agent:{original.run_id}:7:{original.steps[0].step_id}"
        )
        assert verified.events[-1].event_type == "verification.rechecked"
    finally:
        reopened.dispose()


def test_crashed_active_snapshot_requires_authoritative_expired_queue(tmp_path, readback):
    path = f"sqlite:///{tmp_path / 'crashed.sqlite'}"
    engine = create_engine(path)
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    run = _run(status="running")
    run.metadata["execution"] = {"state": "active", "started_at": "original-start"}
    repo.save(run)
    queue.enqueue(run)
    claimed = queue.claim("original-worker", lease_seconds=1)
    queue.mark_open_effect(run.run_id)
    with pytest.raises(VerificationRecoveryError, match="租约"):
        reverify_run(repo, run.run_id)
    assert not readback
    after_expiry = (
        datetime.fromisoformat(claimed.lease_expires_at) + timedelta(seconds=2)
    ).isoformat()
    assert queue.claim("replacement-worker", lease_seconds=10, now=after_expiry) is None
    assert queue.get(run.run_id).last_error_code == "needs_verification"
    assert queue.get(run.run_id).state == "unknown"
    assert not queue.get(run.run_id).finished_at
    stopped = queue.get(run.run_id).to_dict()
    assert repo.get(run.run_id).status == "running"
    engine.dispose()
    reopened = create_engine(path)
    fresh = SQLAlchemyAgentRunRepository(
        session_factory=sessionmaker(bind=reopened), auto_create=False
    )
    try:
        result = reverify_run(fresh, run.run_id)
        assert result.status == "blocked"
        assert result.metadata["execution"] == {"state": "idle", "started_at": "original-start"}
        assert verification_report(result)["accepted"] is True
        assert result.steps[0].attempt_count == 1
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].output == run.tool_calls[0].output
        assert len(readback) == 1
        assert queue.get(run.run_id).to_dict() == stopped
    finally:
        reopened.dispose()


def test_queue_changed_during_crash_reverification_fails_same_transaction_cas(
    tmp_path, monkeypatch
):
    from app.db.models.agent import AgentTaskExecutionRecord

    engine = create_engine(f"sqlite:///{tmp_path / 'queue-cas.sqlite'}")
    factory = sessionmaker(bind=engine)
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    run = _run(status="running")
    run.metadata["execution"] = {"state": "active"}
    repo.save(run)
    queue.enqueue(run)
    queue.claim("old-worker", lease_seconds=60)
    queue.mark_open_effect(run.run_id)
    queue.finish(run.run_id, "old-worker", "failed", error_code="needs_verification")

    def queue_changed(**kwargs):
        with factory.begin() as db:
            row = db.get(AgentTaskExecutionRecord, run.run_id)
            row.state = "running"
            row.lease_owner = "new-owner"
            row.execution_count += 1
        return _verified(**kwargs)

    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        queue_changed,
    )
    try:
        with pytest.raises(VerificationRecoveryError, match="已变化"):
            reverify_run(repo, run.run_id)
        stored = repo.get(run.run_id)
        assert stored.status == "running"
        assert stored.metadata["execution"]["state"] == "active"
        assert stored.tool_calls[0].metadata["verification"]["status"] == "pending"
        assert queue.get(run.run_id).lease_owner == "new-owner"
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "status", ["queued", "running", "completed", "paused", "cancelled", "rejected"]
)
def test_running_or_terminal_tasks_cannot_reopen(status, readback):
    repo = InMemoryAgentRunRepository()
    run = _run(status=status)
    repo.save(run)
    before = repo.get(run.run_id).to_dict()
    with pytest.raises(VerificationRecoveryError):
        reverify_run(repo, run.run_id)
    assert repo.get(run.run_id).to_dict() == before
    assert not readback


def test_active_execution_owner_blocks_reverification(readback):
    repo = InMemoryAgentRunRepository()
    run = _run()
    run.metadata["execution"]["state"] = "active"
    repo.save(run)
    with pytest.raises(VerificationRecoveryError):
        reverify_run(repo, run.run_id)
    assert not readback


def test_in_memory_crash_proof_must_use_the_paired_run_and_queue(monkeypatch, readback):
    from app.application.agent_orchestrator import run_repository, task_execution_repository

    repo = InMemoryAgentRunRepository()
    queue = task_execution_repository.InMemoryTaskExecutionRepository()
    run = _run(status="running")
    run.metadata["execution"] = {"state": "active"}
    repo.save(run)
    queue.enqueue(run)
    queue.claim("old-worker", lease_seconds=60)
    queue.mark_open_effect(run.run_id)
    queue.finish(run.run_id, "old-worker", "failed", error_code="needs_verification")
    monkeypatch.setattr(
        run_repository, "get_agent_run_repository", lambda: InMemoryAgentRunRepository()
    )
    monkeypatch.setattr(task_execution_repository, "get_task_execution_repository", lambda: queue)
    with pytest.raises(VerificationRecoveryError, match="权威"):
        reverify_run(repo, run.run_id)
    assert not readback
    monkeypatch.setattr(run_repository, "get_agent_run_repository", lambda: repo)
    result = reverify_run(repo, run.run_id)
    assert result.status == "blocked"
    assert result.metadata["execution"]["state"] == "idle"
    assert result.steps[0].attempt_count == 1


@pytest.mark.parametrize("changed", [{"user_id": "18"}, {"tenant_id": "8"}, {"mod_id": "other"}])
def test_reverification_cannot_cross_original_scope(changed, readback):
    repo = InMemoryAgentRunRepository()
    run = _run()
    repo.save(run)
    with pytest.raises(RuntimeContextOwnershipError):
        reverify_run(
            repo,
            run.run_id,
            runtime_context={"user_id": "17", "tenant_id": "7", **changed},
        )
    assert not readback


def test_new_read_session_is_ephemeral_and_original_operation_stays_bound(readback):
    repo = InMemoryAgentRunRepository()
    run = _run(mod_id="company")
    run.metadata["runtime_context"]["_actor_authorization"] = {"session": "old"}
    repo.save(run)
    current = {
        "user_id": "17",
        "tenant_id": "7",
        "mod_id": "company",
        "_actor_authorization": {"session": "new"},
        "_mod_authorization": {"mod_id": "company", "session": "new"},
        "idempotency_key": "caller-cannot-rebind-operation",
    }
    result = reverify_run(repo, run.run_id, runtime_context=current)
    assert result.metadata["runtime_context"] == run.metadata["runtime_context"]
    assert readback[0]["_actor_authorization"] == {"session": "new"}
    assert readback[0]["_mod_authorization"]["session"] == "new"
    assert readback[0]["idempotency_key"] != current["idempotency_key"]
    assert "session" not in str(result.metadata["verification"])


def test_unknown_execution_markers_cannot_be_cleared_by_verification(readback):
    repo = InMemoryAgentRunRepository()
    run = _run()
    run.metadata.update(
        non_retryable=True,
        recovery={"state": "manual_reconciliation_required", "reason": "lost_receipt"},
    )
    repo.save(run)
    result = reverify_run(repo, run.run_id)
    assert result.metadata["non_retryable"] is True
    assert result.metadata["recovery"] == run.metadata["recovery"]
    assert not verification_can_finalize(result)


def test_missing_original_contract_cannot_be_minted_after_execution(readback):
    repo = InMemoryAgentRunRepository()
    run = _run()
    run.tool_calls[0].metadata.clear()
    repo.save(run)
    assert verification_report(run) == {
        "status": "not_verified",
        "accepted": False,
        "steps": [],
    }
    with pytest.raises(VerificationRecoveryError):
        reverify_run(repo, run.run_id)
    assert not readback


def test_failed_parallel_read_does_not_prevent_observing_a_completed_action(readback):
    repo = InMemoryAgentRunRepository()
    run = _run()
    _add_failed_read(run)
    repo.save(run)
    before = repo.get(run.run_id)
    assert verification_blocked(before)
    assert safe_continuation_error(before)

    result = reverify_run(repo, run.run_id)

    assert len(readback) == 1
    assert result.tool_calls[0].metadata["verification"]["status"] == "verified"
    assert result.steps[0].to_dict() == before.steps[0].to_dict()
    assert result.tool_calls[0].output == before.tool_calls[0].output
    assert result.steps[1].to_dict() == before.steps[1].to_dict()
    assert result.tool_calls[1].to_dict() == before.tool_calls[1].to_dict()
    assert verification_report(result)["accepted"] is False
    assert verification_report(result)["status"] == "failed"
    assert not verification_can_finalize(result)
    assert not verification_blocked(result)
    assert safe_continuation_error(result) == ""
    assert result.status == "blocked"

    # Only an explicit original retry may now prepare the failed read. The
    # completed action retains its original receipt and attempt, with no replay.
    queued = AgentOrchestrator(repository=repo).retry_run(run.run_id, auto_execute=False)
    assert queued.status == "queued"
    assert queued.steps[0].to_dict() == before.steps[0].to_dict()
    assert queued.steps[1].status == "pending"
    assert len(queued.tool_calls) == 2
    assert len(readback) == 1


def test_observing_a_completed_action_preserves_parallel_unknown_receipt(readback):
    repo = InMemoryAgentRunRepository()
    run = _run()
    _add_failed_read(run, unknown=True)
    run.metadata.update(
        non_retryable=True,
        recovery={"state": "manual_reconciliation_required", "reason": "unknown_parallel_read"},
    )
    repo.save(run)
    before = repo.get(run.run_id)

    result = reverify_run(repo, run.run_id)

    assert len(readback) == 1
    assert result.tool_calls[0].metadata["verification"]["status"] == "verified"
    assert result.tool_calls[1].to_dict() == before.tool_calls[1].to_dict()
    assert result.steps[1].to_dict() == before.steps[1].to_dict()
    assert result.metadata["non_retryable"] is True
    assert result.metadata["recovery"] == before.metadata["recovery"]
    assert safe_continuation_error(result)
    assert not verification_can_finalize(result)


@pytest.mark.parametrize("state", ["failed", "running", "unknown"])
def test_no_complete_successful_receipt_cannot_trigger_reverification(state, readback):
    repo = InMemoryAgentRunRepository()
    run = _run()
    step, call = _add_failed_read(run, unknown=state == "unknown")
    run.steps, run.tool_calls = [step], [call]
    if state == "running":
        step.status = call.status = "running"
        step.output = call.output = {}
    repo.save(run)
    before = repo.get(run.run_id).to_dict()

    with pytest.raises(VerificationRecoveryError, match="没有可重新核验"):
        reverify_run(repo, run.run_id)

    assert repo.get(run.run_id).to_dict() == before
    assert not readback


def test_concurrent_cancellation_wins_the_observation_cas(monkeypatch):
    repo = InMemoryAgentRunRepository()
    run = _run()
    repo.save(run)

    def cancel_while_observing(**kwargs):
        cancelled = repo.get(run.run_id)
        cancelled.status = "cancelled"
        cancelled.metadata["control"] = {"state": "cancelled"}
        repo.save(cancelled)
        return _verified(**kwargs)

    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        cancel_while_observing,
    )
    with pytest.raises(VerificationRecoveryError, match="已变化"):
        reverify_run(repo, run.run_id)
    stored = repo.get(run.run_id)
    assert stored.status == "cancelled"
    assert stored.tool_calls[0].metadata["verification"]["status"] == "pending"


def test_two_verifiers_cannot_overwrite_each_others_observation(monkeypatch):
    repo = InMemoryAgentRunRepository()
    run = _run()
    repo.save(run)
    barrier = Barrier(2)

    def independent_reads(**kwargs):
        barrier.wait(timeout=5)
        return _verified(**kwargs)

    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        independent_reads,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reverify_run, repo, run.run_id) for _ in range(2)]
        results = []
        for future in futures:
            try:
                results.append(future.result(timeout=10))
            except VerificationRecoveryError:
                results.append("conflict")
    assert results.count("conflict") == 1
    stored = repo.get(run.run_id)
    assert stored.metadata["verification"]["accepted"] is True
    assert sum(event.event_type == "verification.rechecked" for event in stored.events) == 1
    assert stored.steps[0].attempt_count == 1


@pytest.fixture
def api(monkeypatch):
    from app.fastapi_routes.domains.agent import agent_routes as routes

    repo = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repo)
    queued = []
    principal = AgentPrincipal(user_id="17", tenant_id="7")
    monkeypatch.setattr(routes, "AgentOrchestrator", lambda: orchestrator)
    monkeypatch.setattr(routes, "get_agent_run_repository", lambda: repo)
    monkeypatch.setattr(routes, "_enqueue_run", lambda run, **kwargs: queued.append(run.run_id))
    monkeypatch.setattr(
        routes,
        "_run_response",
        lambda run, **kwargs: {"success": True, "data": run.to_dict()},
    )
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_agent_principal] = lambda: principal
    with TestClient(app) as client:
        yield client, repo, queued, app


@pytest.mark.parametrize("method,suffix", [("get", "verification"), ("post", "verify")])
@pytest.mark.parametrize(
    "principal",
    [
        AgentPrincipal(user_id="18", tenant_id="7"),
        AgentPrincipal(user_id="17", tenant_id="8"),
        AgentPrincipal(user_id="17", tenant_id="7", mod_authorization={"mod_id": "other"}),
    ],
)
def test_api_preserves_owner_tenant_and_mod_boundaries(api, method, suffix, principal, readback):
    client, repo, queued, app = api
    run = _run(mod_id="company")
    repo.save(run)
    app.dependency_overrides[require_agent_principal] = lambda: principal
    response = getattr(client, method)(f"/api/agent/runs/{run.run_id}/{suffix}")
    assert response.status_code == 403
    assert not readback and not queued


def test_api_returns_not_verified_for_legacy_run(api):
    client, repo, queued, _ = api
    run = _run()
    run.tool_calls[0].metadata.clear()
    repo.save(run)
    response = client.get(f"/api/agent/runs/{run.run_id}/verification")
    assert response.status_code == 200
    assert response.json()["data"]["verification"]["status"] == "not_verified"
    assert not queued


def test_api_only_requeues_finalization_of_already_completed_actions(api, readback):
    client, repo, queued, _ = api
    run = _run()
    repo.save(run)
    response = client.post(f"/api/agent/runs/{run.run_id}/verify")
    assert response.status_code == 200, response.text
    assert response.json()["verification"]["accepted"] is True
    assert repo.get(run.run_id).status == "queued"
    assert queued == [run.run_id]
    assert repo.get(run.run_id).steps[0].attempt_count == 1
    assert len(readback) == 1
    finished = AgentOrchestrator(repository=repo).execute_dispatched_run(run.run_id)
    assert finished.status == "completed", finished.to_dict()
    assert len(finished.tool_calls) == 1
    assert finished.steps[0].attempt_count == 1
    assert len(readback) == 1


def test_api_does_not_dispatch_remaining_business_actions(api, readback):
    client, repo, queued, _ = api
    run = _run()
    run.steps.append(
        AgentStep(
            node_id="write",
            tool_id="customers",
            action="delete",
            params={"id": 9},
            risk="high",
        )
    )
    repo.save(run)
    response = client.post(f"/api/agent/runs/{run.run_id}/verify")
    assert response.status_code == 200, response.text
    assert response.json()["verification"]["accepted"] is True
    assert repo.get(run.run_id).steps[-1].status == "pending"
    assert repo.get(run.run_id).status == "blocked"
    assert not queued


def test_api_failed_readback_never_requeues_execution(api, monkeypatch):
    client, repo, queued, _ = api
    run = _run()
    repo.save(run)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.verification_readback.verify_independent_result",
        lambda **kwargs: {
            "status": "inconclusive",
            "code": "source_unavailable",
            "checks": [],
        },
    )
    response = client.post(f"/api/agent/runs/{run.run_id}/verify")
    assert response.status_code == 200, response.text
    assert response.json()["verification"]["accepted"] is False
    assert repo.get(run.run_id).status == "blocked"
    assert not queued


def test_api_mixed_receipts_only_observes_completed_action_without_requeue(api, readback):
    client, repo, queued, _ = api
    run = _run()
    _add_failed_read(run)
    repo.save(run)
    before = repo.get(run.run_id)

    response = client.post(f"/api/agent/runs/{run.run_id}/verify")

    assert response.status_code == 200, response.text
    assert response.json()["verification"]["accepted"] is False
    assert response.json()["verification"]["independently_verified_steps"] == 1
    result = repo.get(run.run_id)
    assert result.status == "blocked"
    assert result.tool_calls[1].to_dict() == before.tool_calls[1].to_dict()
    assert result.steps[0].attempt_count == result.steps[1].attempt_count == 1
    assert safe_continuation_error(result) == ""
    assert len(readback) == 1
    assert not queued


@pytest.mark.parametrize("storage", ["sql", "memory"])
@pytest.mark.parametrize("effect", ["original_step", "unbound_dispatch"])
@pytest.mark.parametrize("acknowledged_pending", [False, True])
def test_unknown_queue_settles_only_exact_verified_pending_effects(
    tmp_path, monkeypatch, readback, storage, effect, acknowledged_pending
):
    from app.application.agent_orchestrator import run_repository, task_execution_repository
    from app.domain.task_lifecycle.adapters import execution_requeue_allowed

    engine = None
    if storage == "sql":
        engine = create_engine(f"sqlite:///{tmp_path / 'settlement.sqlite'}")
        factory = sessionmaker(bind=engine)
        repository = SQLAlchemyAgentRunRepository(session_factory=factory)
        queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    else:
        repository = InMemoryAgentRunRepository()
        queue = task_execution_repository.InMemoryTaskExecutionRepository()
        monkeypatch.setattr(run_repository, "get_agent_run_repository", lambda: repository)
        monkeypatch.setattr(
            task_execution_repository, "get_task_execution_repository", lambda: queue
        )
    run = _run(status="running")
    run.metadata["execution"] = {"state": "active"}
    if acknowledged_pending:
        run.steps[0].output = {
            "success": False,
            "execution_state": "pending",
            "request_id": "original",
        }
        run.tool_calls[0].output = copy.deepcopy(run.steps[0].output)
        spec = ToolActionSpecV2(
            tool_id=run.steps[0].tool_id,
            action=run.steps[0].action,
            read_only=True,
            idempotent=True,
            output_schema={
                "type": "object",
                "required": ["success"],
                "properties": {"success": {"type": "boolean"}},
            },
        )
        freeze_verification_contract(
            run, run.steps[0], run.tool_calls[0], spec, run.metadata["runtime_context"]
        )
        bind_execution_receipt(run.tool_calls[0])
        run.metadata.update(non_retryable=True, recovery={"state": "result_pending"})
    repository.save(run)
    queue.enqueue(run)
    queue.claim("old-worker", lease_seconds=60)
    key = run.steps[0].step_id if effect == "original_step" else "unbound-dispatch"
    queue.mark_open_effect(run.run_id, key)
    queue.finish(run.run_id, "old-worker", "failed", error_code="needs_verification")
    before = queue.get(run.run_id)
    assert before.state == "unknown"
    original = repository.get(run.run_id)
    try:
        result = reverify_run(repository, run.run_id)
        after = queue.get(run.run_id)
        assert result.run_id == run.run_id
        assert result.steps[0].attempt_count == 1
        assert result.tool_calls[0].call_id == original.tool_calls[0].call_id
        assert result.tool_calls[0].output == original.tool_calls[0].output
        assert after.execution_count == before.execution_count
        assert len(readback) == 1
        if effect == "original_step" and acknowledged_pending:
            assert after.state == "blocked"
            assert after.last_error_code == "result_verified"
            assert queue.lifecycle(run.run_id)["effects"] == []
            assert verification_can_finalize(result)
            assert execution_requeue_allowed(after.state)
        else:
            assert after.state == "unknown"
            assert queue.lifecycle(run.run_id)["effects"] == [key]
            assert not verification_can_finalize(result)
            assert not execution_requeue_allowed(after.state, retryable=True)
    finally:
        if engine is not None:
            engine.dispose()
