"""Failure-boundary contracts for XiaoC's real LangGraph cognition cycle."""

from __future__ import annotations

import asyncio
import copy
import json
from contextlib import asynccontextmanager, contextmanager

import pytest

from modstore_server import xiaoc_life_runtime as runtime
from modstore_server.xiaoc_life_cognition import cognition_messages, parse_decision


class Store:
    def __init__(self):
        self.state = {
            "identity_id": "enterprise:xiaoc",
            "revision": 1,
            "owner_user_id": 17,
            "level": 5,
            "paused": False,
            "mission": "改善产品与持续学习",
            "policy": {"exploration_percent": 0},
            "goals": [],
            "interests": [],
            "events": [],
        }
        self.claim = {
            "cycle_id": "cycle-1",
            "lease_token": "lease-1",
            "policy_revision": 1,
            "owner_user_id": 17,
            "domain": "enterprise",
            "reserved_tokens": 32768,
            "state": self.state,
        }
        self.active = True
        self.claimed = False
        self.finished = []
        self.phases = []
        self.checkpoints = []
        self.graph_started = False
        self.act_admitted = False

    def read_state(self):
        return copy.deepcopy(self.state)

    def claim_cycle(self, **_kwargs):
        if self.claimed:
            return None
        self.claimed = True
        return self.claim

    def cycle_active(self, claim):
        return self.active and claim["lease_token"] == self.claim["lease_token"]

    @contextmanager
    def life_execution_scope(self, _claim):
        yield

    def finish_cycle(self, claim, **result):
        self.finished.append(result)
        return {"cycle_id": claim["cycle_id"], **result}

    def begin_cycle_graph(self, claim):
        if not self.cycle_active(claim) or self.graph_started:
            return False
        self.graph_started = True
        return True

    def pending_native_act_claim(self):
        return None

    def admit_cycle_act(self, claim):
        if not self.cycle_active(claim) or self.act_admitted:
            return False
        self.act_admitted = True
        return True

    def record_cycle_phase(self, claim, phase):
        if phase != "reflect":
            assert self.cycle_active(claim)
        self.phases.append(phase)

    def record_cycle_checkpoint(self, claim, phase, **details):
        self.checkpoints.append((phase, details))

    def mark_model_attempt(self, claim):
        self.claim["outbound_attempted"] = True

    def record_cycle_step(self, claim, **details):
        assert self.cycle_active(claim)
        self.claim.setdefault("steps", []).append(details)


@pytest.fixture
def ports(monkeypatch):
    from modstore_server import (
        llm_api,
        strategic_portfolio_usage,
        strategy_planner,
        xiaoc_life_reconciliation,
    )
    from modstore_server.services import llm

    store = Store()
    calls = []
    current = {}
    monkeypatch.setattr(runtime, "_store", lambda: store)

    from langgraph.checkpoint.memory import InMemorySaver

    test_saver = InMemorySaver()

    @asynccontextmanager
    async def memory_checkpointer():
        yield test_saver

    monkeypatch.setattr(runtime, "native_life_checkpointer", memory_checkpointer)
    monkeypatch.setattr(xiaoc_life_reconciliation, "reconcile_goals", lambda: None)
    monkeypatch.setattr(xiaoc_life_reconciliation, "reconcile_usage", lambda: None)
    monkeypatch.setattr(runtime.CyclePorts, "approved_portfolio", lambda self: None)
    monkeypatch.setattr(
        strategy_planner,
        "collect_context",
        lambda: {
            "assets": {"status": "ok", "model_count": 3},
            "repo": {"status": "ok", "numeric_signals": {"failures": 2}},
            "domains": {"status": "unrated", "domains": []},
        },
    )

    async def route(_db, user_id, *, platform_only):
        assert user_id == 17 and platform_only is True
        return {"provider": "test", "model": "test-model"}

    monkeypatch.setattr(llm_api, "resolve_default_llm_route", route)

    async def admission(_provider, _model, *, owner_user_id):
        assert owner_user_id == 17
        return {
            "provider": "test",
            "model": "test-model",
            "max_total_tokens": 32768,
            "max_output_tokens": 1600,
            "max_calls": 1,
        }

    @contextmanager
    def scope(owner, admitted):
        current.clear()
        current.update(owner=owner, admission=admitted, receipts=[])
        yield current

    def decision(messages):
        observation = json.loads(messages[1]["content"])["observations"][0]
        return {
            "action": "propose",
            "summary": "建议核对失败事件。",
            "evidence_refs": [observation["ref"]],
            "goal": {
                "title": "核对失败模式",
                "description": "按原记录验证原因并提出实验。",
                "evidence_refs": [observation["ref"]],
            },
            "interests": [
                {
                    "topic": "可恢复任务执行",
                    "reason": "观察到真实失败信号。",
                    "confidence": 0.5,
                    "evidence_refs": [observation["ref"]],
                }
            ],
            "self_assessment": None,
        }

    async def chat(provider, model, messages, **kwargs):
        calls.append({"provider": provider, "model": model, "messages": messages, **kwargs})
        current["receipts"].append({"status": "settled", "actual_tokens": 42})
        return {
            "ok": True,
            "content": json.dumps(decision(messages), ensure_ascii=False),
        }

    monkeypatch.setattr(strategic_portfolio_usage, "planning_admission", admission)
    monkeypatch.setattr(strategic_portfolio_usage, "planning_usage_scope", scope)
    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", chat)
    return store, calls, current, llm, decision


def test_real_graph_proposes_without_claiming_goal_completed_or_self_approval(ports):
    store, calls, current, _, _ = ports
    result = asyncio.run(runtime.tick_async())
    assert store.phases == ["observe", "decide", "act", "reflect"]
    assert [phase for phase, _ in store.checkpoints] == ["act", "reflect"]
    assert store.checkpoints[-1][1]["actual_tokens"] == 42
    assert len(calls) == 1
    assert current["owner"] == 17
    assert result["actual_tokens"] == 42
    assert result["goals"][0]["status"] == "proposed"
    assert result["goals"][0]["blocked_reason"] == "awaiting_portfolio_policy"
    assert "decision_id" not in result["goals"][0]
    assert result["details"]["model_note_status"] == "unverified_suggestion"
    assert "尚未执行" in result["summary"]
    assert len(store.finished) == 1


@pytest.mark.parametrize("level,paused", [(1, False), (2, False), (3, False), (6, True)])
def test_passive_modes_and_pause_never_claim_or_call_model(ports, level, paused):
    store, calls, *_ = ports
    store.state.update(level=level, paused=paused)
    assert asyncio.run(runtime.tick_async())["status"] == "idle"
    assert not store.claimed and not store.finished and not calls


def test_durable_claim_denial_does_not_replay_model(ports):
    store, calls, *_ = ports
    asyncio.run(runtime.tick_async())
    assert asyncio.run(runtime.tick_async())["status"] == "idle"
    assert len(calls) == 1 and len(store.finished) == 1


def test_downgrade_during_model_return_records_spend_but_creates_no_goal(ports, monkeypatch):
    store, calls, current, llm, decision = ports

    async def downgraded(provider, model, messages, **kwargs):
        calls.append(messages)
        current["receipts"].append({"status": "settled", "actual_tokens": 43})
        store.active = False
        return {"ok": True, "content": json.dumps(decision(messages))}

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", downgraded)
    result = asyncio.run(runtime.tick_async())
    assert result["status"] == "blocked"
    assert result["actual_tokens"] == 43
    assert not result["goals"] and not result["interests"]
    assert result["details"]["reason"] == "life_policy_changed_or_lease_lost"


def test_unknown_usage_retains_hold_and_never_learns_from_model_output(ports, monkeypatch):
    _store, calls, current, llm, decision = ports

    async def unknown(provider, model, messages, **kwargs):
        calls.append(messages)
        current["receipts"].append({"status": "unknown", "actual_tokens": None})
        return {"ok": True, "content": json.dumps(decision(messages))}

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", unknown)
    result = asyncio.run(runtime.tick_async())
    assert result["status"] == "blocked" and result["actual_tokens"] is None
    assert not result["goals"] and not result["interests"]
    assert result["details"]["reason"] == "model_usage_unknown"


def test_unknown_platform_quota_blocks_before_call(ports, monkeypatch):
    from modstore_server import strategic_portfolio_usage

    async def unavailable(*args, **kwargs):
        return None

    monkeypatch.setattr(strategic_portfolio_usage, "planning_admission", unavailable)
    result = asyncio.run(runtime.tick_async())
    assert result["status"] == "blocked" and result["actual_tokens"] == 0
    assert not ports[1]


def test_small_remaining_lane_budget_never_sends_over_budget_prompt(ports):
    ports[0].claim["reserved_tokens"] = 128
    result = asyncio.run(runtime.tick_async())
    assert result["details"]["reason"] == "life_cycle_prompt_budget_exhausted"
    assert result["actual_tokens"] == 0 and not ports[1]


def test_model_cannot_forge_fact_refs_goal_status_or_executor_binding(ports):
    _, _, _, _, decision = ports
    messages, refs = cognition_messages(
        ports[0].state, "enterprise", [{"ref": "observed:1", "text": "事实"}]
    )
    valid = decision(messages)
    with pytest.raises(ValueError, match="unobserved"):
        invalid = copy.deepcopy(valid)
        invalid["goal"]["evidence_refs"] = ["fabricated:source"]
        parse_decision(json.dumps(invalid), refs=refs, level=5, domain="enterprise")
    for field, value in [("status", "completed"), ("decision_id", "foreign-portfolio")]:
        invalid = copy.deepcopy(valid)
        invalid["goal"][field] = value
        with pytest.raises(ValueError):
            parse_decision(json.dumps(invalid), refs=refs, level=5, domain="enterprise")


def test_unconfigured_research_never_falls_back_to_paid_search_or_model(ports, monkeypatch):
    from modstore_server import research_tools

    ports[0].claim["domain"] = "exploration"
    monkeypatch.setattr(research_tools, "searxng_instance_url", lambda: "")
    result = asyncio.run(runtime.run_claimed_cycle(ports[0].claim))
    assert result["details"]["reason"] == "research_not_configured"
    assert result["actual_tokens"] == 0 and not ports[1]


def test_research_uses_actual_sources_once_and_preserves_their_limits(ports, monkeypatch):
    from modstore_server import research_tools

    store = ports[0]
    store.claim["domain"] = "exploration"
    store.state["interests"] = [{"topic": "事务恢复", "evidence_refs": ["experience:1"]}]
    history = [{"ref": f"old:{index}", "text": "历史反馈"} for index in range(12)]
    monkeypatch.setattr(runtime, "feedback_facts", lambda _state: copy.deepcopy(history))
    queries = []
    monkeypatch.setattr(research_tools, "searxng_instance_url", lambda: "https://search.example")

    async def search(query, max_results):
        queries.append((query, max_results))
        return [
            {
                "url": "https://docs.example/transactions",
                "title": "事务恢复",
                "content": "官方文档",
            }
        ]

    monkeypatch.setattr(research_tools, "searxng_search", search)
    result = asyncio.run(runtime.run_claimed_cycle(store.claim))
    assert queries == [("事务恢复", 3)]
    sources = result["details"]["sources"]
    web = next(row for row in sources if row["ref"].startswith("web:"))
    assert web["url"] == "https://docs.example/transactions"
    assert web["interpretation"] == "retrieved_source_not_verified_claim"
    observations = json.loads(ports[1][0]["messages"][1]["content"])["observations"]
    assert observations[0]["ref"] == web["ref"]
    assert any(row["ref"] == "old:0" for row in observations)
    assert "尚未执行" in result["summary"]


@pytest.mark.parametrize(
    "facts,reason",
    [
        ([{"text": "无来源"}], "no_observed_context"),
        (
            [{"ref": "receipt:large", "business_feedback": {"measurement": "测" * 1500}}],
            "life_cycle_prompt_budget_exhausted",
        ),
    ],
)
def test_invalid_cognition_context_blocks_before_model_and_learning(
    ports, monkeypatch, facts, reason
):
    store, calls, *_ = ports
    original = copy.deepcopy(store.state)

    async def observe(_self, _state):
        return {"facts": facts}

    monkeypatch.setattr(runtime.CyclePorts, "observe", observe)
    result = asyncio.run(runtime.run_claimed_cycle(store.claim))
    assert result["status"] == "blocked" and result["details"]["reason"] == reason
    assert result["actual_tokens"] == 0 and not calls
    assert not result["goals"] and not result["interests"] and not result["self_model"]
    assert store.state == original and len(store.finished) == 1


def test_public_prompt_excludes_private_account_context_and_raw_paths(ports, monkeypatch):
    from modstore_server import strategy_planner

    monkeypatch.setattr(
        strategy_planner,
        "collect_context",
        lambda: {
            "assets": {"status": "ok", "model_count": 2},
            "private_memory": "SECRET_PRIVATE_CUSTOMER",
            "domains": {
                "status": "unrated",
                "source": "/private/account/file.json",
                "domains": [],
            },
        },
    )
    asyncio.run(runtime.tick_async())
    text = json.dumps(ports[1][0]["messages"])
    assert "SECRET_PRIVATE_CUSTOMER" not in text
    assert "/private/account/file.json" not in text


def test_prior_interests_and_self_assessment_change_next_model_context(ports):
    store = ports[0]
    store.state["interests"] = [
        {
            "topic": "恢复",
            "reason": "原实验失败",
            "confidence": 0.3,
            "evidence_refs": ["experiment:failed"],
        }
    ]
    store.state["self_model"] = {
        "title": "规划不足",
        "description": "应先检验目标与回执的对应关系",
        "status": "hypothesis",
        "owner_user_id": 17,
    }
    asyncio.run(runtime.tick_async())
    payload = json.loads(ports[1][0]["messages"][1]["content"])
    assert payload["interests"][0]["reason"] == "原实验失败"
    assert payload["interests"][0]["confidence"] == 0.3
    assert payload["prior_self_assessment"]["description"] == "应先检验目标与回执的对应关系"


def test_newest_first_events_schedule_unvisited_then_least_recent_domain(ports):
    state = ports[0].state
    state.update(
        level=6,
        interests=[{"topic": "恢复"}],
        events=[{"kind": "enterprise"}, {"kind": "reflection"}, {"kind": "enterprise"}],
    )
    state["policy"]["exploration_percent"] = 20
    assert runtime._domain_order(state)[0] == "exploration"
    state["events"].insert(0, {"kind": "exploration"})
    assert runtime._domain_order(state)[0] == "reflection"
    state["interests"] = []
    assert "exploration" not in runtime._domain_order(state)


def test_unreceipted_model_rejection_does_not_invent_free_usage(ports, monkeypatch):
    async def denied(*args, **kwargs):
        raise ValueError("another planning call owns the account quota slot")

    monkeypatch.setattr(ports[3], "chat_dispatch_via_platform_only", denied)
    result = asyncio.run(runtime.tick_async())
    assert result["status"] == "failed" and result["actual_tokens"] is None
    assert ports[0].claim["outbound_attempted"] and not ports[1]


@pytest.mark.parametrize(
    "task_status,goal_status,actual",
    [
        ("completed", "execution_verified", 12),
        ("waiting", "active", None),
        ("failed", "failed", 12),
    ],
)
def test_existing_portfolio_receipts_do_not_confuse_queued_and_completed(
    ports, monkeypatch, task_status, goal_status, actual
):
    from modstore_server import strategic_portfolio, strategic_portfolio_runtime

    before = {
        "decision_id": "portfolio-1",
        "status": "executing",
        "tasks": {},
        "opportunities": [{"opportunity_id": "op-1", "depends_on": [], "tokens": 100}],
        "plan": {"selected": ["op-1"]},
    }
    current = {"value": copy.deepcopy(before)}
    goal = {
        "id": "goal-1",
        "title": "修复",
        "domain": "enterprise",
        "status": "approved",
        "decision_id": "portfolio-1",
        "evidence_refs": ["source:1"],
    }
    monkeypatch.setattr(
        runtime.CyclePorts,
        "approved_portfolio",
        lambda self: {"goal": goal, "snapshot": before},
    )
    monkeypatch.setattr(strategic_portfolio, "plan_portfolio", lambda *a, **k: before["plan"])
    monkeypatch.setattr(
        strategic_portfolio,
        "portfolio_status",
        lambda *a, **k: copy.deepcopy(current["value"]),
    )

    def execute(*args, **kwargs):
        current["value"]["tasks"]["op-1"] = {
            "status": task_status,
            "calls": {"model-call-1": {"status": "settled", "actual_tokens": 12}},
        }
        return {"processed": 1}

    monkeypatch.setattr(strategic_portfolio_runtime, "run_portfolio_cycle", execute)
    result = asyncio.run(runtime.tick_async())
    assert not ports[1]
    assert result["actual_tokens"] == actual
    assert result["goals"][0]["status"] == goal_status
    if goal_status == "execution_verified":
        assert result["goals"][0]["outcome_status"] == "pending_independent_business_measurement"


def test_portfolio_task_larger_than_cycle_reservation_never_dispatches(ports, monkeypatch):
    from modstore_server import strategic_portfolio, strategic_portfolio_runtime

    before = {
        "decision_id": "portfolio-1",
        "status": "approved",
        "tasks": {},
        "opportunities": [{"opportunity_id": "op-1", "depends_on": [], "tokens": 100000}],
        "plan": {"selected": ["op-1"]},
    }
    monkeypatch.setattr(
        runtime.CyclePorts,
        "approved_portfolio",
        lambda self: {
            "goal": {"id": "goal-1", "decision_id": "portfolio-1"},
            "snapshot": before,
        },
    )
    monkeypatch.setattr(strategic_portfolio, "plan_portfolio", lambda *a, **k: before["plan"])
    monkeypatch.setattr(strategic_portfolio, "portfolio_status", lambda *a, **k: before)
    monkeypatch.setattr(
        strategic_portfolio_runtime,
        "run_portfolio_cycle",
        lambda *a, **k: pytest.fail("must not dispatch"),
    )
    ports[0].state["owner_user_id"] = 17
    assert runtime._cycle_reservation(ports[0].state, "enterprise") == 32768
    ports[0].state["goals"] = [{"decision_id": "portfolio-1", "domain": "enterprise"}]
    assert runtime._cycle_reservation(ports[0].state, "enterprise") == 100000
    result = asyncio.run(runtime.tick_async())
    assert result["details"]["reason"] == "portfolio_task_exceeds_life_cycle_budget"
    assert result["actual_tokens"] == 0 and not ports[1]


def test_same_goal_across_cycles_preserves_execution_identity(ports, monkeypatch):
    store = ports[0]
    first = asyncio.run(runtime.tick_async())
    goal = {
        **first["goals"][0],
        "status": "approved",
        "decision_id": "original-portfolio",
    }
    store.state["goals"] = [goal]
    store.claimed = False
    store.claim["cycle_id"] = "second-cycle"
    store.graph_started = False
    store.act_admitted = False
    # This unit fixture has no strategic_decisions database. Exercise the
    # original-goal identity contract without pretending it has a real ledger.
    monkeypatch.setattr(runtime, "_cycle_reservation", lambda state, domain: 32768)
    second = asyncio.run(runtime.tick_async())
    assert second["goals"][0] == goal
    assert second["details"]["existing_goal_id"] == goal["id"]
    assert not second["details"].get("created_proposals")


@pytest.mark.parametrize("outcome", ["settled", "unknown", "downgraded", "restarted"])
@pytest.mark.parametrize("company_enabled", [False, True], ids=["legacy", "company"])
def test_graph_sql_lifecycle_and_platform_reservation_agree(
    tmp_path, monkeypatch, outcome, company_enabled
):
    """Only the supplier response is simulated; original SQL ledgers are real."""
    from datetime import timedelta

    from sqlalchemy import create_engine
    from sqlalchemy import event as sa_event
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    import modstore_server.strategic_company_resources as company
    from modstore_server import (
        llm_api,
        llm_chat_proxy,
        llm_key_resolver,
        llm_quota_monitor,
        models,
        strategic_portfolio,
        strategic_portfolio_usage,
        strategy_planner,
        xiaoc_life_reconciliation,
        xiaoc_life_store,
    )
    from modstore_server.db import db_base
    from modstore_server.db.identity import User
    from modstore_server.db.llm_chat import (
        ChatConversation,
        LlmCallLog,
        LlmClientRequest,
    )
    from modstore_server.db.strategic import StrategicDecision
    from modstore_server.db.xiaoc_life import XiaoCLifeEvent, XiaoCLifeState
    from modstore_server.strategic_layer import decision_ledger
    from modstore_server.xiaoc_life_policy import LifeUpdate

    engine = create_engine(f"sqlite:///{tmp_path / 'integrated-life.sqlite'}")

    @sa_event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        # The real CSV employee imports FHD's equivalent global hook. Exercise
        # the same FK contract even when this module is the first test collected.
        connection.execute("PRAGMA foreign_keys=ON")

    db_base.Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            XiaoCLifeState.__table__,
            XiaoCLifeEvent.__table__,
            ChatConversation.__table__,
            LlmCallLog.__table__,
            LlmClientRequest.__table__,
            StrategicDecision.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for module in (
        db_base,
        models,
        xiaoc_life_store,
        xiaoc_life_reconciliation,
        strategic_portfolio,
        strategic_portfolio_usage,
        decision_ledger,
    ):
        if hasattr(module, "get_session_factory"):
            monkeypatch.setattr(module, "get_session_factory", lambda: factory)
    with factory() as session:
        session.add(
            User(
                id=17,
                username="life-owner",
                password_hash="unused",
                is_admin=True,
                account_state="active",
            )
        )
        session.commit()
    company_id = None
    if company_enabled:
        monkeypatch.setenv(
            company.CONTROL_ENV,
            json.dumps(
                {
                    "scope": "life-company",
                    "authorizer_user_ids": [17],
                    "eligible_owner_user_ids": [17],
                }
            ),
        )
        funding = company.create_company_proposal(
            authorizer_user_id=17,
            period="life-tests",
            idempotency_key="life-tests",
            member_owner_ids=[17],
            limits={
                "cost_cents": 1000,
                "tokens": 100000,
                "compute_seconds": 600,
                "max_parallel": 1,
                "expires_at": (xiaoc_life_store.utcnow() + timedelta(days=1)).isoformat(),
                "tariffs": [
                    {
                        "provider": "test",
                        "model": "model",
                        "input_cents_per_million": 100,
                        "output_cents_per_million": 100,
                        "source": "approved-test-tariff",
                    }
                ],
            },
        )["decision"]
        company_id = funding["decision_id"]
        company.authorize_company(
            company_id,
            authorizer_user_id=17,
            actor="admin:17",
            expected_proposal_sha256=funding["decision_payload"]["proposal_sha256"],
        )
    state = xiaoc_life_store.read_state()
    xiaoc_life_store.update_settings(
        LifeUpdate(
            expected_revision=state["revision"],
            level=5,
            policy={
                "daily_token_limit": 100000,
                "daily_cycle_limit": 10,
                "exploration_percent": 20,
                "authorization_expires_at": (
                    xiaoc_life_store.utcnow() + timedelta(days=1)
                ).isoformat(),
            },
        ),
        actor_user_id=17,
    )
    monkeypatch.setattr(
        strategy_planner,
        "collect_context",
        lambda: {
            "assets": {"status": "ok", "model_count": 1},
            "repo": {"status": "ok", "numeric_signals": {"failures": 1}},
        },
    )

    async def route(_db, user_id, *, platform_only):
        assert user_id == 17 and platform_only is True
        return {"provider": "test", "model": "model"}

    monkeypatch.setattr(llm_api, "resolve_default_llm_route", route)
    monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: "test-only-key")

    async def quota(**kwargs):
        return {
            "providers": [
                {
                    "provider": "test",
                    "state": "healthy",
                    "visibility": "exact",
                    "resources": [{"resource": "general", "remaining_percent": 80}],
                }
            ]
        }

    monkeypatch.setattr(llm_quota_monitor, "platform_quota_snapshot", quota)
    calls = []

    async def transport(provider, **kwargs):
        calls.append(provider)
        with factory() as session:
            assert session.scalars(select(LlmClientRequest.state)).all() == [
                "processing",
                "processing",
            ]
        current = xiaoc_life_store.read_state()
        assert current["budget"]["reserved_tokens"] > 0
        if company_id:
            held = company.company_status(company_id, owner_user_id=17)["totals"]
            assert held["held"]["tokens"] > 0 and held["slots"] == 1
        if outcome == "downgraded":
            xiaoc_life_store.update_settings(
                LifeUpdate(expected_revision=current["revision"], level=2),
                actor_user_id=17,
            )
        source = json.loads(kwargs["messages"][1]["content"])["observations"][0]["ref"]
        response = {
            "ok": True,
            "provider": provider,
            "model": "model",
            "content": json.dumps(
                {
                    "action": "propose",
                    "summary": "提出验证建议",
                    "evidence_refs": [source],
                    "goal": {
                        "title": "核对失败",
                        "description": "用原回执查证失败原因",
                        "evidence_refs": [source],
                    },
                    "interests": [],
                    "self_assessment": None,
                }
            ),
        }
        if outcome != "unknown":
            response["usage"] = {"prompt_tokens": 12, "completion_tokens": 5}
        return response

    async def dispatch(provider, **kwargs):
        return await strategic_portfolio_usage.dispatch_budgeted(transport, provider, kwargs)

    monkeypatch.setattr(llm_chat_proxy, "chat_dispatch", dispatch)

    def check_company_receipt():
        if company_id:
            totals = company.company_status(company_id, owner_user_id=17)["totals"]
            assert totals["spent"]["tokens"] == (0 if outcome == "unknown" else 17)
            assert (totals["held"]["tokens"] > 0) is (outcome == "unknown")
            assert totals["slots"] == (1 if outcome == "unknown" else 0)

    try:
        if outcome == "restarted":
            original_finish = xiaoc_life_store.finish_cycle

            def crash_before_life_receipt(*args, **kwargs):
                raise OSError("simulated loss after the platform ledger committed")

            monkeypatch.setattr(xiaoc_life_store, "finish_cycle", crash_before_life_receipt)
            with pytest.raises(OSError, match="simulated loss"):
                asyncio.run(runtime.tick_async())
            monkeypatch.setattr(xiaoc_life_store, "finish_cycle", original_finish)
            later = xiaoc_life_store.utcnow() + timedelta(seconds=301)
            monkeypatch.setattr(xiaoc_life_store, "utcnow", lambda: later)
            monkeypatch.setattr(xiaoc_life_reconciliation, "utcnow", lambda: later)
            asyncio.run(runtime.tick_async())
            recovered = xiaoc_life_store.read_state()
            assert calls == ["test"]
            assert recovered["budget"]["used_tokens"] == 17
            assert recovered["budget"]["reserved_tokens"] == 0
            assert not recovered["goals"]
            assert any(
                event["kind"] == "reconciliation" and event["status"] == "verified"
                for event in recovered["events"]
            )
            check_company_receipt()
            return
        result = asyncio.run(runtime.tick_async())
        assert calls == ["test"]
        event = next(row for row in result["events"] if row["kind"] == "enterprise")
        if outcome == "unknown":
            assert result["budget"]["reserved_tokens"] > 0 and not result["goals"]
            assert event["actual_tokens"] is None and event["status"] == "unknown"
        else:
            assert result["budget"]["used_tokens"] == 17
            assert result["budget"]["reserved_tokens"] == 0
            assert bool(result["goals"]) is (outcome == "settled")
            assert event["status"] == ("completed" if outcome == "settled" else "policy_changed")
        with factory() as session:
            logs = session.scalars(select(LlmCallLog)).all()
            assert len(logs) == 1
            assert logs[0].total_tokens == (0 if outcome == "unknown" else 17)
            assert logs[0].estimated is (outcome == "unknown")
        check_company_receipt()
    finally:
        engine.dispose()


def test_model_timeout_without_receipt_keeps_unknown_cost(ports, monkeypatch):
    store, calls, _, llm, _ = ports

    async def timeout(*args, **kwargs):
        raise asyncio.TimeoutError("upstream response lost")

    monkeypatch.setattr(llm, "chat_dispatch_via_platform_only", timeout)
    result = asyncio.run(runtime.tick_async())
    assert result["status"] == "failed" and result["actual_tokens"] is None
    assert store.claim["outbound_attempted"] and not calls
    assert len(store.finished) == 1


def test_native_pre_act_restart_reuses_saved_decision_without_rebilling(ports, monkeypatch):
    """A second runner may resume only before any act invocation is admitted."""
    from modstore_server import xiaoc_life_reconciliation as reconciliation

    store, calls, *_ = ports
    original_admit = store.admit_cycle_act
    admitted = []

    def block_first_admission(claim):
        admitted.append("first")
        return False

    monkeypatch.setattr(store, "admit_cycle_act", block_first_admission)
    first = asyncio.run(runtime.tick_async())
    assert len(calls) == 1 and not store.finished and store.graph_started
    assert first["identity_id"] == store.state["identity_id"]

    # The test's receipt is simulated; actual production recovery independently
    # queries the persisted original model/portfolio execution ledger.
    monkeypatch.setattr(reconciliation, "_verified_usage", lambda steps, owner: 42)
    monkeypatch.setattr(store, "admit_cycle_act", original_admit)
    monkeypatch.setattr(store, "pending_native_act_claim", lambda: store.claim)
    resumed = asyncio.run(runtime.tick_async())
    assert resumed["actual_tokens"] == 42
    assert len(store.finished) == 1 and len(calls) == 1
    assert store.act_admitted and admitted == ["first"]

    # The CAS guard rejects a second resume instead of resending the act.
    assert original_admit(store.claim) is False
