"""Enterprise ownership changes consult original SQL task and usage receipts."""

from __future__ import annotations

from datetime import timedelta

import pytest

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_portfolio_usage as usage
from modstore_server import xiaoc_life_runtime
from modstore_server import xiaoc_life_store as life
from modstore_server.db.identity import User
from modstore_server.xiaoc_life_policy import LifePolicyError, LifeUpdate
from tests.test_strategic_portfolio import claim_proposal
from tests.test_strategic_portfolio import database as database
from tests.test_strategic_portfolio import limits, opportunity


@pytest.fixture
def owned(database, monkeypatch):
    monkeypatch.setattr(life, "get_session_factory", lambda: database)
    decision_id, task = claim_proposal(database)
    with database() as session:
        session.add_all(
            User(id=i, username=f"next-admin-{i}", password_hash="unused", is_admin=True)
            for i in (8, 9)
        )
        session.commit()
    life.update_settings(
        LifeUpdate(
            expected_revision=life.read_state()["revision"],
            level=4,
            policy={
                "daily_token_limit": 1000,
                "authorization_expires_at": (life.utcnow() + timedelta(days=1)).isoformat(),
            },
        ),
        actor_user_id=7,
    )

    def bind(data, _session):
        # A stale UI projection must never override the original task ledger.
        data["goals"] = [
            {
                "id": "historical-goal",
                "decision_id": decision_id,
                "status": "completed",
                "evidence_refs": [f"portfolio:{decision_id}"],
            }
        ]

    life._mutate(bind)
    return decision_id, task


def revoke(database, user_id=7):
    with database() as session:
        session.get(User, user_id).is_admin = False
        session.commit()


def transfer(user_id=8):
    return life.update_settings(
        LifeUpdate(expected_revision=life.read_state()["revision"], policy={}),
        actor_user_id=user_id,
    )


@pytest.mark.parametrize("succeeded", [False, True])
def test_revoked_owner_with_settled_history_can_be_replaced_without_transferring_approval(
    database, owned, succeeded
):
    decision_id, task = owned
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        held = usage.prepare_platform_call("test", "model", [], 100)
        usage.complete_platform_call(
            held, {"ok": True, "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        )
    runtime._finish(task, {"ok": succeeded, "status": "completed" if succeeded else "failed"}, 1)
    # A lagging projection must become execution history, not a new-owner task.
    life._mutate(lambda data, _session: data["goals"][0].update(status="approved"))
    original = portfolio.portfolio_status(decision_id, owner_user_id=7)
    before = life.read_state()
    revoke(database)

    updated = transfer()
    assert updated["owner_user_id"] == 8
    assert updated["identity_id"] == before["identity_id"]
    assert updated["goals"] == [
        {**before["goals"][0], "status": "execution_verified" if succeeded else "failed"}
    ]
    assert updated["budget"] == before["budget"]
    assert portfolio.portfolio_status(decision_id, owner_user_id=7) == original
    with pytest.raises(portfolio.PortfolioError, match="owner"):
        portfolio.portfolio_status(decision_id, owner_user_id=8)
    assert updated["events"][0]["details"] == {
        "previous_owner_user_id": 7,
        "owner_user_id": 8,
        "before_paused": before["paused"],
        "before_stopped": before.get("stopped", False),
        "paused": False,
        "stopped": False,
    }
    assert (
        xiaoc_life_runtime._domain_order(
            {**updated, "level": 5, "interests": [{"topic": "public research"}], "events": []}
        )[0]
        == "exploration"
    )

    # The same immutable history must not deadlock the next administrator change.
    revoke(database, 8)
    assert transfer(9)["owner_user_id"] == 9


@pytest.mark.parametrize("unknown_usage", [False, True])
def test_terminal_ui_and_stopped_portfolio_do_not_hide_unsettled_original_work(
    database, owned, unknown_usage
):
    decision_id, task = owned
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        held = usage.prepare_platform_call("test", "model", [], 100)
        if unknown_usage:
            usage.complete_platform_call(held, {"ok": True})
    if unknown_usage:
        runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    portfolio.stop_portfolio(decision_id, owner_user_id=7, actor="admin:7", reason="stop")
    revoke(database)
    before = life.read_state()
    assert before["goals"][0]["status"] == "completed"
    assert before["activity"] is None and before["unknown_usage"] is False
    with pytest.raises(LifePolicyError, match="原"):
        transfer()
    assert life.read_state()["owner_user_id"] == 7
    original = portfolio.portfolio_status(decision_id, owner_user_id=7)
    assert original["tasks"]["a"]["status"] == ("unknown" if unknown_usage else "running")
    assert original["tasks"]["a"]["calls"][held["request_id"]]["status"] == (
        "unknown" if unknown_usage else "pending"
    )


def test_unreleased_life_reservation_blocks_handoff_after_task_completion(database, owned):
    _decision_id, task = owned
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    life._mutate(lambda data, _session: data["budget"].update(reserved_tokens=100))
    revoke(database)
    with pytest.raises(LifePolicyError, match="原"):
        transfer()
    assert life.read_state()["budget"]["reserved_tokens"] == 100


def test_unstarted_approved_work_blocks_handoff_even_after_other_goals_finish(database, owned):
    _decision_id, task = owned
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    pending = portfolio.create_portfolio_proposal(
        owner_user_id=7,
        goal="Unstarted approved work",
        period="handoff-regression",
        limits=limits(),
        opportunities=[opportunity("pending")],
        idempotency_key="not-yet-started",
    )["decision"]
    portfolio.authorize_portfolio(
        pending["decision_id"],
        owner_user_id=7,
        actor="admin:7",
        expected_proposal_sha256=pending["decision_payload"]["proposal_sha256"],
    )
    life._mutate(
        lambda data, _session: data["goals"].append(
            {"id": "pending", "decision_id": pending["decision_id"], "status": "completed"}
        )
    )
    revoke(database)
    with pytest.raises(LifePolicyError, match="原"):
        transfer()


@pytest.mark.parametrize("approved", [False, True])
def test_unapproved_or_unselected_opportunities_are_not_unsettled_authority(
    database, owned, approved
):
    _decision_id, task = owned
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    draft = portfolio.create_portfolio_proposal(
        owner_user_id=7,
        goal="Only one opportunity fits the original budget",
        period="handoff-regression",
        limits=limits(cost_cents=50, stop_loss_cents=50),
        opportunities=[opportunity("first"), opportunity("deferred")],
        idempotency_key="limited-selection",
    )["decision"]
    decision_id = draft["decision_id"]
    if approved:
        portfolio.authorize_portfolio(
            decision_id,
            owner_user_id=7,
            actor="admin:7",
            expected_proposal_sha256=draft["decision_payload"]["proposal_sha256"],
        )
        plan = portfolio.plan_portfolio(decision_id)
        assert len(plan["selected"]) == 1 and len(plan["deferred"]) == 1
        claimed = runtime._claim(decision_id, 7)
        runtime._finish(claimed, {"ok": True, "status": "completed"}, 1)
    life._mutate(
        lambda data, _session: data["goals"].append(
            {"id": "limited", "decision_id": decision_id, "status": "approved"}
        )
    )
    original = portfolio.portfolio_status(decision_id, owner_user_id=7)
    revoke(database)
    updated = transfer()
    assert updated["owner_user_id"] == 8
    assert updated["goals"][-1]["status"] == (
        "execution_verified" if approved else "awaiting_approval"
    )
    assert portfolio.portfolio_status(decision_id, owner_user_id=7) == original
