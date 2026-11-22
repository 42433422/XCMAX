"""Business receipts, real run SQL CAS and governed JSON memory observations."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.approval_grant import _params_hash
from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_context import apply_task_context
from app.application.agent_task_context import scoped_personal_memory_id
from app.application.enterprise_cognition.outcomes import OutcomeService, observe_terminal_run
from app.domain.shared_services import user_memory_service

NOW = datetime(2026, 11, 21, 15, tzinfo=UTC)


def at(seconds):
    return (NOW + timedelta(seconds=seconds)).isoformat()


def snapshot(value, *, seconds=-2, **changes):
    state = {"remaining_quantity": str(value), "quantity_unit": "箱"}
    digest = canonical_hash(state)
    result = {
        "tenant_id": "2",
        "actor_id": "7",
        "mod_id": "sales",
        "entity_type": "order",
        "entity_id": "17",
        "source": "sales_orders",
        "source_version": "sha256:" + digest,
        "freshness": "fresh",
        "observed_at": at(seconds),
        "expires_at": at(seconds + 60),
        "state": state,
        "evidence": [
            {
                "source": "sales_orders",
                "table": "sales_orders",
                "row_id": "17",
                "tenant_id": "2",
                "actor_id": "7",
                "mod_id": "sales",
                "observed_at": at(seconds),
                "content_sha256": digest,
                "version_kind": "content_sha256",
            }
        ],
    }
    result.update(changes)
    return result


def completed_run():
    goal = {
        "goal_id": "fulfil-order-17",
        "objective": "减少订单17未交数量",
        "entity_type": "order",
        "entity_id": "17",
        "metric": "remaining_quantity",
        "unit": "箱",
        "direction": "decrease",
        "target": "0",
        "tenant_id": 2,
        "actor_id": "7",
        "mod_id": "sales",
        "source": {"kind": "user_goal", "asserted_by": "7"},
    }
    goal["binding_sha256"] = canonical_hash(goal)
    goal["created_at"] = at(-60)
    context = {
        "tenant_id": "2",
        "user_id": "7",
        "mod_id": "sales",
        "task_id": "task-order-17",
        "conversation_id": "conversation-1",
        "_mod_authorization": {"mod_id": "sales"},
        "enterprise_cognition": {
            "goal": goal,
            "baseline": snapshot(10, seconds=-30),
            "bound_at": at(-25),
        },
    }
    run = AgentRun(user_id="7", message="处理订单17", status="completed")
    run.metadata["runtime_context"] = context
    apply_task_context(run, context)
    step = AgentStep(
        node_id="write",
        tool_id="sales",
        action="deliver",
        params={"order_id": "17"},
        risk="high",
        status="completed",
        output={"success": True, "order_id": 17},
        started_at=at(-20),
        finished_at=at(-10),
    )
    run.steps = [step]
    context["enterprise_cognition"]["action_bindings"] = [
        {
            "node_id": step.node_id,
            "entity_type": "order",
            "entity_id": "17",
            "tool_id": step.tool_id,
            "action": step.action,
            "selector": "order_id",
            "params_sha256": canonical_hash(step.params),
        }
    ]
    run.tool_calls = [
        ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=step.params,
            status="completed",
            output=copy.deepcopy(step.output),
            permission="sales.manage",
            started_at=at(-20),
            finished_at=at(-10),
        )
    ]
    run.metadata["approval_receipt"] = {
        "task_id": "task-order-17",
        "step_id": step.step_id,
        "tool_id": step.tool_id,
        "action": step.action,
        "approved_by": "9",
        "approval_request_id": "approval-17",
    }
    approval = run.add_event(
        "step.approved",
        "审批通过",
        {
            "task_id": "task-order-17",
            "step_id": step.step_id,
            "node_id": step.node_id,
            "tool_id": step.tool_id,
            "action": step.action,
            "approved_by": "9",
        },
    )
    approval.created_at = at(-22)
    run.metadata["plan"] = {
        "metadata": {"enterprise_cognition": copy.deepcopy(context["enterprise_cognition"])}
    }
    run.metadata["plan_sha256"] = canonical_hash(run.metadata["plan"])
    approval.data.update(params_sha256=_params_hash(step), plan_sha256=run.metadata["plan_sha256"])
    return run


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "runs.sqlite"))
    sessions = sessionmaker(engine, expire_on_commit=False)
    repository = SQLAlchemyAgentRunRepository(session_factory=sessions)
    monkeypatch.setattr(user_memory_service.UserMemoryStore, "_instance", None)
    monkeypatch.setattr(user_memory_service.UserMemoryService, "_instance", None)
    monkeypatch.setenv("XCAGI_USER_MEMORY_JSON_PATH", str(tmp_path / "memories.json"))
    memory = user_memory_service.UserMemoryService()
    calls = []
    state = {"after": snapshot(2)}

    def read(kind, entity_id, **kwargs):
        calls.append((kind, entity_id, kwargs))
        return copy.deepcopy(state["after"])

    projection = SimpleNamespace(get=read)
    service = OutcomeService(
        repository=repository, projection=projection, memory_service=memory, clock=lambda: NOW
    )
    result = SimpleNamespace(
        repo=repository,
        sessions=sessions,
        memory=memory,
        state=state,
        projection=projection,
        service=service,
        calls=calls,
        owner=scoped_personal_memory_id({"tenant_id": "2", "actor_id": "7", "mod_id": "sales"}),
        run=completed_run(),
    )
    yield result
    engine.dispose()


def evaluate(runtime, **scope):
    return runtime.service.evaluate(
        runtime.run.run_id, **({"tenant_id": "2", "actor_id": "7", "mod_id": "sales"} | scope)
    )


def test_observation_keeps_business_authority_and_proposes_pending_memory(runtime):
    runtime.repo.save(runtime.run)
    original = runtime.repo.get(runtime.run.run_id)
    report = evaluate(runtime)

    assert report["status"] == "improved" and report["delta"] == "-8"
    assert report["target_met"] is False
    assert report["attribution"] == "unproven" and report["business_success"] is None
    assert report["memory_status"] == "pending" and report["memory_requires_confirmation"]
    assert runtime.calls == [
        (
            "order",
            "17",
            {"tenant_id": "2", "actor_id": "7", "mod_id": "sales", "force_refresh": True},
        )
    ]
    after = runtime.repo.get(runtime.run.run_id)
    assert after.metadata == original.metadata and after.tool_calls == original.tool_calls
    assert (
        after.final_output == original.final_output
        and len(after.events) == len(original.events) + 1
    )
    memories = runtime.memory.list_memories(runtime.owner)
    assert len(memories) == 1
    assert memories[0]["eligible_for_planner"] is False
    assert memories[0]["value"]["before"]["value"] == "10"
    assert (
        memories[0]["evidence"][0]["actions"][0]["approval_event_id"] == original.events[0].event_id
    )


def test_original_human_confirmation_does_not_fabricate_or_block_business_evidence(runtime):
    from app.application.agent_orchestrator.clarification import apply_plan_confirmation

    control = AgentStep(
        "confirmation", "clarify", "ask", {"question": "Continue?"}, status="waiting_user"
    )
    runtime.run.steps.append(control)
    runtime.run.status = "waiting_user"
    apply_plan_confirmation(runtime.run, step_id=control.step_id, confirmed=True)
    runtime.run.status = "completed"
    runtime.repo.save(runtime.run)
    result = evaluate(runtime)
    assert result["observation_verified"] is True and result["memory_status"] == "pending"
    actions = result["evidence"][0]["actions"]
    assert len(actions) == 1 and actions[0]["tool_id"] == "sales"
    assert len(runtime.repo.get(runtime.run.run_id).tool_calls) == 1


@pytest.mark.parametrize("after,expected", [(10, "no_change"), (12, "worsened"), (0, "improved")])
def test_unchanged_and_worse_are_never_promoted_to_success(runtime, after, expected):
    runtime.state["after"] = snapshot(after)
    runtime.repo.save(runtime.run)
    report = evaluate(runtime)
    assert report["status"] == expected and report["business_success"] is None
    assert report["memory_status"] == "pending"


@pytest.mark.parametrize("scope", [{"tenant_id": "3"}, {"actor_id": "8"}, {"mod_id": "other"}])
def test_foreign_scopes_do_not_read_entities_or_write_memory(runtime, scope):
    runtime.repo.save(runtime.run)
    result = evaluate(runtime, **scope)
    assert result["reason_code"] == "run_not_accessible"
    assert runtime.calls == [] and runtime.memory.list_memories(runtime.owner) == []


@pytest.mark.parametrize(
    "case",
    [
        "missing_call",
        "missing_output",
        "failed_call",
        "call_params",
        "missing_approval",
        "approval_actor",
        "approval_task",
        "approval_params_digest",
        "approval_plan_digest_missing",
        "approval_plan_digest_mismatch",
        "call_before_baseline",
        "incomplete_run",
        "unknown_effect",
        "nested_failure",
        "no_baseline",
        "invalid_goal",
        "changed_baseline",
        "different_tenant",
        "different_mod",
        "different_entity",
        "missing_metric",
        "boolean_metric",
        "nonfinite_metric",
        "unit_mismatch",
        "expired_after",
        "after_predates_action",
        "unknown_source",
        "same_version_different_value",
        "evidence_mismatch",
    ],
)
def test_incomplete_or_incompatible_evidence_stays_unknown(runtime, case):
    run, state = runtime.run, runtime.state["after"]
    binding = run.metadata["runtime_context"]["enterprise_cognition"]
    if case == "missing_call":
        run.tool_calls = []
    elif case == "missing_output":
        run.tool_calls[0].output = {}
    elif case == "failed_call":
        run.tool_calls[0].status = "failed"
    elif case == "call_params":
        run.tool_calls[0].params = {"order_id": "18"}
    elif case == "missing_approval":
        run.events = []
    elif case == "approval_actor":
        run.metadata["approval_receipt"]["approved_by"] = "8"
    elif case == "approval_task":
        run.events[0].data["task_id"] = "task-other"
    elif case == "approval_params_digest":
        run.events[0].data["params_sha256"] = "c" * 64
    elif case == "approval_plan_digest_missing":
        del run.events[0].data["plan_sha256"]
    elif case == "approval_plan_digest_mismatch":
        run.events[0].data["plan_sha256"] = "c" * 64
    elif case == "call_before_baseline":
        run.tool_calls[0].started_at = at(-35)
    elif case == "incomplete_run":
        run.status = "waiting_user"
    elif case == "unknown_effect":
        run.tool_calls[0].output["requires_reconciliation"] = True
    elif case == "nested_failure":
        run.tool_calls[0].output["data"] = {"result": {"success": False, "message": "业务写入失败"}}
    elif case == "no_baseline":
        del binding["baseline"]
    elif case == "invalid_goal":
        binding["goal"]["target"] = "900"
    elif case == "changed_baseline":
        binding["baseline"] = snapshot(100, seconds=-30)
    elif case == "different_tenant":
        state["tenant_id"] = "3"
    elif case == "different_mod":
        state["mod_id"] = "other"
    elif case == "different_entity":
        state["entity_id"] = "18"
    elif case == "missing_metric":
        del state["state"]["remaining_quantity"]
    elif case == "boolean_metric":
        state["state"]["remaining_quantity"] = True
    elif case == "nonfinite_metric":
        state["state"]["remaining_quantity"] = "NaN"
    elif case == "unit_mismatch":
        state["state"]["quantity_unit"] = "个"
    elif case == "expired_after":
        state["expires_at"] = at(-1)
    elif case == "after_predates_action":
        state["observed_at"] = state["evidence"][0]["observed_at"] = at(-15)
    elif case == "unknown_source":
        state["freshness"] = "unknown"
    elif case == "same_version_different_value":
        state["source_version"] = binding["baseline"]["source_version"]
        state["evidence"][0]["content_sha256"] = state["source_version"].removeprefix("sha256:")
    elif case == "evidence_mismatch":
        state["evidence"][0]["row_id"] = "18"
    runtime.repo.save(run)
    report = evaluate(runtime)
    assert report["status"] == "unknown", (case, report)
    assert report["business_success"] is None and report["memory_status"] == "not_written"
    assert runtime.memory.list_memories(runtime.owner) == []
    assert not any(
        event.event_type == "enterprise.outcome_observed"
        for event in runtime.repo.get(run.run_id).events
    )


def test_restart_keeps_first_frozen_measurement_and_memory_identity(runtime):
    runtime.repo.save(runtime.run)
    first = evaluate(runtime)
    runtime.state["after"] = snapshot(0, seconds=-1)
    runtime.service.repository = SQLAlchemyAgentRunRepository(session_factory=runtime.sessions)
    runtime.memory._store._repository._memory_cache.clear()
    repeated = evaluate(runtime)
    assert repeated["observation_id"] == first["observation_id"]
    assert repeated["after"]["value"] == "2" and repeated["memory_id"] == first["memory_id"]
    assert repeated["memory_created"] is False
    assert len(runtime.memory.list_memories(runtime.owner)) == 1


def test_memory_commit_ack_loss_retries_the_same_governed_candidate(runtime):
    runtime.repo.save(runtime.run)
    real_propose = runtime.memory.propose_memory_candidate
    failures = [True]

    def lose_ack(*args, **kwargs):
        result = real_propose(*args, **kwargs)
        if failures.pop() if failures else False:
            raise OSError("simulated lost memory acknowledgement")
        return result

    runtime.service.memory_service = SimpleNamespace(
        propose_memory_candidate=lose_ack,
        _store=runtime.memory._store,
        list_memories=runtime.memory.list_memories,
    )
    first = evaluate(runtime)
    assert first["observation_verified"] and first["memory_status"] == "retry_required"
    repeated = evaluate(runtime)
    assert repeated["observation_id"] == first["observation_id"]
    assert repeated["memory_created"] is False and repeated["memory_status"] == "pending"
    assert len(runtime.memory.list_memories(runtime.owner)) == 1


def test_run_commit_ack_loss_reads_back_frozen_event_without_duplicate(runtime, monkeypatch):
    runtime.repo.save(runtime.run)
    save = runtime.repo.save_if_unchanged

    def lose_ack(run, previous):
        assert save(run, previous)
        raise OSError("simulated lost database acknowledgement")

    monkeypatch.setattr(runtime.repo, "save_if_unchanged", lose_ack)
    first, repeated = evaluate(runtime), evaluate(runtime)
    assert first["observation_id"] == repeated["observation_id"]
    assert first["memory_id"] == repeated["memory_id"]
    assert (
        len(
            [
                event
                for event in runtime.repo.get(runtime.run.run_id).events
                if event.event_type == "enterprise.outcome_observed"
            ]
        )
        == 1
    )


def test_concurrent_run_change_cannot_be_overwritten_by_measurement(runtime):
    runtime.repo.save(runtime.run)
    read = runtime.projection.get

    def race(*args, **kwargs):
        latest = runtime.repo.get(runtime.run.run_id)
        previous = copy.deepcopy(latest)
        latest.add_event("audit.note", "concurrent authoritative audit")
        assert runtime.repo.save_if_unchanged(latest, previous)
        return read(*args, **kwargs)

    runtime.projection.get = race
    report = evaluate(runtime)
    assert report["reason_code"] == "run_changed_during_observation"
    assert runtime.memory.list_memories(runtime.owner) == []
    assert runtime.repo.get(runtime.run.run_id).events[-1].event_type == "audit.note"


def test_permission_revocation_stops_even_frozen_memory_retry(runtime):
    runtime.repo.save(runtime.run)
    evaluate(runtime)
    before = runtime.memory.list_memories(runtime.owner)

    def denied(*args, **kwargs):
        raise PermissionError("permission revoked")

    runtime.projection.get = denied
    with pytest.raises(PermissionError):
        evaluate(runtime)
    assert runtime.memory.list_memories(runtime.owner) == before


@pytest.mark.parametrize("operation", ["delete", "correct"])
def test_observation_retry_preserves_user_memory_lifecycle(runtime, monkeypatch, operation):
    runtime.repo.save(runtime.run)
    first = evaluate(runtime)
    # Candidate governance is under test; optional search replica IO is separate.
    monkeypatch.setattr(
        "app.application.user_memory.projections.sync_memory_projection", lambda *args, **kwargs: {}
    )
    if operation == "delete":
        runtime.memory.delete_memory(runtime.owner, first["memory_id"])
    else:
        runtime.memory.correct_memory(
            runtime.owner,
            first["memory_id"],
            key="operator_revised",
            value={"statement": "人工修订观察"},
        )
    saved = runtime.memory.list_memories(runtime.owner)
    repeated = evaluate(runtime)
    assert repeated["memory_id"] == first["memory_id"] and not repeated["memory_created"]
    assert repeated["memory_status"] == ("deleted" if operation == "delete" else "pending")
    assert runtime.memory.list_memories(runtime.owner) == saved


def test_metric_comparison_preserves_decimal_money(runtime):
    binding = runtime.run.metadata["runtime_context"]["enterprise_cognition"]
    goal = binding["goal"]
    goal.update(metric="paid_amount", unit="CNY", direction="increase", target="0.30")
    goal["binding_sha256"] = canonical_hash(
        {key: value for key, value in goal.items() if key not in {"binding_sha256", "created_at"}}
    )
    for sample, value in [(binding["baseline"], "0.10"), (runtime.state["after"], "0.30")]:
        sample["state"] = {"paid_amount": value, "currency": "CNY"}
        digest = canonical_hash(sample["state"])
        sample["source_version"] = "sha256:" + digest
        sample["evidence"][0]["content_sha256"] = digest
    runtime.run.metadata["plan"]["metadata"]["enterprise_cognition"] = copy.deepcopy(binding)
    runtime.run.metadata["plan_sha256"] = canonical_hash(runtime.run.metadata["plan"])
    runtime.run.events[0].data["plan_sha256"] = runtime.run.metadata["plan_sha256"]
    runtime.repo.save(runtime.run)
    report = evaluate(runtime)
    assert report["delta"] == "0.20" and report["target_met"] is True
    assert report["business_success"] is None


def test_personal_observation_does_not_promote_to_shared_enterprise_memory(runtime):
    runtime.repo.save(runtime.run)
    report = evaluate(runtime)
    assert report["memory_scope"] == "personal"
    assert set(runtime.memory._store._repository._memory_cache) == {runtime.owner}
    other = scoped_personal_memory_id({"tenant_id": "2", "actor_id": "8", "mod_id": "sales"})
    assert runtime.memory.list_memories(other) == []


def test_frozen_conflicting_events_do_not_create_another_memory(runtime):
    runtime.repo.save(runtime.run)
    report = evaluate(runtime)
    current = runtime.repo.get(runtime.run.run_id)
    previous = copy.deepcopy(current)
    conflicting = copy.deepcopy(current.events[-1].data["observation"])
    conflicting["delta"] = "-10"
    current.add_event(
        "enterprise.outcome_observed", "invalid duplicate", {"observation": conflicting}
    )
    assert runtime.repo.save_if_unchanged(current, previous)
    repeated = evaluate(runtime)
    assert repeated["reason_code"] == "frozen_observation_conflict"
    assert len(runtime.memory.list_memories(runtime.owner)) == 1
    assert runtime.memory.list_memories(runtime.owner)[0]["memory_id"] == report["memory_id"]


def test_terminal_hook_skips_unbound_and_incomplete_runs(runtime):
    runtime.run.status = "waiting_user"
    runtime.repo.save(runtime.run)
    assert observe_terminal_run(runtime.run.run_id, repository=runtime.repo) is None
    run = AgentRun(user_id="7", message="ordinary completed task", status="completed")
    runtime.repo.save(run)
    assert observe_terminal_run(run.run_id, repository=runtime.repo) is None
    assert runtime.memory.list_memories(runtime.owner) == []


def test_terminal_hook_authorization_failure_leaves_business_receipt_untouched(runtime):
    runtime.repo.save(runtime.run)
    previous = runtime.repo.get(runtime.run.run_id).to_dict()
    report = observe_terminal_run(runtime.run.run_id, repository=runtime.repo)
    assert report["reason_code"] == "observation_authorization_unavailable"
    assert runtime.repo.get(runtime.run.run_id).to_dict() == previous


def test_terminal_hook_persistence_outage_stays_unknown():
    def unavailable(*args):
        raise OSError("database unavailable")

    report = observe_terminal_run("run-unavailable", repository=SimpleNamespace(get=unavailable))
    assert report["reason_code"] == "terminal_observation_retry_required"
    assert report["memory_status"] == "not_written"
