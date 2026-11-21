"""Original business/worker receipts flow back to life without invented success."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta

import pytest

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as workers
from modstore_server import strategic_portfolio_usage as usage
from modstore_server import xiaoc_life_reconciliation as reconciliation
from modstore_server import xiaoc_life_runtime as runtime
from modstore_server import xiaoc_life_store as life
from modstore_server.xiaoc_life_cognition import (
    SYSTEM_PROMPT,
    cognition_messages,
    feedback_facts,
    portfolio_feedback,
)
from modstore_server.xiaoc_life_policy import LifeUpdate
from tests.test_strategic_portfolio import database as database  # noqa: PLC0414
from tests.test_strategic_portfolio import limits, opportunity, seed_owner
from tests.test_xiaoc_life_runtime import ports as ports  # noqa: PLC0414


def reviewed_record(**changes):
    report = {
        "at": "2026-11-21T10:00:00+00:00",
        "business": {
            "status": "verified",
            "revenue_cents": 0,
            "verified_attributed_cents": 0,
            "paid_order_count": 0,
            "source": "/private/payment/source",
            "order_numbers": ["PRIVATE_ORDER"],
            "window_start": "2026-11-20T10:00:00+00:00",
            "window_end": "2026-11-21T10:00:00+00:00",
            "attribution": "same_owner_completed_task_artifact_and_verified_acceptance_with_order_outcome_not_incremental_causality",
        },
        "accrued_cost_cents": 100,
        "attributed_roi_bps": -10000,
        "usage_complete": True,
        "observation_complete": True,
        "cost_basis": "approved_tariff_accrual_not_supplier_invoice",
        "decision": "stop",
        "stop_reason": "business_roi_guardrail",
        "hypotheses": [
            {
                "hypothesis": {
                    "metric_id": "revenue_monthly",
                    "threshold": 1.0,
                    "direction": "max",
                    "hypothesis": "PRIVATE_CUSTOMER_TEXT",
                },
                "evidence": {"value": 0, "source": "/private/metric/source"},
                "verdict": "miss",
                "snapshot_sha256": "a" * 64,
            }
        ],
        **changes,
    }
    return {"decision_id": "original-portfolio", "reviews": [report], "halted": True}


@pytest.mark.parametrize(
    "change,expected",
    [
        ({}, "business_verified"),
        ({"observation_complete": False}, "observation_in_progress"),
        ({"usage_complete": False}, "pending_usage_verification"),
        (
            {"business": {"status": "unknown", "revenue_cents": None}},
            "business_measurement_unknown",
        ),
        (
            {"business": {"status": "verified", "revenue_cents": True}},
            "business_measurement_unknown",
        ),
    ],
)
def test_feedback_preserves_actual_measurement_stage_and_filters_private_text(change, expected):
    feedback = portfolio_feedback(reviewed_record(**change))
    assert feedback["outcome_status"] == expected
    metrics = feedback["metrics"]
    assert metrics["decision"] == "stop" and metrics["stop_reason"] == "business_roi_guardrail"
    assert metrics["hypotheses"][0]["verdict"] == "miss"
    if expected == "business_verified":
        assert metrics["revenue_cents"] == 0 and metrics["attributed_roi_bps"] == -10000
        assert metrics["paid_order_count"] == 0
    if expected == "business_measurement_unknown":
        assert metrics["revenue_cents"] is None and metrics["attributed_roi_bps"] is None
    serialized = json.dumps(feedback)
    assert "/private/" not in serialized and "PRIVATE_" not in serialized


def test_business_and_stop_feedback_survives_prompt_bound_and_enters_next_model(ports):
    store, calls, *_ = ports
    feedback = portfolio_feedback(reviewed_record())
    store.state["goals"] = [
        {
            "id": "g-old",
            "title": "原经营实验",
            "status": "stopped",
            "outcome_status": feedback["outcome_status"],
            "outcome_ref": feedback["evidence_ref"],
            "outcome_feedback": feedback["metrics"],
            "evidence_refs": [feedback["evidence_ref"]],
        }
    ]
    store.state["events"] = [
        {
            "id": "real-review",
            "summary": "复盘了原经营测量",
            "details": {"outcome_feedback": feedback},
        }
    ]
    store.state["self_model"] = {"description": "待验证的旧假设" * 100}
    asyncio.run(runtime.tick_async())
    payload = json.loads(calls[0]["messages"][1]["content"])
    observation = payload["observations"][0]
    assert observation["ref"] == feedback["evidence_ref"]
    actual = observation["business_feedback"]
    assert actual["outcome_status"] == "business_verified"
    assert actual["attributed_roi_bps"] == -10000 and actual["decision"] == "stop"
    assert (
        actual["attribution"] == "artifact_acceptance_and_order_outcome_not_incremental_causality"
    )
    assert actual["hypotheses"][0]["verdict"] == "miss"
    messages, refs = cognition_messages(
        store.state,
        "reflection",
        feedback_facts(store.state)
        + [{"ref": f"long:{i}", "text": "来源正文" * 500} for i in range(11)],
    )
    assert len(messages[1]["content"].encode()) <= 4200
    assert feedback["evidence_ref"] in refs
    assert "not incremental" in SYSTEM_PROMPT and "model-weight training" in SYSTEM_PROMPT


@pytest.fixture
def approved_life_portfolio(database, monkeypatch):
    for module in (life, reconciliation):
        monkeypatch.setattr(module, "get_session_factory", lambda: database)
    seed_owner(database)
    life.update_settings(
        LifeUpdate(
            expected_revision=1,
            level=6,
            policy={
                "daily_token_limit": 1_000_000,
                "authorization_expires_at": (life.utcnow() + timedelta(days=1)).isoformat(),
            },
        ),
        actor_user_id=7,
    )
    made = portfolio.create_portfolio_proposal(
        owner_user_id=7,
        goal="Measure real delivery",
        period="xiaoc-life:g1",
        limits=limits(observation_hours=1),
        opportunities=[opportunity()],
        idempotency_key="life-feedback-g1",
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
        summary="Observed real source",
        actual_tokens=0,
        evidence_refs=["source:1"],
        goals=[
            {
                "id": "g1",
                "title": "原经营实验",
                "domain": "enterprise",
                "status": "approved",
                "decision_id": decision_id,
                "evidence_refs": ["source:1"],
            }
        ],
    )
    life.wake(actor_user_id=7, expected_revision=life.read_state()["revision"])
    return decision_id


def test_original_business_review_updates_goal_during_pause_without_replaying(
    approved_life_portfolio, monkeypatch
):
    from modstore_server import customer_value_payment_source

    decision_id = approved_life_portfolio
    claim = life.claim_cycle(domain="enterprise", reserve_tokens=40000)
    with life.life_execution_scope(claim):
        portfolio.plan_portfolio(decision_id)
        task = workers._claim(decision_id, 7)
        with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
            call = usage.prepare_platform_call("test", "model", [], 10)
            usage.complete_platform_call(
                call, {"usage": {"prompt_tokens": 3, "completion_tokens": 2}}
            )
        workers._finish(
            task,
            {"ok": True, "status": "completed", "output": "actual worker output"},
            1,
        )
    life.finish_cycle(
        claim,
        status="completed",
        summary="Original execution returned",
        actual_tokens=5,
        evidence_refs=[f"portfolio:{decision_id}"],
    )
    life.update_settings(
        LifeUpdate(expected_revision=life.read_state()["revision"], paused=True),
        actor_user_id=7,
    )
    assert reconciliation.reconcile_goals() == {"observed": 1}
    before = life.read_state()
    assert before["goals"][0]["outcome_status"] == "pending_independent_business_measurement"
    monkeypatch.setattr(
        customer_value_payment_source,
        "load_authoritative_payment_orders",
        lambda *_: {
            "source_available": True,
            "source_authoritative": True,
            "source_owner": "/private/payment/source",
            "orders": [],
        },
    )
    portfolio.mutate_portfolio(
        decision_id,
        lambda _r, _p, state, _s: state.update(
            started_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat()
        ),
        owner_user_id=7,
    )
    review = workers.review_portfolio(decision_id, owner_user_id=7)
    assert review["business"]["status"] == "verified" and review["observation_complete"]
    assert review["attributed_roi_bps"] == -10000 and review["decision"] == "stop"
    assert reconciliation.reconcile_goals() == {"observed": 1}
    assert reconciliation.reconcile_goals() == {"observed": 0}
    after = life.read_state()
    goal = after["goals"][0]
    assert after["paused"] and after["budget"] == before["budget"]
    assert goal["status"] == "stopped" and goal["outcome_status"] == "business_verified"
    assert goal["outcome_feedback"]["attributed_roi_bps"] == -10000
    assert goal["outcome_ref"] != before["goals"][0]["outcome_ref"]
    observation = feedback_facts(after)[0]
    assert observation["ref"] == goal["outcome_ref"]
    assert observation["business_feedback"]["stop_reason"] == "business_roi_guardrail"
    assert "/private/" not in json.dumps(observation)


@pytest.mark.parametrize("raced_worker", [False, True])
def test_runtime_keeps_real_queued_worker_lease_including_pending_call_race(
    approved_life_portfolio, monkeypatch, raced_worker
):
    from modstore_server import employee_executor

    decision_id = approved_life_portfolio
    captured = {}

    def queue_employee(*_args, **_kwargs):
        call = usage.prepare_platform_call("test", "model", [], 10)
        usage.complete_platform_call(call, {"usage": {"prompt_tokens": 3, "completion_tokens": 2}})
        captured["binding"] = usage.bind_portfolio_worker("local-queue:real", owner_user_id=7)
        return {"ok": True, "status": "queued", "worker_receipt_id": "local-queue:real"}

    monkeypatch.setattr(employee_executor, "execute_employee_task", queue_employee)
    original_review = workers.review_portfolio
    monkeypatch.setattr(
        workers,
        "_business_outcome",
        lambda *a, **k: {"status": "unknown", "revenue_cents": None},
    )

    def review(*args, **kwargs):
        if raced_worker:
            with usage.portfolio_worker_scope(captured["binding"], owner_user_id=7) as worker_task:
                captured["task"] = worker_task
                captured["pending"] = usage.prepare_platform_call("test", "model", [], 10)
        return original_review(*args, **kwargs)

    monkeypatch.setattr(workers, "review_portfolio", review)
    result = asyncio.run(runtime.tick_async())
    binding = captured["binding"]
    task = portfolio.portfolio_status(decision_id)["tasks"]["a"]
    assert task["status"] == ("running" if raced_worker else "waiting")
    assert task["execution_receipt"]["worker_receipt_id"] == binding["receipt_id"]
    assert result["budget"]["reserved_tokens"] == 40000 and not result["unknown_usage"]
    waiting = next(
        row
        for row in result["events"]
        if row["id"] == "waiting:" + binding["life_scope"]["cycle_id"]
    )
    assert (
        waiting["details"]["awaiting_worker"][0]["receipt_ref"] == "worker-receipt:local-queue:real"
    )
    assert not any(
        row["id"] == "cycle:" + binding["life_scope"]["cycle_id"] for row in result["events"]
    )
    assert life.cycle_active(binding["life_scope"])
    assert reconciliation.reconcile_usage()["resolved"] == 0
    if raced_worker:
        usage.complete_platform_call(
            captured["pending"], {"usage": {"prompt_tokens": 3, "completion_tokens": 4}}
        )
        workers._finish(
            captured["task"],
            {"ok": True, "status": "completed", "output": "actual worker result"},
            2,
        )
    else:
        workers.execute_portfolio_worker(
            binding,
            owner_user_id=7,
            execute=lambda _: {
                "ok": True,
                "status": "completed",
                "output": "actual worker result",
            },
        )
    assert reconciliation.reconcile_usage()["resolved"] == 1
    final = life.read_state()
    assert final["budget"]["reserved_tokens"] == 0
    assert final["budget"]["used_tokens"] == (12 if raced_worker else 5)


def test_goal_capacity_blocks_proposal_before_creating_orphan_and_preserves_bindings(
    ports, monkeypatch
):
    store = ports[0]
    store.state["goals"] = [
        {
            "id": f"g-{i}",
            "title": f"已有目标{i}",
            "status": "approved",
            "decision_id": f"original-{i}",
            "evidence_refs": ["original:source"],
        }
        for i in range(100)
    ]
    original = copy.deepcopy(store.state["goals"])
    store.state["policy"].update(employee_id="approved-employee", portfolio_limits=limits())
    monkeypatch.setattr(
        portfolio,
        "create_portfolio_proposal",
        lambda **_: pytest.fail("must not create orphan proposal"),
    )
    result = asyncio.run(runtime.tick_async())
    assert result["status"] == "blocked" and not result["goals"]
    assert result["details"]["blocked_reason"] == "life_goal_capacity_reached"
    assert store.state["goals"] == original


def test_automatic_proposal_uses_only_admin_frozen_task_input(ports, monkeypatch):
    store = ports[0]
    store.state["policy"].update(
        employee_id="approved-employee",
        portfolio_limits=limits(),
        task_input={"approved_record_id": "record-17"},
    )
    captured = {}

    def propose(**kwargs):
        captured.update(kwargs)
        return {"decision": {"decision_id": "new-proposal"}}

    monkeypatch.setattr(portfolio, "create_portfolio_proposal", propose)
    result = asyncio.run(runtime.tick_async())
    row = captured["opportunities"][0]
    assert row["input_data"] == {"approved_record_id": "record-17"}
    assert row["compute_seconds"] == 240
    assert result["goals"][0]["status"] == "awaiting_approval"
    assert captured["period"].startswith("xiaoc-life:")
    first_key = captured["idempotency_key"]
    store.claimed = False
    store.claim["cycle_id"] = "next-cycle"
    asyncio.run(runtime.tick_async())
    assert captured["idempotency_key"] == first_key
    store.claimed = False
    store.claim["cycle_id"] = "changed-template-cycle"
    store.state["policy"]["task_input"] = {"approved_record_id": "record-18"}
    asyncio.run(runtime.tick_async())
    assert captured["idempotency_key"] != first_key


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("life_cycle_prompt_budget_exhausted", "预算不足以容纳观察上下文"),
        ("platform_model_not_configured", "尚未配置可用的平台模型"),
        ("platform_quota_unknown_or_exhausted", "额度未知或已耗尽"),
        ("research_not_configured", "尚未配置自托管 SearXNG"),
        ("model_usage_unknown", "模型调用用量尚未核实"),
    ],
)
def test_blocked_reason_is_actionable_without_exposing_arbitrary_text(
    ports, monkeypatch, reason, expected
):
    async def blocked(*_):
        raise runtime.LifeBlocked(reason)

    monkeypatch.setattr(runtime.CyclePorts, "observe", blocked)
    result = asyncio.run(runtime.tick_async())
    assert expected in result["summary"]
    assert result["details"]["reason"] == reason
