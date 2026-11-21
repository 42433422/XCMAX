"""The original life scheduler resumes approved work after company contention."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as workers
from modstore_server import xiaoc_life_reconciliation as reconciliation
from modstore_server import xiaoc_life_runtime as runtime
from modstore_server import xiaoc_life_store as life
from modstore_server.db.strategic import StrategicActionItem
from modstore_server.xiaoc_life_policy import LifeUpdate
from tests import test_strategic_company_resources as company
from tests.test_strategic_portfolio import limits, opportunity

database = company.database
configured = company.configured


@pytest.fixture
def company_life(configured, monkeypatch):
    for module in (life, reconciliation):
        monkeypatch.setattr(module, "get_session_factory", lambda: configured)
    life.update_settings(
        LifeUpdate(
            expected_revision=1,
            level=4,
            policy={
                "daily_token_limit": 1_000_000,
                "daily_cycle_limit": 10,
                "exploration_percent": 0,
                "authorization_expires_at": (life.utcnow() + timedelta(days=1)).isoformat(),
            },
        ),
        actor_user_id=7,
    )
    identity = company.budget(configured, cost_cents=200, tokens=500000, compute_seconds=1000)
    dispatched = []

    def execute(task):
        company.complete(company.reserve(task))
        dispatched.append((task["decision_id"], task["opportunity_id"]))
        return {"ok": True, "status": "completed"}

    monkeypatch.setattr(workers, "_execute", execute)
    monkeypatch.setattr(
        workers, "_business_outcome", lambda *_: {"status": "unknown", "revenue_cents": None}
    )
    return configured, identity, dispatched


def approve_work(rows):
    made = portfolio.create_portfolio_proposal(
        owner_user_id=7,
        goal="Complete the original company work",
        period="xiaoc-life:company-ready",
        limits=limits(tokens=200000),
        opportunities=rows,
        idempotency_key="life-company-ready",
    )["decision"]
    identity = made["decision_id"]
    portfolio.authorize_portfolio(
        identity,
        owner_user_id=7,
        actor="admin:7",
        expected_proposal_sha256=made["decision_payload"]["proposal_sha256"],
    )
    seed = life.claim_cycle(domain="enterprise", reserve_tokens=0)
    life.finish_cycle(
        seed,
        status="completed",
        summary="Original administrator approved the task inputs",
        evidence_refs=["original:company-task"],
        actual_tokens=0,
        goals=[
            {
                "id": "company-ready",
                "title": "Original company work",
                "domain": "enterprise",
                "status": "approved",
                "decision_id": identity,
                "evidence_refs": ["original:company-task"],
            }
        ],
    )
    return identity


def advance():
    life.wake(actor_user_id=7, expected_revision=life.read_state()["revision"])
    return asyncio.run(runtime.tick_async())


@pytest.mark.parametrize("with_history", [False, True])
def test_company_deferral_then_release_resumes_original_ready_task_once(company_life, with_history):
    factory, company_id, dispatched = company_life
    rows = [
        opportunity("ready", cost_cents=30, depends_on=["past"] if with_history else []),
        opportunity("later", cost_cents=30, tokens=90000, depends_on=["ready"]),
        opportunity("high-risk", cost_cents=1, tokens=900000, risk="high", value_score=100000),
        opportunity("unaffordable", cost_cents=500, tokens=950000, value_score=100000),
    ]
    if with_history:
        rows.insert(0, opportunity("past", cost_cents=10, tokens=10000))
    identity = approve_work(rows)
    approved = portfolio.portfolio_status(identity)["proposal_sha256"]
    if with_history:
        advance()
        assert dispatched == [(identity, "past")]
        # Older snapshots scheduled an outcome review after completing only the
        # local plan. That timestamp must not delay newly eligible company work.
        life._mutate(
            lambda saved, _db: saved["goals"][0].update(
                next_review_at=(life.utcnow() + timedelta(hours=1)).isoformat()
            )
        )
    other = company.proposal(8, rows=[opportunity(value_score=1000)])
    occupied = workers._claim(other, 8)
    assert occupied and company.totals(company_id)["slots"] == 1
    advance()
    deferred = portfolio.portfolio_status(identity)
    assert deferred["plan"]["selected"] == (["past"] if with_history else [])
    assert "ready" not in deferred["tasks"]
    # Future dependencies, high risk and unaffordable candidates cannot inflate
    # the next life reservation. A company deferral is not exhausted work.
    assert runtime._cycle_reservation(life.read_state(), "enterprise") == 40000
    company.complete(company.reserve(occupied))
    company.finish(occupied)
    assert company.totals(company_id)["slots"] == 0
    advance()
    current = portfolio.portfolio_status(identity)
    assert current["tasks"]["ready"]["status"] == "completed"
    assert dispatched.count((identity, "ready")) == 1
    assert runtime._cycle_reservation(life.read_state(), "enterprise") == 90000
    advance()
    final = portfolio.portfolio_status(identity)
    assert final["tasks"]["later"]["status"] == "completed"
    assert dispatched.count((identity, "ready")) == dispatched.count((identity, "later")) == 1
    assert "high-risk" not in final["tasks"] and "unaffordable" not in final["tasks"]
    assert final["proposal_sha256"] == approved
    assert not life.read_state()["unknown_usage"]
    assert life.read_state()["budget"]["used_tokens"] == (75 if with_history else 50)
    with factory() as session:
        actions = session.scalars(
            select(StrategicActionItem).where(
                StrategicActionItem.decision_id == identity,
                StrategicActionItem.status == "completed",
            )
        ).all()
        assert len(actions) == (3 if with_history else 2)


def test_daily_life_cap_can_run_smaller_global_candidate_without_enlarging_it(company_life):
    _, company_id, dispatched = company_life
    life.update_settings(
        LifeUpdate(
            expected_revision=life.read_state()["revision"], policy={"daily_token_limit": 30000}
        ),
        actor_user_id=7,
    )
    identity = approve_work(
        [
            opportunity("large", cost_cents=100, tokens=80000, value_score=100),
            opportunity("small", cost_cents=50, tokens=20000, value_score=99),
        ]
    )
    assert runtime._cycle_reservation(life.read_state(), "enterprise") == 80000
    result = advance()
    assert dispatched == [(identity, "small")]
    assert portfolio.portfolio_status(identity)["tasks"]["small"]["status"] == "completed"
    assert "large" not in portfolio.portfolio_status(identity)["tasks"]
    assert result["budget"]["used_tokens"] == 25 and result["budget"]["reserved_tokens"] == 0
    assert not result["unknown_usage"] and company.totals(company_id)["slots"] == 0
