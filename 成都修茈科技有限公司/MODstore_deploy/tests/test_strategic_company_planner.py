"""The original scheduler and claim transaction consume one company allocation."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import select

import modstore_server.strategic_company_planner as planner
import modstore_server.strategic_company_resources as company
import modstore_server.strategic_portfolio as portfolio
import modstore_server.strategic_portfolio_runtime as runtime
import modstore_server.strategic_portfolio_scheduler as scheduler
import tests.test_strategic_company_resources as company_fixtures
from modstore_server.db.identity import User
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision
from tests.test_strategic_company_resources import (
    budget,
    complete,
    finish,
    proposal,
    reserve,
    totals,
)
from tests.test_strategic_portfolio import limits, opportunity

configured = company_fixtures.configured
database = company_fixtures.database


def create_unstarted(owner, *, key, value, period="quarter", approved=True):
    row = portfolio.create_portfolio_proposal(
        owner_user_id=owner,
        goal=f"private-owner-{owner}-{key}",
        period=period,
        limits=limits(),
        opportunities=[opportunity("a", value_score=value)],
        idempotency_key=key,
    )["decision"]
    if approved:
        portfolio.authorize_portfolio(
            row["decision_id"],
            owner_user_id=owner,
            actor=f"admin:{owner}",
            expected_proposal_sha256=row["decision_payload"]["proposal_sha256"],
        )
    return row["decision_id"]


@pytest.fixture
def dispatch(configured, monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: configured)
    monkeypatch.setattr(
        runtime,
        "_business_outcome",
        lambda _state: {
            "status": "unknown",
            "revenue_cents": None,
        },
    )

    def execute(task):
        with configured() as session:
            action = session.scalars(
                select(StrategicActionItem).where(
                    StrategicActionItem.action_id
                    == runtime._action_id(task["decision_id"], task["opportunity_id"])
                )
            ).one()
            assert action.status == "in_progress"
        complete(reserve(task))
        calls.append((task["decision_id"], task["opportunity_id"]))
        return {"ok": True, "status": "completed"}

    monkeypatch.setattr(runtime, "_execute", execute)
    return calls


def test_actual_scheduler_chooses_high_value_owner_even_outside_oldest_limit(configured, dispatch):
    identity = budget(configured)
    older = proposal(7, rows=[opportunity(value_score=2)])
    newer = create_unstarted(8, key="private-high-value", value=90)
    assert runtime._claim(older, 7) is None
    private_status = json.dumps(portfolio.portfolio_status(older, owner_user_id=7))
    assert newer not in private_status and "private-high-value" not in private_status
    assert scheduler.tick(limit=1)["selected"] == 1
    assert dispatch == [(newer, "a")]
    assert portfolio.portfolio_status(older)["tasks"] == {}
    assert totals(identity)["spent"]["tokens"] == 25 and totals(identity)["slots"] == 0
    scheduler.tick(limit=1)
    assert dispatch == [(newer, "a"), (older, "a")]
    assert totals(identity)["spent"]["tokens"] == 50 and totals(identity)["slots"] == 0


@pytest.mark.parametrize("block", ["life", "revoked_owner", "changed_proposal", "unapproved"])
def test_unstartable_high_value_owner_cannot_starve_authorized_work(configured, dispatch, block):
    budget(configured)
    ready = proposal(7, rows=[opportunity(value_score=2)])
    blocked = create_unstarted(
        8,
        key=block,
        value=100000,
        period="xiaoc-life:unclaimed" if block == "life" else "quarter",
        approved=block != "unapproved",
    )
    if block in {"revoked_owner", "changed_proposal"}:
        with configured() as session:
            if block == "revoked_owner":
                session.get(User, 8).is_admin = False
            else:
                row = session.scalars(
                    select(StrategicDecision).where(StrategicDecision.decision_id == blocked)
                ).one()
                changed = json.loads(row.decision_payload_json)
                changed["opportunities"][0]["task"] = "unapproved replacement"
                row.decision_payload_json = json.dumps(changed)
            session.commit()
    scheduler.tick(limit=1)
    assert dispatch == [(ready, "a")]
    assert portfolio.portfolio_status(blocked).get("tasks", {}) == {}


def test_global_solver_prefers_feasible_total_value_over_one_expensive_candidate(configured):
    identity = budget(configured, max_parallel=2)
    expensive = proposal(7, rows=[opportunity(value_score=90, cost_cents=100)])
    combined = proposal(
        8,
        caps=limits(max_parallel=2),
        rows=[
            opportunity("a", value_score=60),
            opportunity("b", value_score=60),
        ],
    )
    assert runtime._claim(expensive, 7) is None
    first, second = runtime._claim(combined, 8), runtime._claim(combined, 8)
    assert {first["opportunity_id"], second["opportunity_id"]} == {"a", "b"}
    assert totals(identity)["held"]["cost_cents"] == 100
    assert totals(identity)["slots"] == 2
    assert runtime._claim(expensive, 7) is None


def test_global_solver_can_select_an_approved_candidate_deferred_by_the_local_plan(configured):
    identity = budget(configured, max_parallel=2)
    first = proposal(
        7,
        rows=[
            opportunity("expensive", value_score=100, cost_cents=100),
            opportunity("alternative", value_score=99, cost_cents=50),
        ],
    )
    second = proposal(8, rows=[opportunity("a", value_score=99, cost_cents=50)])
    before = portfolio.portfolio_status(first)
    assert before["plan"]["selected"] == ["expensive"]
    with configured() as session:
        assert (
            session.scalars(
                select(StrategicActionItem).where(
                    StrategicActionItem.action_id == runtime._action_id(first, "alternative")
                )
            ).one_or_none()
            is None
        )
    claimed = runtime._claim(first, 7)
    other = runtime._claim(second, 8)
    assert claimed["opportunity_id"] == "alternative"
    assert other["opportunity_id"] == "a"
    with configured() as session:
        action = session.scalars(
            select(StrategicActionItem).where(
                StrategicActionItem.action_id == runtime._action_id(first, "alternative")
            )
        ).one()
        assert action.status == "in_progress"
        assert json.loads(action.result_json)["lease_token"] == claimed["lease_token"]
    after = portfolio.portfolio_status(first)
    assert after["proposal_sha256"] == before["proposal_sha256"]
    assert after["limits"] == before["limits"]
    assert after["plan"]["selected"] == ["alternative"]
    assert totals(identity)["held"]["cost_cents"] == 100 and totals(identity)["slots"] == 2


def test_group_capacity_risk_and_dependencies_remain_inside_each_approval(configured):
    identity = budget(configured, cost_cents=200, tokens=200000, max_parallel=2)
    row = {"cost_cents": 30, "tokens": 20000, "compute_seconds": 20}
    first = proposal(
        7,
        rows=[
            opportunity("a", value_score=100, **row),
            opportunity("b", value_score=90, **row),
            opportunity("later", value_score=100000, depends_on=["a"], **row),
            opportunity("high-risk", value_score=100000, risk="high", **row),
        ],
    )
    second = proposal(8, rows=[opportunity("a", value_score=80, **row)])
    claimed = runtime._claim(first, 7)
    assert claimed["opportunity_id"] == "a"
    assert runtime._claim(first, 7) is None
    other = runtime._claim(second, 8)
    assert other["opportunity_id"] == "a" and other["decision_id"] != claimed["decision_id"]
    assert totals(identity)["slots"] == 2
    finish(claimed)
    finish(other)
    assert runtime._claim(first, 7)["opportunity_id"] == "later"


def test_company_choice_reuses_mature_review_without_increasing_original_confidence(
    configured, monkeypatch
):
    budget(configured)
    reviewed = proposal(
        7,
        caps=limits(observation_hours=1),
        rows=[
            opportunity("failed", value_score=101, cost_cents=60),
            opportunity("next", value_score=100, cost_cents=60),
        ],
    )
    other = proposal(8, rows=[opportunity(value_score=75)])
    first = runtime._claim(reviewed, 7)
    assert first["opportunity_id"] == "failed"
    complete(reserve(first))
    runtime._finish(first, {"ok": False, "status": "failed"}, elapsed=1)
    portfolio.mutate_portfolio(
        reviewed,
        lambda _r, _p, state, _db: state.update(
            started_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat()
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_business_outcome",
        lambda _state: {
            "status": "verified",
            "revenue_cents": 1,
        },
    )
    report = runtime.review_portfolio(reviewed)
    assert report["decision"] == "reallocate_within_approval"
    assert report["reallocation"]["selected"] == ["next"]
    assert runtime._claim(reviewed, 7) is None
    assert runtime._claim(other, 8)["opportunity_id"] == "a"
    status = portfolio.portfolio_status(reviewed)
    assert status["opportunities"][1]["confidence_bps"] == 5000
    assert status["limits"]["cost_cents"] == 100


def test_competing_claims_cannot_bypass_global_priority_or_double_spend(configured):
    identity = budget(configured)
    decisions = [
        proposal(7, rows=[opportunity(value_score=1)]),
        proposal(8, rows=[opportunity(value_score=90)]),
    ]
    barrier = Barrier(2)

    def claim(index):
        barrier.wait()
        return runtime._claim(decisions[index], index + 7)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(claim, [0, 1]))
    assert claimed[0] is None and claimed[1]["decision_id"] == decisions[1]
    assert totals(identity)["slots"] == 1
    receipt = reserve(claimed[1])
    from modstore_server.strategic_portfolio_usage import complete_platform_call

    complete_platform_call(receipt, None)
    finish(claimed[1])
    assert runtime._claim(decisions[0], 7) is None
    assert totals(identity)["slots"] == 1
    with pytest.raises(portfolio.PortfolioError, match="unresolved resource holds"):
        budget(configured, key="replacement")


def test_oversized_candidate_snapshot_blocks_instead_of_optimizing_a_prefix(
    configured, monkeypatch
):
    budget(configured)
    first = proposal(7)
    proposal(8)
    monkeypatch.setattr(planner, "COMPANY_MAX_CANDIDATES", 1)
    with pytest.raises(portfolio.PortfolioError, match="snapshot exceeds"):
        runtime._claim(first, 7)
    assert portfolio.portfolio_status(first)["tasks"] == {}
