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
from modstore_server.strategic_customer_outcomes import VERIFIED_DELIVERY_ATTRIBUTION
from modstore_server.xiaoc_life_cognition import (
    SYSTEM_PROMPT,
    CognitionContextError,
    cognition_messages,
    cognitive_review_facts,
    feedback_facts,
    goal_review_facts,
    goal_review_projection,
    parse_decision,
    portfolio_feedback,
    prior_self_assessment,
    reflection_facts,
    reflection_receipt,
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


@pytest.mark.parametrize(
    "attribution,status,revenue,expected",
    [
        (VERIFIED_DELIVERY_ATTRIBUTION, "verified", 0, True),
        (
            "same_owner_completed_task_artifact_and_verified_acceptance_with_order_outcome_not_incremental_causality",
            "verified",
            0,
            True,
        ),
        (VERIFIED_DELIVERY_ATTRIBUTION, "unknown", None, False),
        (
            "same_owner_completed_task_artifact_and_verified_acceptance_with_order_outcome_not_incremental_causality",
            "unknown",
            100,
            False,
        ),
        (VERIFIED_DELIVERY_ATTRIBUTION, "verified", True, False),
        (VERIFIED_DELIVERY_ATTRIBUTION, "verified", -1, False),
        (VERIFIED_DELIVERY_ATTRIBUTION, "verified", "0", False),
        (VERIFIED_DELIVERY_ATTRIBUTION + " ", "verified", 0, False),
        ({"attribution": VERIFIED_DELIVERY_ATTRIBUTION}, "verified", 0, False),
    ],
)
def test_attribution_requires_verified_measurement_and_exact_contract(
    attribution, status, revenue, expected
):
    record = reviewed_record()
    record["reviews"][0]["business"].update(
        attribution=attribution,
        status=status,
        revenue_cents=revenue,
        verified_attributed_cents=100,
        paid_order_count=1,
    )
    metrics = portfolio_feedback(record)["metrics"]
    assert metrics["verified_attributed_cents"] == 100
    assert metrics["attribution"] == (
        "artifact_acceptance_and_order_outcome_not_incremental_causality"
        if expected
        else "unverified"
    )


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


def test_prompt_deduplicates_sources_before_limit_without_rewriting_receipts():
    facts = (
        [{"ref": "receipt:old", "text": "首份原回执"}]
        + [{"ref": "receipt:old", "text": "同一来源的重复记录"} for _ in range(11)]
        + [{"ref": "receipt:new", "text": "新业务事实", "business_feedback": {"decision": "stop"}}]
    )
    original = copy.deepcopy(facts)
    messages, refs = cognition_messages({"identity_id": "xiaoc", "level": 5}, "enterprise", facts)
    observed = json.loads(messages[1]["content"])["observations"]
    assert [{k: v for k, v in row.items() if k != "evidence_status"} for row in observed] == [
        facts[0], facts[-1]
    ]
    assert observed[0]["evidence_status"] == "observed_source_not_verified_claim"
    assert observed[1]["evidence_status"] == "measurement_pending"
    assert refs == {"receipt:old", "receipt:new"}
    assert facts == original


@pytest.mark.parametrize(
    "facts,reason",
    [
        ([], "no_observed_context"),
        ([{"text": "无来源"}], "no_observed_context"),
        ([{"ref": "", "text": "无来源"}], "no_observed_context"),
        ([{"ref": " \t", "text": "无来源"}], "no_observed_context"),
        ([{"ref": 3, "text": "无来源"}], "no_observed_context"),
        (
            [{"ref": "receipt:large", "business_feedback": {"measurement": "测" * 1500}}],
            "life_cycle_prompt_budget_exhausted",
        ),
    ],
)
def test_prompt_rejects_unusable_context_without_altering_structured_evidence(facts, reason):
    from modstore_server import xiaoc_life_cognition as cognition

    original = copy.deepcopy(facts)
    with pytest.raises(ValueError, match=f"^{reason}$") as raised:
        cognition_messages({"identity_id": "xiaoc", "level": 5}, "enterprise", facts)
    assert type(raised.value) is cognition.CognitionContextError
    assert facts == original


@pytest.mark.parametrize(
    "attribution,recognized",
    [
        (
            "same_owner_completed_task_artifact_and_verified_acceptance_with_order_outcome_not_incremental_causality",
            True,
        ),
        (
            "approved_customer_goal_order_completed_artifact_and_verified_acceptance_not_incremental_causality",
            True,
        ),
        ("incremental_causal_profit", False),
        (None, False),
        ({"verified": True}, False),
        (["verified"], False),
    ],
)
def test_feedback_accepts_known_delivery_contracts_and_rejects_unknown_claims(
    attribution, recognized
):
    record = reviewed_record()
    record["reviews"][0]["business"]["attribution"] = attribution
    metrics = portfolio_feedback(record)["metrics"]
    assert metrics["attribution"] == (
        "artifact_acceptance_and_order_outcome_not_incremental_causality"
        if recognized
        else "unverified"
    )


def test_delivery_contract_label_alone_does_not_verify_an_unknown_measurement():
    record = reviewed_record()
    record["reviews"][0]["business"].update(status="unknown", revenue_cents=None)
    feedback = portfolio_feedback(record)
    assert feedback["outcome_status"] == "business_measurement_unknown"
    assert feedback["metrics"]["attribution"] == "unverified"


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
        opportunities=[opportunity(customer_goal_ids=["goal-a"])],
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


@pytest.mark.parametrize("completed_artifact", [True, False])
def test_original_business_review_updates_goal_during_pause_without_replaying(
    approved_life_portfolio, monkeypatch, completed_artifact
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
            {
                "ok": True,
                "status": "completed",
                "output": "actual worker output",
                **(
                    {"artifact_id": "delivered-output", "artifact_sha256": "b" * 64}
                    if completed_artifact
                    else {}
                ),
            },
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
    assert review["business"]["attribution"] == VERIFIED_DELIVERY_ATTRIBUTION
    assert review["business"]["status"] == ("verified" if completed_artifact else "unknown")
    assert review["business"]["revenue_cents"] == (0 if completed_artifact else None)
    assert review["observation_complete"] and review["usage_complete"]
    assert review["attributed_roi_bps"] == (-10000 if completed_artifact else None)
    assert review["decision"] == ("stop" if completed_artifact else "wait_for_measurement")
    assert reconciliation.reconcile_goals() == {"observed": 1}
    assert reconciliation.reconcile_goals() == {"observed": 0}
    after = life.read_state()
    goal = after["goals"][0]
    assert after["paused"] and after["budget"] == before["budget"]
    assert goal["status"] == ("stopped" if completed_artifact else "execution_verified")
    assert goal["outcome_status"] == (
        "business_verified" if completed_artifact else "business_measurement_unknown"
    )
    assert goal["outcome_feedback"]["attributed_roi_bps"] == (
        -10000 if completed_artifact else None
    )
    assert goal["outcome_ref"] != before["goals"][0]["outcome_ref"]
    observation = feedback_facts(after)[0]
    assert observation["ref"] == goal["outcome_ref"]
    assert observation["business_feedback"]["stop_reason"] == (
        "business_roi_guardrail" if completed_artifact else ""
    )
    assert "/private/" not in json.dumps(observation)
    messages, refs = cognition_messages(after, "reflection", [observation])
    next_feedback = json.loads(messages[1]["content"])["observations"][0]
    assert next_feedback["ref"] == goal["outcome_ref"] and next_feedback["ref"] in refs
    assert next_feedback["business_feedback"] == observation["business_feedback"]
    assert next_feedback["business_feedback"]["attribution"] == (
        "artifact_acceptance_and_order_outcome_not_incremental_causality"
        if completed_artifact
        else "unverified"
    )
    reflected = reflection_facts(after)
    reviewed = cognitive_review_facts(after)
    if completed_artifact:
        assert len(reflected) == len(reviewed) == 1
        assert reflected[0]["ref"] == "reflection:execution:" + goal["execution_receipt"]
        assert reviewed[0]["cognitive_review"]["latest_goal_review"]["recommendation"] == (
            "respect_recorded_stop"
        )
        assert not cognitive_review_facts({**after, "owner_user_id": 8})
        stale = copy.deepcopy(after)
        stale["goals"][0]["execution_receipt"] = "newer-receipt"
        assert not reflection_facts(stale)
        assert life.read_state()["budget"] == after["budget"]
        advisory = goal_review_facts(after)
        assert advisory[0]["goal_review"]["recommendation"] == "respect_recorded_stop"
        assert not goal_review_facts({**after, "owner_user_id": 8})
        assert goal["status"] == "stopped"
    else:
        assert not reflected and not reviewed


def test_goal_reconciliation_does_not_overwrite_concurrent_newer_receipt(
    approved_life_portfolio, monkeypatch
):
    original_mutate = reconciliation._mutate

    def interleave(callback):
        def newer(data, _session):
            data["goals"][0].update(
                status="stopped", execution_receipt="newer-receipt", outcome_ref="newer-outcome"
            )

        original_mutate(newer)
        return original_mutate(callback)

    monkeypatch.setattr(reconciliation, "_mutate", interleave)
    assert reconciliation.reconcile_goals() == {"observed": 0}
    goal = life.read_state()["goals"][0]
    assert goal["decision_id"] == approved_life_portfolio
    assert goal["status"] == "stopped"
    assert goal["execution_receipt"] == "newer-receipt"
    assert goal["outcome_ref"] == "newer-outcome"
    assert not any(row["id"].startswith("execution:") for row in life.read_state()["events"])


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
    monkeypatch.setattr(runtime, "_cycle_reservation", lambda state, domain: 32768)
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
    proposals = []

    def propose(**kwargs):
        proposals.append(kwargs)
        return {"decision": {"decision_id": "new-proposal"}}

    monkeypatch.setattr(portfolio, "create_portfolio_proposal", propose)
    result = asyncio.run(runtime.tick_async())
    first = proposals[0]
    row = first["opportunities"][0]
    assert row["input_data"] == {"approved_record_id": "record-17"}
    assert row["compute_seconds"] == 240
    assert result["goals"][0]["status"] == "awaiting_approval"
    assert first["period"].startswith("xiaoc-life:")
    store.claimed = False
    store.graph_started = store.act_admitted = False
    store.claim["cycle_id"] = "next-cycle"
    asyncio.run(runtime.tick_async())
    store.claimed = False
    store.graph_started = store.act_admitted = False
    store.claim["cycle_id"] = "changed-template-cycle"
    store.state["policy"]["task_input"] = {"approved_record_id": "record-18"}
    asyncio.run(runtime.tick_async())
    assert len(proposals) == 3
    assert proposals[1]["idempotency_key"] == first["idempotency_key"]
    assert proposals[2]["idempotency_key"] != first["idempotency_key"]
    assert proposals[2]["opportunities"][0]["input_data"] == {"approved_record_id": "record-18"}


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

def test_cognition_deduplicates_and_bounds_attention():
    state = {"identity_id": "test", "level": 6}
    facts = [{"ref": "observed:1", "text": "original"}] * 15
    facts.append({"ref": "observed:2", "text": "second"})
    messages, refs = cognition_messages(state, "enterprise", facts)
    payload = json.loads(messages[1]["content"])
    assert refs == {"observed:1", "observed:2"}
    assert len(payload["observations"]) == 2
    assert payload["observations"][0]["evidence_status"] == "observed_source_not_verified_claim"
    assert len(messages[1]["content"].encode()) <= 4200
    with pytest.raises(CognitionContextError, match="no_observed_context"):
        cognition_messages(state, "enterprise", [])
    with pytest.raises(CognitionContextError, match="life_cycle_prompt_budget_exhausted"):
        cognition_messages(
            state,
            "enterprise",
            [{"ref": "observed:1", "text": "x", "metadata": "x" * 5000}],
        )


def test_alternatives_remain_distinct_cited_review_suggestions():
    body = {
        "action": "propose",
        "summary": "review",
        "evidence_refs": ["observed:1"],
        "goal": {"title": "original", "description": "review", "evidence_refs": ["observed:1"]},
        "alternatives": [
            {"title": "other", "tradeoff": "uncertain", "evidence_refs": ["observed:1"]}
        ],
    }

    def parse():
        return parse_decision(json.dumps(body), refs={"observed:1"}, level=6, domain="enterprise")

    assert parse().alternatives[0].title == "other"
    body["alternatives"][0]["evidence_refs"] = ["invented:source"]
    with pytest.raises(ValueError, match="unobserved"):
        parse()
    body["alternatives"][0]["evidence_refs"] = ["observed:1"]
    body["alternatives"][0]["title"] = " ORIGINAL "
    with pytest.raises(ValueError, match="distinct"):
        parse()
    body["alternatives"][0]["title"] = "other"
    body["alternatives"][0]["approved"] = True
    with pytest.raises(ValueError):
        parse()


@pytest.mark.parametrize(
    "status,tokens,complete,expected",
    [
        ("completed", 50, True, "measurement_verified"),
        ("completed", None, True, "measurement_pending"),
        ("completed", 50, False, "measurement_pending"),
        ("awaiting_worker", 50, True, "measurement_pending"),
    ],
)
def test_reflection_keeps_measurement_and_completion_distinct(status, tokens, complete, expected):
    feedback = portfolio_feedback(reviewed_record(observation_complete=complete))
    refs = [feedback["evidence_ref"]]
    receipt = reflection_receipt(
        feedback, evidence_refs=refs, status=status, actual_tokens=tokens
    )
    assert receipt["status"] == expected
    if expected == "measurement_verified":
        assert receipt["hypothesis_verdicts"]["miss"] == 1
    assert "success" not in receipt


def test_reflection_recall_uses_same_owner_original_receipt_only():
    feedback = portfolio_feedback(reviewed_record())
    refs = [feedback["evidence_ref"]]
    event = {
        "id": "cycle:" + "a" * 32,
        "status": "completed",
        "actual_tokens": 50,
        "evidence_refs": refs,
        "summary": "private text",
        "details": {
            "owner_user_id": 7,
            "learning_applied": True,
            "outcome_feedback": feedback,
            "reflection_receipt": reflection_receipt(
                feedback, evidence_refs=refs, status="completed", actual_tokens=50
            ),
        },
    }
    state = {"owner_user_id": 7, "events": [event]}
    facts = reflection_facts(state)
    assert len(facts) == 1 and "private text" not in facts[0]["text"]
    assert json.loads(facts[0]["text"])["hypothesis_verdicts"]["miss"] == 1
    state["owner_user_id"] = 8
    assert reflection_facts(state) == []
    state["owner_user_id"] = 7
    event["details"]["learning_applied"] = False
    assert reflection_facts(state) == []
    event["details"]["learning_applied"] = True
    event["details"]["reflection_receipt"]["hypothesis_verdicts"]["miss"] = 0
    assert reflection_facts(state) == []


def _review_event(record, *, cycle="a", owner=17):
    feedback = portfolio_feedback(record)
    refs = [feedback["evidence_ref"]]
    return {
        "id": "cycle:" + cycle * 32,
        "status": "completed",
        "actual_tokens": 50,
        "evidence_refs": refs,
        "details": {
            "owner_user_id": owner,
            "learning_applied": True,
            "outcome_feedback": feedback,
            "reflection_receipt": reflection_receipt(
                feedback, evidence_refs=refs, status="completed", actual_tokens=50
            ),
        },
    }


def _measured_review_record():
    record = reviewed_record()
    hypothesis = record["reviews"][0]["hypotheses"][0]
    hypothesis.update(
        window_start="2026-11-20T10:00:00+00:00",
        window_end="2026-11-21T10:00:00+00:00",
        reviewed_at="2026-11-21T10:00:00+00:00",
    )
    return record


def test_cognitive_review_deduplicates_measurements_and_respects_original_stop():
    event = _review_event(_measured_review_record())
    ref = event["evidence_refs"][0]
    state = {
        "identity_id": "test",
        "level": 6,
        "owner_user_id": 17,
        "goals": [{"id": "g", "status": "stopped", "outcome_ref": ref}],
        "events": [event, _review_event(_measured_review_record(), cycle="b")],
    }
    facts = cognitive_review_facts(state)
    review = facts[0]["cognitive_review"]
    assert review["sample_count"] == 1
    assert review["verdict_counts"] == {"hit": 0, "miss": 1}
    assert review["latest_goal_review"]["recommendation"] == "respect_recorded_stop"
    assert review["source_refs"] == [ref]
    assert state["goals"][0]["status"] == "stopped"
    messages, refs = cognition_messages(state, "reflection", facts)
    assert facts[0]["ref"] in refs
    assert json.loads(messages[1]["content"])["observations"][0]["evidence_status"] == (
        "historical_ledger_review_not_prediction"
    )


@pytest.mark.parametrize("change", ["wrong_owner", "forged_fingerprint", "wrong_verdict", "open_window"])
def test_cognitive_review_rejects_unverified_calibration(change):
    record = _measured_review_record()
    target = record["reviews"][0]["hypotheses"][0]
    if change == "wrong_verdict":
        target["verdict"] = "hit"
    if change == "open_window":
        target["window_end"] = "2026-11-22T10:00:00+00:00"
    event = _review_event(record, owner=8 if change == "wrong_owner" else 17)
    if change == "forged_fingerprint":
        event["details"]["outcome_feedback"]["metrics"]["revenue_cents"] = 999
    state = {"owner_user_id": 17, "events": [event]}
    assert cognitive_review_facts(state) == []
    if change in ("wrong_owner", "forged_fingerprint"):
        assert reflection_facts(state) == []


def test_prior_self_assessment_is_scoped_and_never_a_verified_capability():
    state = {
        "owner_user_id": 17,
        "self_model": {"owner_user_id": 17, "description": "hypothesis", "status": "verified"},
    }
    assert prior_self_assessment(state) == {
        "title": "",
        "description": "hypothesis",
        "status": "hypothesis",
    }
    state["owner_user_id"] = 8
    assert prior_self_assessment(state) == {"status": "unbound_or_previous_owner_hypothesis"}
    del state["self_model"]["owner_user_id"]
    assert prior_self_assessment(state) == {"status": "unbound_or_previous_owner_hypothesis"}


def test_real_cognition_graph_reads_historical_review_without_new_execution_authority(ports):
    store, calls, *_ = ports
    store.state["owner_user_id"] = 17
    store.state["events"] = [_review_event(_measured_review_record())]
    result = asyncio.run(runtime.tick_async())
    assert len(calls) == 1
    payload = json.loads(calls[0]["messages"][1]["content"])
    review = next(row["cognitive_review"] for row in payload["observations"] if "cognitive_review" in row)
    assert review["verdict_counts"]["miss"] == 1
    assert result["goals"][0]["status"] == "proposed"
    assert "decision_id" not in result["goals"][0]


def test_real_cognition_graph_excludes_experiences_pending_human_review(ports):
    store, calls, *_ = ports
    store.state["owner_user_id"] = 17
    store.state["revision"] = store.claim["policy_revision"]
    pending = {
        "ref": "experience:" + "a" * 64,
        "text": "Pending review",
        "experience_candidate": {"outcome": "success", "metric_id": "revenue_monthly"},
    }
    reviewed = {
        "ref": "experience-review:" + "b" * 64,
        "text": "Human-confirmed historical task comparison; not causal proof.",
        "reviewed_experience": {"outcome": "failure", "metric_id": "revenue_monthly"},
        "candidate_ref": "experience:" + "c" * 64,
    }
    store.state["experience_review_facts"] = [pending, reviewed]
    result = asyncio.run(runtime.tick_async())
    assert len(calls) == 1
    payload = json.loads(calls[0]["messages"][1]["content"])
    refs = {row["ref"] for row in payload["observations"]}
    assert pending["ref"] not in refs
    assert reviewed["ref"] in refs
    assert result["goals"][0]["status"] == "proposed"
    assert "decision_id" not in result["goals"][0]


def test_goal_review_evolves_with_original_receipts_without_changing_approval():
    record = _measured_review_record()
    record["halted"] = False
    record["reviews"][0]["decision"] = "reallocate_within_approval"
    record["reviews"][0]["stop_reason"] = ""
    decision_id = record["decision_id"]

    def project(original, status="execution_verified"):
        return goal_review_projection(
            owner=7, goal_id="g1", decision_id=decision_id,
            status=status, feedback=portfolio_feedback(original),
        )

    pending = copy.deepcopy(record)
    pending["reviews"][0]["observation_complete"] = False
    assert project(pending)["recommendation"] == "await_original_evidence"
    assert project(record)["recommendation"] == "consider_revision_in_separate_approval"
    stopped = copy.deepcopy(record)
    stopped["halted"] = True
    assert project(stopped)["recommendation"] == "respect_recorded_stop"
    feedback = portfolio_feedback(record)
    goal = {
        "id": "g1",
        "status": "execution_verified",
        "decision_id": decision_id,
        "outcome_ref": feedback["evidence_ref"],
        "outcome_feedback": feedback["metrics"],
        "outcome_status": feedback["outcome_status"],
        "goal_review": project(record),
    }
    state = {"owner_user_id": 7, "goals": [goal]}
    before = copy.deepcopy(state)
    assert len(goal_review_facts(state)) == 1
    assert state == before
    goal["outcome_ref"] = "forged"
    assert not goal_review_facts(state)
