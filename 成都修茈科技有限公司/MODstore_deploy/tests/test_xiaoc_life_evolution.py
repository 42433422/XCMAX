"""Original SQL transactions, Retort approvals and life feedback stay connected."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from modstore_server import retort_evolution as retort
from modstore_server import retort_github_workspace as workspace
from modstore_server import strategic_portfolio as portfolio
from modstore_server import xiaoc_life_evolution as evolution
from modstore_server import xiaoc_life_reconciliation as reconciliation
from modstore_server import xiaoc_life_runtime as runtime
from modstore_server import xiaoc_life_store as life
from modstore_server.models import IncidentEvent, RetortEvolutionRun
from modstore_server.xiaoc_life_cognition import cognition_messages
from modstore_server.xiaoc_life_policy import LifePolicyError, LifeUpdate
from tests import test_strategic_company_resources as company
from tests.test_strategic_portfolio import limits
from tests.test_xiaoc_life_runtime import ports as ports_fixture

database = company.database
configured = company.configured
ports = ports_fixture


@pytest.fixture
def reflection(configured, tmp_path, monkeypatch):
    from modstore_server import (
        retort_customer_feedback,
        retort_training_candidates,
        strategic_remote_bridge,
    )

    for module in (
        life,
        reconciliation,
        retort,
        workspace,
        retort_customer_feedback,
        retort_training_candidates,
        strategic_remote_bridge,
    ):
        monkeypatch.setattr(module, "get_session_factory", lambda: configured)
    monkeypatch.setattr(retort, "get_engine", lambda: configured.kw["bind"])
    monkeypatch.setenv(
        "MODSTORE_RETORT_CHECKPOINT_DSN", "sqlite:///" + str(tmp_path / "checkpoints.sqlite")
    )
    monkeypatch.setenv("MODSTORE_GITHUB_REPOSITORY", "example/product")
    monkeypatch.setenv("DEVFLEET_FORCE_OPENCODE", "1")
    monkeypatch.setenv("MODSTORE_PARA_PLATFORM_POOL", "1")
    template = {
        "name": "原任务恢复核验",
        "criterion_ids": ["shared-engine-B2"],
        "container_image": "example/test@sha256:" + "c" * 64,
        "checks": [
            {
                "id": "restore",
                "criterion_ids": ["shared-engine-B2"],
                "files": {"check.py": "b" * 64},
                "argv": ["python", "check.py"],
                "timeout_seconds": 10,
            }
        ],
        "life_reflection": {
            "owner_id": 7,
            "goal": "验证原持久任务恢复，不重复执行。",
            "provider": "openai",
            "model": "model",
        },
    }
    path = tmp_path / "protocols.json"
    path.write_text(json.dumps({"restore": template}))
    monkeypatch.setenv("MODSTORE_RETORT_PROTOCOLS", str(path))
    calls = []

    def github(method, route, body=None):
        calls.append((method, route, body))
        if method == "GET" and route.endswith("/commits/main"):
            return {"sha": "a" * 40}
        if method == "POST" and route.endswith("/issues"):
            return {"number": 41}
        raise AssertionError((method, route))

    monkeypatch.setattr("modstore_server.customer_ticket_github.github", github)
    monkeypatch.setattr(workspace, "github", github)
    tariffs = [{**limits()["tariffs"][0], "provider": "openai"}]
    company_id = company.budget(configured, tariffs=tariffs)
    life.update_settings(
        LifeUpdate(
            expected_revision=1,
            level=6,
            policy={
                "daily_token_limit": 1000000,
                "authorization_expires_at": (life.utcnow() + timedelta(days=1)).isoformat(),
                "retort_template_id": "restore",
                "employee_id": "test-qa-runner",
                "portfolio_limits": limits(company_budget_id=company_id, tariffs=tariffs),
            },
        ),
        actor_user_id=7,
    )
    claim = life.claim_cycle(domain="reflection", reserve_tokens=0)
    goal = {
        "id": "g-reflection",
        "domain": "reflection",
        "title": "PRIVATE_CUSTOMER 改进建议",
        "description": "PRIVATE_FAILURE_TEXT",
        "evidence_refs": ["receipt:original-failure"],
        "status": "proposed",
    }
    return configured, claim, goal, calls, path


def finish(claim, goal):
    return life.finish_cycle(
        claim,
        status="completed",
        summary="形成原改进提案",
        actual_tokens=0,
        evidence_refs=goal["evidence_refs"],
        goals=[goal],
    )


def approve_original(request_id):
    snapshot = retort.advance_run(request_id)
    assert snapshot["status"] == "awaiting_dispatch_approval"
    return retort.advance_run(
        request_id,
        approval={"approved": True, "actor_id": 7, "digest": snapshot["pending"][0]["digest"]},
    )


def test_reflection_reuses_original_retort_and_keeps_private_context_out_of_public_plan(
    reflection, monkeypatch
):
    factory, claim, goal, calls, _ = reflection
    linked = evolution.propose(claim, goal)
    assert linked["retort_request_id"] == evolution.propose(claim, linked)["retort_request_id"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(RetortEvolutionRun)) == 1
    assert len(calls) == 1
    finish(claim, linked)
    # Even if an auxiliary optimizer is configured, source-only proposal creation
    # cannot spend a second model budget before engineering authorization.
    monkeypatch.setenv("MODSTORE_RETORT_RSI_PROTOCOL", "/must-not-be-read")
    state = retort.advance_run(linked["retort_request_id"])
    assert state["status"] == "awaiting_dispatch_approval"
    assert "PRIVATE_CUSTOMER" in json.dumps(state["plan"]["private_life_reflection"])
    assert "PRIVATE_" not in state["plan"]["public_body"]
    assert not [call for call in calls if call[0] == "POST"]
    assert state["optimization"]["status"] == "awaiting_approved_experiment_budget"


def test_original_task_and_goal_rollback_together_on_failed_state_write(reflection, monkeypatch):
    factory, claim, goal, *_ = reflection

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("persist failed")

    monkeypatch.setattr(life, "_event", unavailable)
    with pytest.raises(RuntimeError, match="persist failed"):
        evolution.propose(claim, goal)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(RetortEvolutionRun)) == 0
    assert life.read_state()["goals"] == []


def test_private_reflection_reaches_only_original_approved_isolated_employee_prompt(reflection):
    from modstore_server import retort_customer_feedback
    from modstore_server.dot_ticket_dispatch import DoltIncidentContractError, _incident_prompt
    from modstore_server.para_execution_isolation import (
        HEADER_ONLY_PLATFORM_PROFILE,
        feedback_execution_kind,
    )

    factory, claim, goal, *_ = reflection
    linked = evolution.propose(claim, goal)
    approve_original(linked["retort_request_id"])
    with factory() as session:
        row = session.get(RetortEvolutionRun, linked["retort_request_id"])
        protocol, effects = json.loads(row.protocol_json), json.loads(row.effects_json)
        effects.update(
            run_id=99,
            model_allocation={
                "status": "admitted",
                "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
            },
        )
        row.effects_json = json.dumps(effects)
        payload = {
            "retort_run_id": row.id,
            "user_id": row.user_id,
            "github_workspace": {
                "retort_run_id": row.id,
                "request_id": row.id,
                "repository": protocol["repository"],
                "source_sha": protocol["source_sha"],
                "run_id": 99,
                "issue_number": effects["issue_number"],
            },
        }
        event = IncidentEvent(
            event_type="ops.retort.evolution",
            source="retort",
            fingerprint="retort:" + row.id,
            payload_json=json.dumps(payload),
        )
        session.add(event)
        session.flush()
        row.event_id = event.id
        session.flush()
        private = retort_customer_feedback.private_execution_context(session, event.id, payload)
        assert private["intent"] == "evidence_linked_life_reflection"
        assert "PRIVATE_FAILURE_TEXT" in private["reproduction"]
        assert feedback_execution_kind(effects) == "life_reflection_repair"
        contract = {
            "role": "fix",
            "source": payload,
            "handoffs": [],
            "review": {},
            "customer_feedback": private,
            "requires_isolated_execution": True,
            "execution_isolation": HEADER_ONLY_PLATFORM_PROFILE,
        }
        assert "PRIVATE_FAILURE_TEXT" in _incident_prompt(contract, {}, "opencode")
        with pytest.raises(DoltIncidentContractError):
            _incident_prompt(contract, {}, "cursor")
        assert "PRIVATE_" not in workspace.public_task_body(effects)
        with pytest.raises(LifePolicyError, match="身份"):
            retort_customer_feedback.private_execution_context(session, event.id + 1, payload)
        effects["plan"]["private_life_reflection"]["private_goal"]["description"] = "forged"
        row.effects_json = json.dumps(effects)
        with pytest.raises(LifePolicyError, match="批准"):
            retort_customer_feedback.private_execution_context(session, event.id, payload)


@pytest.mark.parametrize("change", [{"paused": True}, {"level": 5}])
def test_revoked_life_claim_cannot_create_retort(reflection, change):
    factory, claim, goal, *_ = reflection
    life.update_settings(
        LifeUpdate(expected_revision=life.read_state()["revision"], **change), actor_user_id=7
    )
    with pytest.raises(LifePolicyError, match="授权已变化"):
        evolution.propose(claim, goal)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(RetortEvolutionRun)) == 0


def test_original_owner_and_request_binding_cannot_be_replaced(reflection):
    _, claim, goal, *_ = reflection
    linked = evolution.propose(claim, goal)
    with pytest.raises(LifePolicyError, match="责任人"):
        evolution.propose({**claim, "owner_user_id": 8}, linked)
    with pytest.raises(LifePolicyError, match="binding"):
        life._merge([linked], [{**linked, "retort_request_id": "changed"}], "id", 100)
    finish(claim, linked)
    with pytest.raises(LifePolicyError, match="原管理员"):
        life.update_settings(
            LifeUpdate(
                expected_revision=life.read_state()["revision"], policy={"daily_cycle_limit": 8}
            ),
            actor_user_id=8,
        )


def test_dispatch_approval_reenters_existing_company_budget_once_and_never_autoruns(
    reflection, monkeypatch
):
    factory, claim, goal, calls, _ = reflection
    linked = evolution.propose(claim, goal)
    finish(claim, linked)
    approve_original(linked["retort_request_id"])
    evolution.reconcile()
    assert runtime._cycle_reservation(life.read_state(), "reflection") == 0
    life.wake(actor_user_id=7, expected_revision=life.read_state()["revision"])
    second = life.claim_cycle(domain="reflection", reserve_tokens=0)
    observed = evolution.pending_budget(second["state"], "reflection")
    assert observed["id"] == goal["id"]
    budgeted = evolution.propose_budget(second, observed)
    assert evolution.propose_budget(second, observed)["decision_id"] == budgeted["decision_id"]
    state = portfolio.portfolio_status(budgeted["decision_id"])
    assert state["status"] == "proposed" and state.get("tasks", {}) == {}
    original = state["opportunities"][0]["input_data"]["remote_execution"]
    assert original["original_request_id"] == linked["retort_request_id"]
    assert original["kind"] == "github_opencode_workspace"
    assert original["life_lease"]["mode"] == "persistent_phases"
    assert "PRIVATE_" not in state["opportunities"][0]["task"]
    assert len([call for call in calls if call[0] == "POST"]) == 1
    # Runner cannot turn the original Retort approval into unbudgeted execution.
    with factory() as session:
        row = session.get(RetortEvolutionRun, linked["retort_request_id"])
        protocol, effects = json.loads(row.protocol_json), json.loads(row.effects_json)
    result = workspace._ensure_runner(linked["retort_request_id"], protocol, effects)
    assert result["model_allocation"]["reason"] == "strategic_company_budget_binding_required"


def test_lost_budget_response_resumes_frozen_original_proposal(reflection, monkeypatch):
    _, claim, goal, *_ = reflection
    linked = evolution.propose(claim, goal)
    approve_original(linked["retort_request_id"])
    original = portfolio.create_portfolio_proposal
    created = []

    def lost(**kwargs):
        created.append(original(**kwargs))
        raise RuntimeError("receipt lost")

    monkeypatch.setattr(portfolio, "create_portfolio_proposal", lost)
    with pytest.raises(RuntimeError, match="receipt lost"):
        evolution.propose_budget(claim, linked)
    monkeypatch.setattr(portfolio, "create_portfolio_proposal", original)
    retried = evolution.propose_budget(claim, linked)
    assert retried["decision_id"] == created[0]["decision"]["decision_id"]


def test_approved_life_retort_reuses_original_workspace_lease_without_another_model_call(
    reflection, monkeypatch
):
    from modstore_server import llm_key_resolver
    from modstore_server import strategic_portfolio_runtime as executor
    from modstore_server import strategic_remote_bridge as remote
    from modstore_server import strategic_workspace_bridge as bridge

    _, claim, goal, calls, _ = reflection
    linked = evolution.propose(claim, goal)
    approve_original(linked["retort_request_id"])
    budgeted = evolution.propose_budget(claim, linked)
    finish(claim, budgeted)
    original = portfolio.portfolio_status(budgeted["decision_id"])
    portfolio.authorize_portfolio(
        budgeted["decision_id"],
        owner_user_id=7,
        actor="admin:7",
        expected_proposal_sha256=original["proposal_sha256"],
    )
    monkeypatch.setenv("MODSTORE_STRATEGIC_WORKSPACES_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_PARA_DISPATCH_TOKEN_SHA256", "d" * 64)
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _provider: "fixture-key")
    monkeypatch.setattr(llm_key_resolver, "platform_base_url", lambda _provider: None)
    monkeypatch.setattr(
        executor,
        "_business_outcome",
        lambda *_args, **_kwargs: {"status": "unknown", "revenue_cents": None},
    )
    life.wake(actor_user_id=7, expected_revision=life.read_state()["revision"])
    claim = life.claim_cycle(domain="reflection", reserve_tokens=100000)
    with life.life_execution_scope(claim):
        ports = runtime.CyclePorts(claim)
        result = asyncio.run(ports.advance_portfolio(ports.approved_portfolio()))
        assert result["status"] == "awaiting_worker"
        ports.finish(result)
    request, _, _ = remote.read_request(linked["retort_request_id"])
    assert request["binding"]["receipt_id"] == linked["retort_request_id"]
    assert request["binding"]["decision_id"] == budgeted["decision_id"]
    assert request["binding"]["life_scope"]["cycle_id"] == claim["cycle_id"]
    assert bridge.ready(linked["retort_request_id"]) is True
    assert life.read_state()["activity"]["status"] == "waiting"
    assert len([call for call in calls if call[0] == "POST"]) == 1


def test_false_completed_retort_stays_unknown_then_verified_delivery_returns_to_next_prompt(
    reflection,
):
    factory, claim, goal, calls, _ = reflection
    linked = evolution.propose(claim, goal)
    finish(claim, linked)
    life.update_settings(
        LifeUpdate(expected_revision=life.read_state()["revision"], paused=True), actor_user_id=7
    )
    with factory() as session:
        row = session.get(RetortEvolutionRun, linked["retort_request_id"])
        row.status = "completed"
        row.snapshot_json = json.dumps(
            {"status": "completed", "delivery": {"status": "deployment_verified"}}
        )
        session.commit()
    assert evolution.reconcile() == 1
    assert life.read_state()["goals"][0]["status"] == "evolution_evidence_incomplete"
    with factory() as session:
        row = session.get(RetortEvolutionRun, linked["retort_request_id"])
        protocol = json.loads(row.protocol_json)
        verification = {
            "status": "checks_passed",
            "request_id": row.id,
            "protocol_digest": protocol["protocol_digest"],
            "run_id": "41",
            "target_sha": "d" * 40,
            "evidence_archive": {"sha256": "b" * 64},
        }
        from modstore_server.integrations.repository_packages import load_repository_module

        contract = load_repository_module("retort_engine.evolution_contract")
        row.effects_json = json.dumps(
            {**json.loads(row.effects_json), "verification": verification, "run_id": 41}
        )
        row.snapshot_json = json.dumps(
            {
                "status": "completed",
                "verification": verification,
                "approval": {"approved": True, "digest": contract.digest(verification)},
                "delivery": {
                    "status": "deployment_verified",
                    "candidate_sha": "d" * 40,
                    "receipt": {"verified": True},
                    "release_sha": "e" * 40,
                    "identity": {"git_sha": "e" * 40, "artifact_sha256": "f" * 64},
                },
            }
        )
        session.commit()
    assert evolution.reconcile() == 1
    assert evolution.reconcile() == 0
    state = life.read_state()
    assert state["goals"][0]["status"] == "evolution_delivery_verified"
    messages, refs = cognition_messages(state, "reflection", evolution.feedback_facts(state))
    feedback = json.loads(messages[1]["content"])["observations"][0]["evolution_feedback"]
    assert feedback["terminal_verified"] is True and feedback["impact_status"] == "not_measured"
    assert any(ref.startswith("evolution-outcome:") for ref in refs)
    assert not [call for call in calls if call[0] == "POST"]
    # An unchanged original receipt must still restore its stronger status after
    # the portfolio projection updates; it must not create another observation.
    life._mutate(lambda data, _session: data["goals"][0].update(status="execution_verified"))
    assert evolution.reconcile() == 0
    assert life.read_state()["goals"][0]["status"] == "evolution_delivery_verified"
    with factory() as session:
        row = session.get(RetortEvolutionRun, linked["retort_request_id"])
        row.user_id = 8
        session.commit()
    assert evolution.reconcile() == 1
    unknown = life.read_state()["goals"][0]
    assert unknown["status"] == "evolution_evidence_incomplete"
    assert unknown["evolution_outcome"]["metrics"]["terminal_verified"] is False


def test_rejected_effect_requires_actual_rollback_receipt(reflection):
    factory, claim, goal, *_ = reflection
    linked = evolution.propose(claim, goal)
    finish(claim, linked)
    with factory() as session:
        row = session.get(RetortEvolutionRun, linked["retort_request_id"])
        row.status = "customer_impact_rejected"
        row.snapshot_json = json.dumps(
            {"status": row.status, "impact": {"status": "customer_impact_rejected"}}
        )
        session.commit()
    evolution.reconcile()
    assert life.read_state()["goals"][0]["status"] == "waiting_recovery"
    with factory() as session:
        row = session.get(RetortEvolutionRun, linked["retort_request_id"])
        snapshot = json.loads(row.snapshot_json)
        snapshot["recovery"] = {"status": "rollback_verified"}
        row.snapshot_json = json.dumps(snapshot)
        session.commit()
    evolution.reconcile()
    observed = life.read_state()["goals"][0]["evolution_outcome"]
    assert observed["status"] == "evolution_failed"
    assert observed["metrics"]["recovery_status"] == "rollback_verified"


def test_runtime_consumes_customer_value_and_original_evolution_feedback(ports, monkeypatch):
    store, calls, *_ = ports
    monkeypatch.setattr(
        "modstore_server.strategy_planner.collect_context",
        lambda: {
            "customer_value": {
                "status": "unknown",
                "source_owner": "unavailable",
                "observed_at": "2026-11-21T14:00:00+00:00",
                "private_customers": ["SECRET"],
                "verified_paid_count": 0,
            }
        },
    )
    asyncio.run(runtime.tick_async())
    observed = json.loads(calls[0]["messages"][1]["content"])["observations"][0]
    assert observed["ref"].startswith("company:customer_value:")
    assert "unavailable" in observed["text"]
    assert "SECRET" not in observed["text"] and "verified_paid_count" not in observed["text"]
