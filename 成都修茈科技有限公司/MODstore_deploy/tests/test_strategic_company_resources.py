"""Company finance consumes real SQL portfolio claims and raw model receipts."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

import modstore_server.strategic_company_resources as company
import modstore_server.strategic_portfolio as portfolio
import modstore_server.strategic_portfolio_runtime as runtime
import modstore_server.strategic_portfolio_usage as usage
from modstore_server.db.identity import User
from modstore_server.db.llm_chat import LlmClientRequest
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision
from tests.test_strategic_portfolio import database as database_fixture
from tests.test_strategic_portfolio import limits, opportunity

database = database_fixture


@pytest.fixture
def configured(database, monkeypatch):
    monkeypatch.setenv(
        company.CONTROL_ENV,
        json.dumps(
            {
                "scope": "xcagi-company",
                "authorizer_user_ids": [7],
                "eligible_owner_user_ids": [7, 8],
            }
        ),
    )
    with database() as session:
        session.add_all(
            [
                User(id=owner, username=f"admin-{owner}", password_hash="unused", is_admin=True)
                for owner in (7, 8, 9)
            ]
        )
        session.commit()
    return database


def budget(configured, *, approved=True, key="company-period", **overrides):
    caps = {
        key: value for key, value in limits().items() if key in company.CompanyLimits.model_fields
    }
    caps.update(max_parallel=1, expires_at=(datetime.now(UTC) + timedelta(days=8)).isoformat())
    caps.update(overrides)
    result = company.create_company_proposal(
        authorizer_user_id=7,
        period="quarter",
        limits=caps,
        member_owner_ids=[7, 8],
        idempotency_key=key,
    )["decision"]
    identity = result["decision_id"]
    if approved:
        company.authorize_company(
            identity,
            authorizer_user_id=7,
            actor="admin:7",
            expected_proposal_sha256=result["decision_payload"]["proposal_sha256"],
        )
    return identity


def proposal(owner=7, *, key=None, rows=None, caps=None):
    result = portfolio.create_portfolio_proposal(
        owner_user_id=owner,
        goal=f"Owner {owner} private objective",
        period="quarter",
        limits=caps or limits(),
        opportunities=rows or [opportunity()],
        idempotency_key=key or f"portfolio-{owner}",
    )["decision"]
    identity = result["decision_id"]
    portfolio.authorize_portfolio(
        identity,
        owner_user_id=owner,
        actor=f"admin:{owner}",
        expected_proposal_sha256=result["decision_payload"]["proposal_sha256"],
    )
    portfolio.plan_portfolio(identity, owner_user_id=owner)
    return identity


def totals(identity):
    return company.company_status(identity, owner_user_id=7)["totals"]


def reserve(task):
    with usage.portfolio_usage_scope(
        task["decision_id"], task["opportunity_id"], task["lease_token"]
    ):
        return usage.prepare_platform_call(
            "test", "model", [{"role": "user", "content": "hello"}], 10
        )


def complete(reservation, *, prompt=20, completion=5):
    usage.complete_platform_call(
        reservation,
        {
            "provider": "test",
            "model": "model",
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
        },
    )


def finish(task):
    runtime._finish(task, {"ok": True, "status": "completed"}, elapsed=2)


def test_only_configured_authorizer_can_create_one_company_pool(configured, monkeypatch):
    with pytest.raises(portfolio.PortfolioError, match="configured and approved"):
        proposal()
    identity = budget(configured, approved=False)
    with pytest.raises(portfolio.PortfolioError, match="authorizer"):
        company.authorize_company(
            identity, authorizer_user_id=8, actor="admin:8", expected_proposal_sha256="0" * 64
        )
    with configured() as session:
        row = session.scalars(
            select(StrategicDecision).where(StrategicDecision.decision_id == identity)
        ).one()
        expected = json.loads(row.decision_payload_json)["proposal_sha256"]
    company.authorize_company(
        identity, authorizer_user_id=7, actor="admin:7", expected_proposal_sha256=expected
    )
    with pytest.raises(portfolio.PortfolioError, match="not a member"):
        proposal(owner=9)
    first, second = proposal(7), proposal(8)
    assert all(
        portfolio.portfolio_status(item)["limits"]["company_budget_id"] == identity
        for item in (first, second)
    )
    monkeypatch.delenv(company.CONTROL_ENV)
    with pytest.raises(portfolio.PortfolioError, match="configured and approved"):
        proposal(9)
    with pytest.raises(portfolio.PortfolioError, match="configured and approved"):
        runtime._claim(first, 7)


def test_two_owners_compete_atomically_then_real_completion_reallocates(configured):
    identity = budget(configured)
    ids = [proposal(7), proposal(8)]
    barrier = Barrier(2)

    def claim(index):
        barrier.wait()
        return runtime._claim(ids[index], index + 7)

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(claim, (0, 1)))
    winners = [item for item in attempts if item]
    assert len(winners) == 1
    task = winners[0]
    losing = 1 if task["owner_user_id"] == 7 else 0
    assert totals(identity) == {
        "spent": dict.fromkeys(portfolio.RESOURCES, 0),
        "held": {"cost_cents": 50, "tokens": 40000, "compute_seconds": 100},
        "slots": 1,
    }
    assert portfolio.portfolio_status(ids[losing])["tasks"] == {}
    receipt = reserve(task)
    complete(receipt)
    charged = totals(identity)
    assert charged["spent"]["tokens"] == 25 and charged["spent"]["cost_cents"] == 1
    assert charged["held"]["cost_cents"] == 49 and charged["slots"] == 1
    assert runtime._claim(ids[losing], losing + 7) is None
    finish(task)
    released = totals(identity)
    assert released["held"] == dict.fromkeys(portfolio.RESOURCES, 0)
    assert released["spent"] == {"cost_cents": 1, "tokens": 25, "compute_seconds": 2}
    assert released["slots"] == 0
    complete(receipt)
    assert totals(identity) == released
    assert runtime._claim(ids[losing], losing + 7)
    own = company.company_status(identity, owner_user_id=8)
    assert all(value["owner_user_id"] == 8 for value in own["own_allocations"].values())
    assert "private objective" not in json.dumps(own)


def test_unknown_usage_keeps_full_budget_and_slot_after_stop_and_restart(configured):
    identity = budget(configured)
    first, second = proposal(), proposal(8)
    task = runtime._claim(first, 7)
    receipt = reserve(task)
    usage.complete_platform_call(receipt, None)
    finish(task)
    before = totals(identity)
    assert before["spent"]["tokens"] + before["held"]["tokens"] == 40000
    assert before["spent"]["cost_cents"] + before["held"]["cost_cents"] == 50
    assert before["slots"] == 1
    portfolio.stop_portfolio(first, owner_user_id=7, actor="admin:7", reason="unknown stop")
    complete(json.loads(json.dumps(receipt)))
    assert totals(identity) == before
    assert runtime._claim(second, 8) is None
    company.revoke_company(identity, authorizer_user_id=7, actor="admin:7", reason="pause")
    assert totals(identity) == before
    with pytest.raises(portfolio.PortfolioError, match="unresolved resource holds"):
        budget(configured, key="replacement")
    with pytest.raises(portfolio.PortfolioError, match="revoked/stopped"):
        runtime._claim(second, 8)


def test_revocation_blocks_new_calls_but_known_pending_settlement_recovers(configured):
    identity = budget(configured)
    first = proposal()
    task = runtime._claim(first, 7)
    receipt = reserve(task)
    company.revoke_company(identity, authorizer_user_id=7, actor="admin:7", reason="finance stop")
    with pytest.raises(portfolio.PortfolioError, match="revoked/stopped"):
        reserve(task)
    complete(json.loads(json.dumps(receipt)))
    finish(task)
    assert totals(identity)["slots"] == 0
    assert totals(identity)["spent"]["tokens"] == 25
    status = company.company_status(identity, owner_user_id=7)
    assert status["status"] == "withdrawn" and status["stop_reason"] == "finance stop"
    replacement = budget(configured, key="replacement")
    assert replacement != identity
    with pytest.raises(portfolio.PortfolioError, match="mandate changed"):
        runtime._claim(first, 7)
    assert runtime._claim(proposal(key="new-cycle"), 7)


def test_expiry_cannot_release_pending_job_but_terminal_recovery_can(configured, monkeypatch):
    identity = budget(configured)
    first, second = proposal(), proposal(8)
    task = runtime._claim(first, 7)
    receipt = reserve(task)
    clock = datetime.now(UTC) + timedelta(days=10)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock

    monkeypatch.setattr(company, "datetime", Later)
    with pytest.raises(portfolio.PortfolioError, match="expired"):
        runtime._claim(second, 8)
    assert totals(identity)["slots"] == 1
    complete(receipt)
    finish(task)
    assert totals(identity)["slots"] == 0
    assert totals(identity)["spent"]["tokens"] == 25


def test_actual_overrun_is_recorded_and_stops_company_admissions(configured):
    identity = budget(configured)
    task = runtime._claim(proposal(), 7)
    second = proposal(8)
    receipt = reserve(task)
    complete(receipt, prompt=1_500_000, completion=5)
    state = company.company_status(identity, owner_user_id=7)
    assert state["halted"] and state["totals"]["spent"]["tokens"] == 1_500_005
    assert state["totals"]["spent"]["cost_cents"] > state["limits"]["cost_cents"]
    with pytest.raises(portfolio.PortfolioError, match="revoked/stopped"):
        runtime._claim(second, 8)


def test_planning_is_a_real_shared_company_consumer(configured, monkeypatch):
    from modstore_server import llm_quota_monitor

    identity = budget(configured)
    second = proposal(8)
    monkeypatch.setattr(
        llm_quota_monitor,
        "platform_quota_snapshot",
        lambda **_kwargs: pytest.fail("monitoring must not grant company credit"),
    )
    admission = asyncio.run(usage.planning_admission("test", "model", owner_user_id=7))
    assert admission["company_budget_id"] == identity
    with usage.planning_usage_scope(7, admission):
        receipt = usage.prepare_platform_call(
            "test", "model", [{"role": "user", "content": "plan"}], 20
        )
    assert runtime._claim(second, 8) is None
    assert totals(identity)["slots"] == 1
    with configured() as session:
        persisted = session.scalars(
            select(LlmClientRequest).where(
                LlmClientRequest.client_request_id == receipt["request_id"]
            )
        ).one()
        assert json.loads(persisted.done_json)["company_budget_id"] == identity
    complete(receipt)
    assert totals(identity)["slots"] == 0
    assert totals(identity)["spent"]["tokens"] == 25
    assert runtime._claim(second, 8)


def test_unknown_planning_reservation_survives_revoke_and_capacity_recovery(configured):
    identity = budget(configured)
    second = proposal(8)
    admission = asyncio.run(usage.planning_admission("test", "model", owner_user_id=7))
    with usage.planning_usage_scope(7, admission):
        receipt = usage.prepare_platform_call(
            "test", "model", [{"role": "user", "content": "plan"}], 20
        )
    usage.complete_platform_call(receipt, None)
    before = totals(identity)
    assert before["slots"] == 1 and before["held"]["tokens"] > 0
    assert runtime._claim(second, 8) is None
    complete(receipt)
    assert totals(identity) == before
    with pytest.raises(portfolio.PortfolioError, match="unresolved resource holds"):
        budget(configured, key="next")


def test_company_task_and_action_updates_roll_back_together(configured):
    identity = budget(configured)
    first = proposal()
    with configured() as session:
        session.execute(
            text(
                "CREATE TRIGGER deny_portfolio_update BEFORE UPDATE ON strategic_decisions "
                f"WHEN OLD.decision_id = '{first}' "
                "BEGIN SELECT RAISE(ABORT, 'simulated commit interruption'); END"
            )
        )
        session.commit()
    with pytest.raises(IntegrityError):
        runtime._claim(first, 7)
    assert totals(identity)["slots"] == 0
    assert portfolio.portfolio_status(first)["tasks"] == {}
    with configured() as session:
        action = session.scalars(
            select(StrategicActionItem).where(StrategicActionItem.decision_id == first)
        ).one()
        assert action.status == "pending"
        session.execute(text("DROP TRIGGER deny_portfolio_update"))
        session.commit()
    assert runtime._claim(first, 7)
    assert totals(identity)["slots"] == 1


@pytest.mark.parametrize(
    "resource,limit", [("cost_cents", 60), ("tokens", 60000), ("compute_seconds", 150)]
)
def test_shared_financial_and_compute_caps_apply_even_with_a_free_slot(configured, resource, limit):
    identity = budget(configured, max_parallel=2, **{resource: limit})
    caps = limits(**{resource: limit})
    caps["stop_loss_cents"] = min(caps["stop_loss_cents"], caps["cost_cents"])
    first, second = proposal(7, caps=caps), proposal(8, caps=caps)
    task = runtime._claim(first, 7)
    assert totals(identity)["slots"] == 1
    assert runtime._claim(second, 8) is None
    assert totals(identity)["held"][resource] == task[resource]
    finish(task)
    assert runtime._claim(second, 8)
