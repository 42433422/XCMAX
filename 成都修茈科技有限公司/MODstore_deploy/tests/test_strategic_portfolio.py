"""Real optimizer/SQLite tests for strategy, budget, execution and outcome boundaries."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from modstore_server import strategic_portfolio as p
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_portfolio_usage as usage
from modstore_server.db.db_base import Base
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision


@pytest.fixture
def database(tmp_path, monkeypatch):
    from modstore_server import (
        db,
        employee_runtime,
        models,
    )
    from modstore_server.strategic_layer import autonomy_boundary, decision_ledger

    engine = create_engine(
        f"sqlite:///{tmp_path / 'strategy.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for module in (p, runtime, usage, db.db_base, autonomy_boundary, decision_ledger):
        monkeypatch.setattr(module, "get_session_factory", lambda: factory)
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "workspaces" / "{user_id}"))
    monkeypatch.setattr(
        employee_runtime,
        "load_employee_pack_resolved",
        lambda _session, employee_id, **_kwargs: {
            "pack_id": employee_id,
            "version": "1.0.0",
            "manifest": deepcopy(
                {
                    "employee_config_v2": {
                        "workspace_policy": {
                            "scope_globs": ["docs/**"],
                            "forbidden_globs": ["**/.env"],
                        },
                        "actions": {"handlers": ["echo"]},
                    }
                }
            ),
        },
    )
    yield factory
    engine.dispose()


def limits(**overrides):
    return {
        "cost_cents": 100,
        "tokens": 100_000,
        "compute_seconds": 600,
        "stop_loss_cents": 100,
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "tariffs": [
            {
                "provider": "test",
                "model": "model",
                "input_cents_per_million": 100,
                "output_cents_per_million": 100,
                "source": "approved-unit-price",
            }
        ],
        **overrides,
    }


def opportunity(key="a", **overrides):
    return {
        "opportunity_id": key,
        "title": key,
        "task": f"Run approved task {key}",
        "employee_id": "test-qa-runner",
        "source_refs": ["incident:1"],
        "value_score": 10,
        "cost_cents": 50,
        "tokens": 40_000,
        "compute_seconds": 100,
        **overrides,
    }


def seed_owner(database):
    from modstore_server.db.identity import User

    with database() as session:
        if session.get(User, 7) is None:
            session.add(
                User(id=7, username="portfolio-owner", password_hash="unused", is_admin=True)
            )
            session.commit()


def proposal(database, *, rows=None, caps=None, approved=True):
    seed_owner(database)
    result = p.create_portfolio_proposal(
        owner_user_id=7,
        goal="Improve delivery",
        period="2026-Q4",
        limits=caps or limits(),
        opportunities=rows or [opportunity()],
        idempotency_key="one",
    )
    decision_id = result["decision"]["decision_id"]
    if approved:
        p.authorize_portfolio(
            decision_id,
            owner_user_id=7,
            actor="admin:7",
            expected_proposal_sha256=result["decision"]["decision_payload"]["proposal_sha256"],
        )
    return decision_id


def claim_proposal(database, **kwargs):
    decision_id = proposal(database, **kwargs)
    p.plan_portfolio(decision_id)
    return decision_id, runtime._claim(decision_id, 7)


def planning_budget(**overrides):
    return {
        "provider": "test",
        "model": "model",
        "max_total_tokens": 32768,
        "max_output_tokens": 1600,
        **overrides,
    }


def test_optimizer_is_not_greedy_and_checks_dependencies():
    rows = [
        opportunity("a", cost_cents=60, value_score=6, tokens=1),
        opportunity("b", value_score=5, tokens=1),
        opportunity("c", value_score=5, tokens=1),
    ]
    assert p.optimize_portfolio(rows, limits())["selected"] == ["b", "c"]
    rows[2]["depends_on"] = ["a"]
    assert p.optimize_portfolio(rows, limits())["selected"] == ["a"]
    rows[0]["risk"] = "high"
    assert p.optimize_portfolio(rows, limits())["selected"] == ["b"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("cost_cents", -1),
        ("tokens", True),
        ("value_score", 2**31),
        ("confidence_bps", float("nan")),
    ],
)
def test_solver_rejects_invalid_or_overflowing_coefficients(field, value):
    with pytest.raises(ValueError):
        p.optimize_portfolio([opportunity(**{field: value})], limits())


def test_proposal_is_idempotent_but_changed_payload_conflicts(database):
    caps = limits()
    decision_id = proposal(database, caps=caps, approved=False)
    assert proposal(database, caps=caps, approved=False) == decision_id
    with pytest.raises(p.PortfolioError, match="different proposal"):
        proposal(database, caps=caps, rows=[opportunity(task="different task")], approved=False)


def test_approval_binds_hash_owner_and_authenticated_state(database):
    decision_id = proposal(database, approved=False)
    with pytest.raises(p.PortfolioError, match="approval"):
        p.plan_portfolio(decision_id)
    with pytest.raises(p.PortfolioError):
        p.authorize_portfolio(
            decision_id, owner_user_id=7, actor="admin:7", expected_proposal_sha256="wrong"
        )
    with pytest.raises(p.PortfolioError, match="owner"):
        p.portfolio_status(decision_id, owner_user_id=8)
    with database() as session:
        row = session.execute(select(StrategicDecision)).scalar_one()
        row.status, row.decided_by = "approved", "user"
        session.commit()
    with pytest.raises(p.PortfolioError, match="authenticated"):
        p.plan_portfolio(decision_id)


def test_claim_is_exclusive_and_completed_task_is_not_replayed(database, monkeypatch):
    decision_id = proposal(database)
    p.plan_portfolio(decision_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: runtime._claim(decision_id, 7), range(2)))
    assert sum(item is not None for item in claimed) == 1
    task = next(item for item in claimed if item)
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    monkeypatch.setattr(
        runtime, "_execute", lambda *_: pytest.fail("replayed completed side effect")
    )
    assert runtime.run_portfolio_cycle(decision_id)["processed"] == 0
    with database() as session:
        assert session.execute(select(StrategicActionItem)).scalar_one().status == "completed"


def test_real_usage_settles_and_unknown_usage_keeps_hold(database):
    decision_id, task = claim_proposal(database)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        held = usage.prepare_platform_call(
            "test", "model", [{"role": "user", "content": "test"}], 100
        )
        usage.complete_platform_call(
            held, {"ok": True, "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        )
        second = usage.prepare_platform_call(
            "test", "model", [{"role": "user", "content": "test"}], 100
        )
        usage.complete_platform_call(second, {"ok": True})
        with pytest.raises(p.PortfolioError, match="stopped"):
            usage.prepare_platform_call("test", "model", [], 10)
    state = p.portfolio_status(decision_id)
    assert state["halted"] is True
    assert state["tasks"]["a"]["calls"][held["request_id"]]["actual_tokens"] == 15
    missing = state["tasks"]["a"]["calls"][second["request_id"]]
    assert missing["status"] == "unknown" and "accrued_cost_cents" not in missing


def test_stop_revokes_active_lease_admission_but_still_settles_paid_usage(database):
    decision_id, task = claim_proposal(database)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        held = usage.prepare_platform_call("test", "model", [], 10)
        p.stop_portfolio(decision_id, owner_user_id=7, actor="admin:7", reason="operator veto")
        usage.complete_platform_call(held, {"usage": {"prompt_tokens": 10, "completion_tokens": 1}})
        with pytest.raises(p.PortfolioError):
            usage.prepare_platform_call("test", "model", [], 10)
    assert p.portfolio_status(decision_id)["halted"] is True


def test_unapproved_route_and_spend_limit_fail_before_call(database):
    decision_id, task = claim_proposal(database, caps=limits(stop_loss_cents=0))
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        with pytest.raises(p.PortfolioError, match="tariff"):
            usage.prepare_platform_call("unapproved", "model", [], 10)
        with pytest.raises(p.PortfolioError, match="stop loss"):
            usage.prepare_platform_call("test", "model", [], 10)


def test_expired_running_task_does_not_retry_side_effect(database):
    decision_id = proposal(database)
    p.plan_portfolio(decision_id)
    runtime._claim(decision_id, 7)

    def expire(_row, _proposal, state, _session):
        state["tasks"]["a"]["deadline"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    p.mutate_portfolio(decision_id, expire)
    assert runtime._claim(decision_id, 7) is None
    assert (
        p.portfolio_status(decision_id)["stop_reason"] == "execution_outcome_unknown_after_deadline"
    )


def test_review_unknown_payment_source_is_not_zero_revenue(database, monkeypatch):
    from modstore_server import customer_value_payment_source

    decision_id = proposal(database)
    p.plan_portfolio(decision_id)
    monkeypatch.setattr(
        customer_value_payment_source,
        "load_authoritative_payment_orders",
        lambda _: {"source_available": False},
    )
    report = runtime.review_portfolio(decision_id)
    assert report["business"]["revenue_cents"] is None
    assert report["attributed_roi_bps"] is None
    assert report["decision"] == "wait_for_measurement"


def test_outcome_rejects_unrelated_future_refunded_or_wrong_customer_payments(
    database, monkeypatch
):
    from modstore_server import customer_value_payment_source
    from modstore_server.db.customer_value import CustomerValueReceipt

    decision_id = proposal(
        database,
        rows=[
            opportunity(customer_goal_ids=["goal-a"]),
            opportunity("deferred", risk="high", customer_goal_ids=["goal-deferred"]),
        ],
    )
    p.plan_portfolio(decision_id)
    task = runtime._claim(decision_id, 7)
    runtime._finish(
        task,
        {
            "ok": True,
            "status": "completed",
            "artifact_id": "artifact-a",
            "artifact_sha256": "b" * 64,
        },
        1,
    )
    start = datetime.now(UTC) - timedelta(days=2)

    def backdate(_r, _p, state, _db):
        state["started_at"] = start.isoformat()
        state["tasks"]["a"]["started_at"] = start.isoformat()
        state["tasks"]["a"]["completed_at"] = start.isoformat()

    p.mutate_portfolio(decision_id, backdate)
    orders = []
    with database() as session:
        for number in (
            "revenue-a",
            "unrelated",
            "refunded",
            "wrong-user",
            "future",
            "other-owner",
            "deferred",
            "wrong-artifact",
        ):
            orders.append(
                {
                    "out_trade_no": number,
                    "status": "paid",
                    "user_id": 9 if number == "other-owner" else 7,
                    "amount_cents": 100,
                    "paid_at": (
                        start + timedelta(hours=1)
                        if number != "future"
                        else datetime.now(UTC) + timedelta(days=1)
                    ).isoformat(),
                    "payment_provider": "alipay",
                    "provider_verification": "alipay_signed_callback",
                    "provider_trade_no": f"trade-{number}",
                    "environment": "production",
                }
            )
            for kind in ("outcome", "acceptance", *(["refund"] if number == "refunded" else [])):
                session.add(
                    CustomerValueReceipt(
                        receipt_id=f"{number}-{kind}",
                        receipt_kind=kind,
                        verification_status="verified",
                        customer_ref=(
                            "paid-user:8"
                            if number == "wrong-user"
                            else "paid-user:9" if number == "other-owner" else "paid-user:7"
                        ),
                        customer_goal_id=(
                            "other-goal"
                            if number == "unrelated"
                            else "goal-deferred" if number == "deferred" else "goal-a"
                        ),
                        artifact_id=(
                            "artifact-wrong" if number == "wrong-artifact" else "artifact-a"
                        ),
                        evidence_json=json.dumps({"artifact_sha256": "b" * 64}),
                        order_no=number,
                        currency="CNY",
                        environment="production",
                        evidence_digest="a" * 64,
                        occurred_at=start + timedelta(hours=2),
                    )
                )
        session.commit()
    monkeypatch.setattr(
        customer_value_payment_source,
        "load_authoritative_payment_orders",
        lambda _: {
            "source_available": True,
            "source_authoritative": True,
            "source_owner": "signed_gateway",
            "orders": orders,
        },
    )
    business = runtime._business_outcome(p.portfolio_status(decision_id))
    assert business["revenue_cents"] == 100
    assert business["paid_order_count"] == 1


def test_review_reallocates_released_resources_without_new_authorization(database, monkeypatch):
    caps = limits(min_roi_bps=-10_000, observation_hours=1)
    decision_id = proposal(
        database,
        caps=caps,
        rows=[
            opportunity("a", cost_cents=60, value_score=100),
            opportunity("b", cost_cents=60, value_score=50),
        ],
    )
    assert p.plan_portfolio(decision_id)["selected"] == ["a"]
    task = runtime._claim(decision_id, 7)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        held = usage.prepare_platform_call("test", "model", [], 100)
        usage.complete_platform_call(
            held, {"usage": {"prompt_tokens": 10, "completion_tokens": 10}}
        )
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    p.mutate_portfolio(
        decision_id,
        lambda _r, _p, s, _db: s.update(
            started_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat()
        ),
    )
    monkeypatch.setattr(
        runtime, "_business_outcome", lambda _: {"status": "verified", "revenue_cents": 0}
    )
    report = runtime.review_portfolio(decision_id)
    assert report["reallocation"]["selected"] == ["b"]
    assert p.portfolio_status(decision_id)["limits"]["cost_cents"] == 100
    assert runtime._claim(decision_id, 7)["opportunity_id"] == "b"


def test_platform_model_hook_reserves_before_call_and_records_actual_usage(database, monkeypatch):
    from modstore_server import llm_chat_proxy, llm_key_resolver
    from modstore_server.services.llm import chat_dispatch_via_platform_only

    decision_id, task = claim_proposal(database)
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: "unit-test-key")
    calls = []

    async def dispatch(*args, **kwargs):
        calls.append(kwargs)
        state = p.portfolio_status(decision_id)
        assert len(state["tasks"]["a"]["calls"]) == 1
        return {
            "ok": True,
            "content": "done",
            "usage": {"prompt_tokens": 10, "completion_tokens": 1},
        }

    monkeypatch.setattr(llm_chat_proxy, "chat_dispatch", dispatch)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        response = asyncio.run(chat_dispatch_via_platform_only("test", "model", [], max_tokens=10))
    assert response["ok"] and len(calls) == 1
    assert "fallback_api_key" not in calls[0]
    assert (
        next(iter(p.portfolio_status(decision_id)["tasks"]["a"]["calls"].values()))["actual_tokens"]
        == 11
    )


def test_discovery_reuses_planner_and_filters_other_account_context(database, monkeypatch):
    from modstore_server import customer_value_payment_source, strategy_planner, task_router
    from modstore_server.db.identity import User
    from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket
    from modstore_server.services import llm

    with database() as session:
        for owner in (7, 8):
            session.add(
                User(
                    id=owner, username=f"owner-{owner}", password_hash="unused", is_admin=owner == 7
                )
            )
            session.add(CustomerServiceSession(id=owner, user_id=owner))
            session.add(
                CustomerServiceTicket(
                    id=owner,
                    session_id=owner,
                    user_id=owner,
                    ticket_no=f"CS-{owner}",
                    title="OUR DELIVERY GAP" if owner == 7 else "PRIVATE OTHER ACCOUNT",
                )
            )
        session.commit()
    monkeypatch.setattr(
        customer_value_payment_source,
        "load_authoritative_payment_orders",
        lambda _: {"source_available": True, "source_authoritative": True, "orders": []},
    )
    monkeypatch.setattr(
        task_router, "_load_all_employee_profiles", lambda: [{"id": "daily-orchestrator"}]
    )
    monkeypatch.setattr(llm, "resolve_platform_bench_llm", lambda: ("test", "model"))

    async def admission(*_args):
        return planning_budget(budget_source="existing_platform_subscription_quota", max_calls=1)

    monkeypatch.setattr(usage, "planning_admission", admission)
    monkeypatch.setattr(
        strategy_planner,
        "collect_context",
        lambda: {
            "assets": {"status": "unknown"},
            "repo": {"status": "unknown"},
            "domains": {"status": "unrated"},
        },
    )
    prompts = []

    async def complete(provider, model, messages, **_kwargs):
        prompts.append(json.dumps(messages, ensure_ascii=False))
        return {
            "ok": True,
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            "content": json.dumps(
                [
                    {
                        "title": f"Delivery improvement {index}",
                        "hypothesis": "observed customer gap",
                        "metric_id": "slo_availability",
                        "threshold": 0.99,
                        "direction": "max",
                        "window_days": 7,
                        "kill_criteria": ["stop if unchanged"],
                        "expected_value": 4,
                        "effort": 2,
                    }
                    for index in range(3)
                ]
            ),
        }

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", complete)
    result = asyncio.run(
        runtime.discover_portfolio_opportunities(
            owner_user_id=7, goal="Improve delivery", limits=limits()
        )
    )
    assert result["source"] == "llm" and len(result["opportunities"]) == 3
    assert "OUR DELIVERY GAP" in prompts[0] and "PRIVATE OTHER ACCOUNT" not in prompts[0]
    assert all(item["employee_id"] == "daily-orchestrator" for item in result["opportunities"])
    with database() as session:
        assert not session.execute(select(StrategicDecision)).scalars().all()


def test_dispatched_downstream_job_is_not_claimed_completed(database):
    decision_id, task = claim_proposal(database)
    runtime._finish(
        task,
        {
            "ok": True,
            "result": {
                "outputs": [{"handler": "local_queue", "status": "queued", "job_id": "job-1"}]
            },
        },
        1,
    )
    state = p.portfolio_status(decision_id)
    assert state["tasks"]["a"]["status"] == "unknown"
    assert state["halted"] is True


def test_worker_binding_restores_metered_scope_once_across_threads(database):
    decision_id, task = claim_proposal(database)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        binding = usage.bind_portfolio_worker("durable-queue:1", owner_user_id=7)
    runtime._finish(
        task, {"ok": True, "status": "queued", "worker_receipt_id": "durable-queue:1"}, 1
    )
    assert p.portfolio_status(decision_id)["tasks"]["a"]["status"] == "waiting"
    with pytest.raises(p.PortfolioError):
        runtime.execute_portfolio_worker(
            binding, owner_user_id=8, execute=lambda _: pytest.fail("cross-owner worker")
        )

    def worker(_task):
        held = usage.prepare_platform_call("test", "model", [], 10)
        assert held is not None
        usage.complete_platform_call(held, {"usage": {"prompt_tokens": 3, "completion_tokens": 4}})
        return {"ok": True, "status": "completed", "output": "durable result"}

    with ThreadPoolExecutor(max_workers=1) as pool:
        state = pool.submit(
            runtime.execute_portfolio_worker, binding, owner_user_id=7, execute=worker
        ).result()
    assert state["tasks"]["a"]["actual_tokens"] == 7
    assert state["tasks"]["a"]["execution_receipt"]["output"] == "durable result"
    assert state["tasks"]["a"]["status"] == "completed"
    with pytest.raises(p.PortfolioError):
        runtime.execute_portfolio_worker(
            binding, owner_user_id=7, execute=lambda _: pytest.fail("worker replay")
        )


def test_unmetered_remote_delegate_blocks_before_external_submission(database, monkeypatch):
    from modstore_server import cursor_delegate_handler, para_delegate_handler

    decision_id, task = claim_proposal(database)
    monkeypatch.setattr(
        para_delegate_handler, "_post_webhook", lambda *_: pytest.fail("unmetered Para submission")
    )
    monkeypatch.setattr(
        cursor_delegate_handler,
        "_try_cursor_sdk_prompt",
        lambda *_args, **_kwargs: pytest.fail("unmetered Cursor submission"),
    )
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        for delegate in (
            para_delegate_handler.dispatch_para_delegate,
            cursor_delegate_handler.dispatch_cursor_delegate,
        ):
            result = delegate(task="approved bounded task", employee_id="test-qa-runner")
            assert result["status"] == "blocked_strategy_budget_adapter"
            assert not result["accepted"] and not result["queued"]


def test_planning_spends_only_observed_subscription_quota_and_persists_actual_usage(
    database, monkeypatch
):
    from modstore_server import llm_chat_proxy, llm_key_resolver
    from modstore_server.db.llm_chat import LlmCallLog, LlmClientRequest
    from modstore_server.services.llm import chat_dispatch_via_platform_only

    seed_owner(database)
    admission = planning_budget(budget_source="existing_platform_subscription_quota")
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: "test-key")

    async def dispatch(*_args, **_kwargs):
        with database() as session:
            assert set(session.execute(select(LlmClientRequest.state)).scalars()) == {"processing"}
        return {"ok": True, "usage": {"prompt_tokens": 12, "completion_tokens": 3}}

    monkeypatch.setattr(llm_chat_proxy, "chat_dispatch", dispatch)
    with usage.planning_usage_scope(7, admission) as context:
        asyncio.run(chat_dispatch_via_platform_only("test", "model", [], max_tokens=20))
        assert context["receipts"][0]["actual_tokens"] == 15
        assert context["receipts"][0]["supplier_cost_cents"] is None
        with pytest.raises(p.PortfolioError, match="single-call"):
            asyncio.run(chat_dispatch_via_platform_only("test", "model", [], max_tokens=20))
    with database() as session:
        assert session.execute(select(LlmCallLog.total_tokens)).scalar_one() == 15


def test_planning_unknown_quota_never_admits_model_call(monkeypatch):
    from modstore_server import llm_quota_monitor

    async def snapshot(**_kwargs):
        return {
            "providers": [
                {
                    "provider": "test",
                    "state": "healthy",
                    "visibility": "usage_only",
                    "remaining_percent": None,
                }
            ]
        }

    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", snapshot)
    assert asyncio.run(usage.planning_admission("test", "model")) is None


def test_budgeted_raw_proxy_does_not_retry_uncertain_paid_request(database, monkeypatch):
    from modstore_server import llm_chat_proxy, llm_key_resolver, llm_litellm_router

    caps = limits()
    caps["tariffs"][0]["provider"] = "openai"
    decision_id, task = claim_proposal(database, caps=caps)
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: "unit-key")
    monkeypatch.setattr(llm_key_resolver, "platform_base_url", lambda _: None)

    calls = []

    async def no_router(*_args, **_kwargs):
        return None

    async def fail(*_args, **_kwargs):
        calls.append(True)
        return {"ok": False, "status": 503, "error": "connection lost"}

    monkeypatch.setattr(llm_litellm_router, "chat", no_router)
    monkeypatch.setattr(llm_chat_proxy, "chat_openai_compatible", fail)
    monkeypatch.setenv("MODSTORE_LLM_PRIMARY_MAX_ATTEMPTS", "5")
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        result = asyncio.run(
            llm_chat_proxy.chat_dispatch(
                "openai",
                api_key="unit-key",
                base_url=None,
                model="model",
                messages=[],
                fallback_provider="openai",
                fallback_model="fallback",
                timeout_fallback_s=10,
            )
        )
    assert not result["ok"] and len(calls) == 1
    assert p.portfolio_status(decision_id)["halted"]


def test_direct_model_dispatch_cannot_bypass_lease_or_usage(database, monkeypatch):
    from modstore_server import llm_chat_proxy, llm_key_resolver, llm_litellm_router

    calls = []
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: "unit-key")
    monkeypatch.setattr(llm_key_resolver, "platform_base_url", lambda _: None)

    async def upstream(*_args, **_kwargs):
        calls.append(True)
        usage.require_call_reservation()
        return {"ok": True, "usage": {"prompt_tokens": 10, "completion_tokens": 4}}

    monkeypatch.setattr(llm_litellm_router, "chat", upstream)
    kwargs = {
        "api_key": "unit-key",
        "base_url": None,
        "model": "model",
        "messages": [],
        "max_tokens": 30,
    }
    with usage.portfolio_usage_scope("NONEXISTENT-NO-APPROVAL", "a", "NO-LEASE"):
        with pytest.raises(p.PortfolioError):
            asyncio.run(llm_chat_proxy.chat_dispatch("openai", **kwargs))
    assert not calls
    caps = limits()
    caps["tariffs"][0]["provider"] = "openai"
    decision_id, task = claim_proposal(database, caps=caps)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        asyncio.run(llm_chat_proxy.chat_dispatch("openai", **kwargs))
    call = next(iter(p.portfolio_status(decision_id)["tasks"]["a"]["calls"].values()))
    assert len(calls) == 1 and call["status"] == "settled" and call["actual_tokens"] == 14


def test_parallel_planning_shares_one_durable_owner_slot(database):

    seed_owner(database)
    barrier = Barrier(2)
    admission = planning_budget()

    def reserve():
        with usage.planning_usage_scope(7, admission):
            barrier.wait(timeout=5)
            try:
                return usage.prepare_platform_call("test", "model", [], 20)
            except p.PortfolioError:
                return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservations = list(executor.map(lambda _: reserve(), range(2)))
    assert sum(value is not None for value in reservations) == 1
    reservation = next(value for value in reservations if value is not None)
    usage.complete_platform_call(
        reservation, {"usage": {"prompt_tokens": 12, "completion_tokens": 3}}
    )
    with usage.planning_usage_scope(7, admission):
        assert usage.prepare_platform_call("test", "model", [], 20)


def test_execution_boundary_observes_admin_stop(database):
    decision_id, task = claim_proposal(database)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        assert usage.remaining_execution_seconds() > 0
        p.stop_portfolio(decision_id, owner_user_id=7, actor="admin:7", reason="operator stop")
        with pytest.raises(p.PortfolioError):
            usage.remaining_execution_seconds()


@pytest.mark.parametrize("account_state", ["disabled", "suspended", "blocked", "deleted"])
def test_owner_freeze_blocks_new_reservations_and_dispatch_but_settles_prior_usage(
    database, account_state
):
    from modstore_server.db.identity import User

    decision_id, task = claim_proposal(database)
    calls = []

    async def outbound(*_args, **_kwargs):
        calls.append(True)
        return {"ok": True}

    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        reservation = usage.prepare_platform_call("test", "model", [], 20)
        with database() as session:
            session.get(User, 7).account_state = account_state
            session.commit()
        # A completed in-flight call is still accounted after authority is revoked.
        usage.complete_platform_call(
            reservation, {"usage": {"prompt_tokens": 12, "completion_tokens": 3}}
        )
        with pytest.raises(p.PortfolioError, match="active administrator"):
            usage.prepare_platform_call("test", "model", [], 20)
        with usage.platform_call_reservation(reservation):
            with pytest.raises(p.PortfolioError, match="active administrator"):
                asyncio.run(
                    usage.dispatch_budgeted(outbound, "test", {"model": "model", "messages": []})
                )
    state = p.portfolio_status(decision_id)
    call = next(iter(state["tasks"]["a"]["calls"].values()))
    assert call["status"] == "settled" and call["actual_tokens"] == 15
    assert not calls and len(state["tasks"]["a"]["calls"]) == 1


def test_worker_and_planning_reservations_recheck_frozen_owner(database):
    from modstore_server.db.identity import User

    decision_id, task = claim_proposal(database)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        binding = usage.bind_portfolio_worker("queue:revoked", owner_user_id=7)
    runtime._finish(task, {"ok": True, "status": "queued", "worker_receipt_id": "queue:revoked"}, 1)
    with database() as session:
        session.get(User, 7).account_state = "suspended"
        session.commit()
    with pytest.raises(p.PortfolioError, match="active administrator"):
        runtime.execute_portfolio_worker(
            binding, owner_user_id=7, execute=lambda _task: pytest.fail("revoked worker dispatched")
        )
    admission = planning_budget()
    with usage.planning_usage_scope(7, admission):
        with pytest.raises(p.PortfolioError, match="active administrator"):
            usage.prepare_platform_call("test", "model", [], 20)
    assert p.portfolio_status(decision_id)["tasks"]["a"]["status"] == "waiting"


@pytest.mark.parametrize("error_type", [asyncio.CancelledError, AssertionError, TimeoutError])
@pytest.mark.parametrize("entrypoint", ["platform", "direct"])
def test_model_failure_preserves_original_exception_and_unsettled_cost_hold(
    database, monkeypatch, error_type, entrypoint
):
    from modstore_server import llm_chat_proxy, llm_key_resolver
    from modstore_server.services.llm import chat_dispatch_via_platform_only

    decision_id, task = claim_proposal(database)
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: "unit-key")

    async def fail(*_args, **_kwargs):
        raise error_type("original model failure")

    monkeypatch.setattr(llm_chat_proxy, "chat_dispatch", fail)
    with usage.portfolio_usage_scope(decision_id, "a", task["lease_token"]):
        call = (
            chat_dispatch_via_platform_only("test", "model", [], max_tokens=20)
            if entrypoint == "platform"
            else usage.dispatch_budgeted(
                fail,
                "test",
                {"api_key": "unit-key", "model": "model", "messages": [], "max_tokens": 20},
            )
        )
        with pytest.raises(error_type, match="original model failure"):
            asyncio.run(call)
    state = p.portfolio_status(decision_id)
    calls = list(state["tasks"]["a"]["calls"].values())
    assert state["halted"] and len(calls) == 1
    assert calls[0]["status"] == "unknown" and calls[0]["reserved_cost_cents"] > 0
    assert "accrued_cost_cents" not in calls[0]


def test_strategy_streaming_rejects_unmetered_adapter_before_outbound(database):
    from modstore_server import llm_chat_proxy, llm_litellm_router

    kwargs = {"api_key": "unused", "base_url": None, "model": "model", "messages": []}

    async def consume():
        return [item async for item in llm_chat_proxy.chat_dispatch_stream("openai", **kwargs)]

    with usage.portfolio_usage_scope("unapproved", "a", "none"):
        with pytest.raises(p.PortfolioError):
            asyncio.run(consume())
        with pytest.raises(p.PortfolioError):
            llm_litellm_router.stream_events("openai", **kwargs)


def test_google_enforces_output_cap_and_accounts_thinking_tokens(monkeypatch):
    from types import SimpleNamespace

    from modstore_server import llm_chat_providers, llm_chat_proxy

    payloads = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **kwargs):
            payloads.append(kwargs["json"])
            return SimpleNamespace(
                status_code=200,
                text=json.dumps(
                    {
                        "candidates": [{"content": {"parts": [{"text": "done"}]}}],
                        "usageMetadata": {
                            "promptTokenCount": 10,
                            "candidatesTokenCount": 3,
                            "thoughtsTokenCount": 5,
                            "totalTokenCount": 18,
                        },
                    }
                ),
            )

    monkeypatch.setattr(llm_chat_proxy.httpx, "AsyncClient", Client)
    result = asyncio.run(llm_chat_providers.chat_google("key", "model", [], max_tokens=20))
    assert payloads[0]["generationConfig"]["maxOutputTokens"] == 20
    assert result["usage"]["prompt_tokens"] == 10
    assert result["usage"]["completion_tokens"] == 8


def test_preregistered_metric_window_freezes_miss_and_stops_investment(
    database, monkeypatch, tmp_path
):
    target = {
        "hypothesis": "availability improves",
        "metric_id": "slo_availability",
        "threshold": 0.99,
        "direction": "max",
        "window_days": 1,
        "kill_criteria": ["stop on miss"],
    }
    decision_id, task = claim_proposal(database, rows=[opportunity(hypothesis=target)])
    runtime._finish(task, {"ok": True, "status": "completed"}, 1)
    start = datetime.now(UTC) - timedelta(days=2)
    p.mutate_portfolio(
        decision_id, lambda _r, _p, s, _db: s["tasks"]["a"].update(started_at=start.isoformat())
    )
    report_path = tmp_path / "measured.json"
    sample = {
        "generated_at": (start + timedelta(hours=12)).isoformat(),
        "readings": {"SLO-API-01": {"reading_numeric": 0.5}},
    }
    report_path.write_text(json.dumps(sample))
    monkeypatch.setenv("MODSTORE_SLO_REPORT_PATH", str(report_path))
    monkeypatch.setattr(
        runtime, "_business_outcome", lambda _: {"status": "unknown", "revenue_cents": None}
    )
    first = runtime.review_portfolio(decision_id)
    assert first["decision"] == "stop"
    assert first["hypotheses"][0]["verdict"] == "miss"
    digest = first["hypotheses"][0]["snapshot_sha256"]
    sample["readings"]["SLO-API-01"]["reading_numeric"] = 1.0
    report_path.write_text(json.dumps(sample))
    assert runtime.review_portfolio(decision_id)["hypotheses"][0]["snapshot_sha256"] == digest
