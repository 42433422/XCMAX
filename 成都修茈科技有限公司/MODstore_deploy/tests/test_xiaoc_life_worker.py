"""A persisted local worker restores one original life lease, never a fresh one."""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as workers
from modstore_server import strategic_portfolio_usage as usage
from modstore_server import xiaoc_life_reconciliation as reconciliation
from modstore_server import xiaoc_life_store as life
from modstore_server.db.identity import User
from modstore_server.db.xiaoc_life import XiaoCLifeState
from modstore_server.xiaoc_life_policy import LifeUpdate
from tests.test_strategic_portfolio import database as database
from tests.test_strategic_portfolio import limits, opportunity, seed_owner


@pytest.fixture
def queued(database, monkeypatch):
    for module in (life, reconciliation):
        monkeypatch.setattr(module, "get_session_factory", lambda: database)
    seed_owner(database)
    life.update_settings(
        LifeUpdate(
            expected_revision=1,
            level=4,
            policy={
                "daily_token_limit": 1_000_000,
                "authorization_expires_at": (life.utcnow() + timedelta(days=1)).isoformat(),
            },
        ),
        actor_user_id=7,
    )
    made = portfolio.create_portfolio_proposal(
        owner_user_id=7,
        goal="Deliver one existing queue task",
        period="xiaoc-life:g1",
        limits=limits(),
        opportunities=[opportunity()],
        idempotency_key="life-queue-g1",
    )
    decision_id = made["decision"]["decision_id"]
    portfolio.authorize_portfolio(
        decision_id,
        owner_user_id=7,
        actor="admin:7",
        expected_proposal_sha256=made["decision"]["decision_payload"]["proposal_sha256"],
    )
    seed = life.claim_cycle(domain="enterprise", reserve_tokens=0)
    life.finish_cycle(
        seed,
        status="completed",
        summary="Observed a sourced task",
        evidence_refs=["source:1"],
        actual_tokens=0,
        goals=[
            {
                "id": "g1",
                "title": "Existing queue",
                "domain": "enterprise",
                "decision_id": decision_id,
                "status": "approved",
                "evidence_refs": ["source:1"],
            }
        ],
    )
    life.wake(actor_user_id=7, expected_revision=life.read_state()["revision"])
    claim = life.claim_cycle(domain="enterprise", reserve_tokens=40_000)
    with life.life_execution_scope(claim):
        life.record_cycle_step(
            claim,
            kind="portfolio",
            details={"decision_id": decision_id, "before_task_ids": [], "before_call_ids": []},
        )
        portfolio.plan_portfolio(decision_id)
        task = workers._claim(decision_id, 7)
        with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
            before_queue = usage.prepare_platform_call("test", "model", [], 10)
            usage.complete_platform_call(
                before_queue, {"usage": {"prompt_tokens": 3, "completion_tokens": 2}}
            )
            binding = usage.bind_portfolio_worker("local-queue:life", owner_user_id=7)
        workers._finish(
            task, {"ok": True, "status": "queued", "worker_receipt_id": "local-queue:life"}, 1
        )
    life.defer_cycle(claim, summary="Waiting for original worker", evidence_refs=["queue:life"])
    assert life.current_life_claim() is None
    assert life.read_state()["budget"]["reserved_tokens"] == 40_000
    return {"claim": claim, "binding": binding, "decision_id": decision_id}


def test_queue_restores_scope_in_new_thread_and_settles_before_expiry(queued):
    binding = queued["binding"]
    assert set(binding["life_scope"]) == {
        "cycle_id",
        "lease_token",
        "owner_user_id",
        "domain",
        "reserved_tokens",
        "policy_revision",
        "deadline",
    }
    assert reconciliation.reconcile_usage()["resolved"] == 0

    def execute(_task):
        assert life.current_life_claim() == binding["life_scope"]
        held = usage.prepare_platform_call("test", "model", [], 10)
        usage.complete_platform_call(held, {"usage": {"prompt_tokens": 3, "completion_tokens": 4}})
        return {"ok": True, "status": "completed", "output": "actual local worker result"}

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(
            workers.execute_portfolio_worker, binding, owner_user_id=7, execute=execute
        ).result()
    assert result["tasks"]["a"]["actual_tokens"] == 12
    assert result["tasks"]["a"]["status"] == "completed"
    assert life.current_life_claim() is None
    assert reconciliation.reconcile_usage()["resolved"] == 1
    assert reconciliation.reconcile_usage()["resolved"] == 0
    state = life.read_state()
    assert state["budget"]["used_tokens"] == 12
    assert state["budget"]["reserved_tokens"] == 0
    assert state["activity"] is None
    with pytest.raises(portfolio.PortfolioError):
        workers.execute_portfolio_worker(binding, owner_user_id=7, execute=execute)


@pytest.mark.parametrize("change", ["downgrade", "pause", "revision", "expiry", "owner_revoked"])
def test_invalid_lease_cancels_only_unstarted_worker_and_keeps_prior_cost(
    queued, database, monkeypatch, change
):
    if change == "expiry":
        later = life.utcnow() + timedelta(minutes=6)
        monkeypatch.setattr(life, "utcnow", lambda: later)
    elif change == "owner_revoked":
        with database() as session:
            session.get(User, 7).is_admin = False
            session.commit()
    else:
        edits = {
            "downgrade": {"level": 2},
            "pause": {"paused": True},
            "revision": {"mission": "New mission"},
        }
        life.update_settings(
            LifeUpdate(expected_revision=life.read_state()["revision"], **edits[change]),
            actor_user_id=7,
        )
    execute = MagicMock()
    with pytest.raises(portfolio.PortfolioError):
        workers.execute_portfolio_worker(queued["binding"], owner_user_id=7, execute=execute)
    execute.assert_not_called()
    task = portfolio.portfolio_status(queued["decision_id"])["tasks"]["a"]
    assert task["status"] == "failed"
    assert task["execution_receipt"]["status"] == "cancelled"
    assert task["execution_receipt"]["worker_started"] is False
    assert task["actual_tokens"] == 5
    assert reconciliation.reconcile_usage()["resolved"] == 1
    with database() as session:
        persisted = json.loads(session.get(XiaoCLifeState, life.IDENTITY_ID).state_json)
    assert persisted["budget"]["used_tokens"] == 5
    assert life.read_state()["budget"]["used_tokens"] == (
        5 if persisted["budget"]["date"] == life._day() else 0
    )
    assert life.read_state()["budget"]["reserved_tokens"] == 0


@pytest.mark.parametrize("tamper", ["owner", "lease", "scope_revision"])
def test_forged_queue_binding_cannot_cancel_or_enter_original_lease(queued, tamper):
    binding = copy.deepcopy(queued["binding"])
    if tamper == "owner":
        binding["owner_user_id"] = 8
    elif tamper == "lease":
        binding["life_scope"]["lease_token"] = "forged"
    else:
        binding["life_scope"]["policy_revision"] += 1
    execute = MagicMock()
    with pytest.raises(portfolio.PortfolioError):
        workers.execute_portfolio_worker(binding, owner_user_id=7, execute=execute)
    execute.assert_not_called()
    assert portfolio.portfolio_status(queued["decision_id"])["tasks"]["a"]["status"] == "waiting"
    assert life.cycle_active(queued["claim"])
    assert life.current_life_claim() is None


@pytest.mark.parametrize("uncertain", ["running", "unknown_call"])
def test_cancellation_never_releases_running_or_unsettled_spending(queued, uncertain):
    def make_uncertain(_row, _proposal, state, _session):
        task = state["tasks"]["a"]
        if uncertain == "running":
            task["status"] = "running"
        else:
            next(iter(task["calls"].values()))["status"] = "pending"

    portfolio.mutate_portfolio(queued["decision_id"], make_uncertain, owner_user_id=7)
    life.update_settings(
        LifeUpdate(expected_revision=life.read_state()["revision"], paused=True), actor_user_id=7
    )
    with pytest.raises(portfolio.PortfolioError):
        workers.execute_portfolio_worker(queued["binding"], owner_user_id=7, execute=MagicMock())
    task = portfolio.portfolio_status(queued["decision_id"])["tasks"]["a"]
    assert task["status"] == ("running" if uncertain == "running" else "waiting")
    assert reconciliation.reconcile_usage()["resolved"] == 0
    assert life.read_state()["budget"]["reserved_tokens"] == 40_000
