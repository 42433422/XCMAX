"""Real SQL ownership, concurrent mode changes and lifecycle accounting."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from queue import Empty
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from modstore_server import xiaoc_life_api as api
from modstore_server import xiaoc_life_reconciliation as reconcile
from modstore_server import xiaoc_life_store as store
from modstore_server.api.deps import get_current_user
from modstore_server.db import db_base
from modstore_server.db.db_base import Base
from modstore_server.db.identity import User
from modstore_server.db.llm_chat import LlmClientRequest
from modstore_server.db.strategic import StrategicDecision
from modstore_server.db.xiaoc_life import XiaoCLifeEvent, XiaoCLifeState
from modstore_server.xiaoc_life_policy import LifePolicyError, LifeUpdate


def _prepare_database(engine, monkeypatch):
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            XiaoCLifeState.__table__,
            XiaoCLifeEvent.__table__,
            LlmClientRequest.__table__,
            StrategicDecision.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    for module in (store, api, reconcile, db_base):
        monkeypatch.setattr(module, "get_session_factory", lambda: factory)
    with factory() as session:
        session.add_all(
            [
                User(
                    id=i,
                    username=f"admin-{i}",
                    password_hash="unused",
                    is_admin=True,
                    account_state="active",
                )
                for i in (7, 8)
            ]
        )
        session.commit()
    return factory


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'life.sqlite'}", connect_args={"timeout": 10})
    try:
        yield _prepare_database(engine, monkeypatch)
    finally:
        engine.dispose()


def configure(**policy):
    return store.update_settings(
        LifeUpdate(
            expected_revision=store.read_state()["revision"],
            level=6,
            policy={
                "daily_token_limit": 1000,
                "daily_cycle_limit": 10,
                "authorization_expires_at": (store.utcnow() + timedelta(days=1)).isoformat(),
                **policy,
            },
        ),
        actor_user_id=7,
    )


def finish(claim, **fields):
    return store.finish_cycle(
        claim,
        status="completed",
        summary="核对了实际运行记录",
        evidence_refs=["receipt:one"],
        actual_tokens=fields.pop("actual_tokens", 50),
        **fields,
    )


def test_identity_survives_new_sessions_and_global_mode_is_shared(database):
    first = store.read_state()
    updated = store.update_settings(
        LifeUpdate(expected_revision=first["revision"], level=1), actor_user_id=7
    )
    assert store.read_state()["identity_id"] == first["identity_id"]
    second = store.update_settings(
        LifeUpdate(expected_revision=updated["revision"], level=5), actor_user_id=8
    )
    assert second["level"] == store.read_state()["level"] == 5
    assert second["budget"]["used_tokens"] == 0
    assert second["status"] == "blocked"
    with database() as session:
        assert session.scalar(select(func.count()).select_from(XiaoCLifeState)) == 1


def test_two_windows_cannot_overwrite_each_others_control_revision(database):
    revision = store.read_state()["revision"]

    def update(level):
        try:
            return store.update_settings(
                LifeUpdate(expected_revision=revision, level=level), actor_user_id=7
            )["level"]
        except LifePolicyError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, (4, 6)))
    assert results.count("conflict") == 1
    assert store.read_state()["revision"] == revision + 1


def test_two_workers_reserve_one_cycle_and_actual_usage_settles_once(database):
    configure()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(lambda _: store.claim_cycle(domain="enterprise", reserve_tokens=200), range(2))
        )
    actual = [claim for claim in claims if claim]
    assert len(actual) == 1
    assert store.read_state()["budget"]["reserved_tokens"] == 200
    result = finish(actual[0])
    finish(actual[0])
    assert result["budget"]["used_tokens"] == 50
    assert store.read_state()["budget"]["used_tokens"] == 50
    assert result["budget"]["reserved_tokens"] == 0
    with database() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(XiaoCLifeEvent)
                .where(XiaoCLifeEvent.kind == "enterprise")
            )
            == 1
        )


def test_downgrade_cancels_new_actions_but_settles_real_cost_and_keeps_identity(database):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    assert store.cycle_active(claim)
    state = store.read_state()
    store.update_settings(LifeUpdate(expected_revision=state["revision"], level=2), actor_user_id=8)
    assert not store.cycle_active(claim)
    assert store.claim_cycle(domain="enterprise", reserve_tokens=200) is None
    result = finish(
        claim,
        goals=[{"id": "must-not-be-scheduled", "title": "stale", "evidence_refs": ["receipt:one"]}],
    )
    assert result["budget"]["used_tokens"] == 50
    assert result["goals"] == []
    assert result["events"][0]["status"] == "policy_changed"


@pytest.mark.parametrize(
    "authority", ["active", "revoked_admin", "expired_lease", "expired_authorization"]
)
@pytest.mark.parametrize("actual_tokens", [50, None])
def test_late_receipts_settle_once_without_learning_or_advancing_goals(
    database, monkeypatch, authority, actual_tokens
):
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    monkeypatch.setattr(store, "utcnow", lambda: now)
    expiry = now + (
        timedelta(minutes=1) if authority == "expired_authorization" else timedelta(days=1)
    )
    configure(authorization_expires_at=expiry.isoformat())
    original_goal = {"id": "original-goal", "decision_id": "original-decision"}
    store._mutate(lambda data, session: data["goals"].append(original_goal))
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    assert store.cycle_active(claim)
    before = store.read_state()
    if authority == "revoked_admin":
        with database() as session:
            session.get(User, 7).is_admin = False
            session.commit()
    elif authority.startswith("expired_"):
        later = now + timedelta(minutes=6 if authority == "expired_lease" else 2)
        monkeypatch.setattr(store, "utcnow", lambda: later)
    fresh = authority == "active"
    assert store.cycle_active(claim) is fresh
    goal = {
        "id": "learned-goal",
        "title": "New learning",
        "evidence_refs": ["receipt:one"],
    }
    interest = {"topic": "Learning", "evidence_refs": ["receipt:one"]}
    self_model = {"assessment": "Learning", "evidence_refs": ["receipt:one"]}
    selection = {
        "goal_id": original_goal["id"],
        "decision_id": original_goal["decision_id"],
    }
    for _ in range(2):
        state = finish(
            claim,
            actual_tokens=actual_tokens,
            goals=[goal],
            interests=[interest],
            self_model=self_model,
            details={"portfolio_selection": selection},
        )
        learned = fresh and actual_tokens is not None
        assert state["budget"]["used_tokens"] == (actual_tokens or 0)
        assert state["budget"]["reserved_tokens"] == (200 if actual_tokens is None else 0)
        assert state["unknown_usage"] is (actual_tokens is None)
        assert state["goals"] == ([original_goal, goal] if learned else before["goals"])
        assert state["interests"] == ([interest] if learned else before["interests"])
        assert state["self_model"] == (
            {
                **self_model,
                "status": "hypothesis",
                "owner_user_id": claim["owner_user_id"],
                "assessment_event_id": "cycle:" + claim["cycle_id"],
            }
            if learned
            else before["self_model"]
        )
        assert state.get("goal_cursors", {}) == ({"enterprise": "original-goal"} if fresh else {})
        events = [event for event in state["events"] if event["id"] == "cycle:" + claim["cycle_id"]]
        assert len(events) == 1
        assert events[0]["actual_tokens"] == actual_tokens
        assert events[0]["evidence_refs"] == ["receipt:one"]
        assert events[0]["details"]["learning_applied"] is learned
        assert events[0]["details"]["portfolio_selection"] == selection
        assert events[0]["status"] == (
            "unknown" if actual_tokens is None else "completed" if fresh else "policy_changed"
        )


def test_pausing_background_does_not_block_explicit_manual_tools(database):
    configure()
    state = store.read_state()
    store.update_settings(
        LifeUpdate(expected_revision=state["revision"], paused=True), actor_user_id=7
    )
    store.require_life_capability(3)
    assert store.claim_cycle(domain="enterprise", reserve_tokens=200) is None


def test_exploration_cannot_consume_enterprise_reserved_share(database):
    configure(exploration_percent=20)
    claim = store.claim_cycle(domain="exploration", reserve_tokens=500)
    assert claim["reserved_tokens"] == 200
    finish(claim, actual_tokens=200)
    state = store.read_state()
    store.wake(actor_user_id=7, expected_revision=state["revision"])
    assert store.claim_cycle(domain="exploration", reserve_tokens=1) is None
    work = store.claim_cycle(domain="enterprise", reserve_tokens=900)
    assert work["reserved_tokens"] == 800


def test_unknown_spending_keeps_hold_across_midnight_and_settings_changes(database, monkeypatch):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    finish(claim, actual_tokens=None)
    tomorrow = store.utcnow() + timedelta(days=1)
    monkeypatch.setattr(store, "utcnow", lambda: tomorrow)
    state = configure()
    assert state["budget"]["reserved_tokens"] == 200
    assert store.claim_cycle(domain="enterprise", reserve_tokens=100) is None
    assert state["unknown_usage"] is True


def test_expired_worker_lease_is_not_replayed(database, monkeypatch):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    later = store.utcnow() + timedelta(minutes=6)
    monkeypatch.setattr(store, "utcnow", lambda: later)
    assert not store.cycle_active(claim)
    assert store.claim_cycle(domain="enterprise", reserve_tokens=200) is None
    state = store.read_state()
    assert state["unknown_usage"] is True
    assert state["budget"]["reserved_tokens"] == 200


def test_revoked_principal_and_expired_authorization_stop_next_model_call(database):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    with store.life_execution_scope(claim):
        with database() as session:
            session.get(User, 7).is_admin = False
            session.commit()
        with pytest.raises(LifePolicyError):
            store.require_current_life_call()
    assert not store.cycle_active(claim)


@pytest.mark.parametrize("invalidate", ["revoked", "lease_expired", "authorization_expired"])
def test_late_lifecycle_receipt_settles_without_adopting_new_learning(
    database, monkeypatch, invalidate
):
    now = store.utcnow()
    if invalidate == "authorization_expired":
        configure(authorization_expires_at=(now + timedelta(minutes=1)).isoformat())
    else:
        configure()
    claim = store.claim_cycle(domain="reflection", reserve_tokens=200)
    assert store.cycle_active(claim)
    if invalidate == "revoked":
        with database() as session:
            session.get(User, 7).is_admin = False
            session.commit()
    else:
        later = now + timedelta(minutes=2 if invalidate == "authorization_expired" else 6)
        monkeypatch.setattr(store, "utcnow", lambda: later)
    assert not store.cycle_active(claim)
    result = finish(
        claim,
        goals=[{"id": "late", "title": "late", "evidence_refs": ["receipt:one"]}],
        interests=[{"topic": "late", "evidence_refs": ["receipt:one"]}],
        self_model={"title": "late", "evidence_refs": ["receipt:one"]},
    )
    finish(claim)
    assert store.read_state()["budget"]["used_tokens"] == 50
    assert result["budget"]["reserved_tokens"] == 0
    assert result["goals"] == []
    assert result["interests"] == []
    assert result["self_model"] == {}
    event = next(row for row in result["events"] if row["id"] == f"cycle:{claim['cycle_id']}")
    assert event["status"] == "policy_changed"
    assert event["actual_tokens"] == 50
    assert event["details"]["learning_applied"] is False


def test_experiences_accumulate_and_hypotheses_never_become_verified_capability(database):
    configure()
    for i in range(2):
        store.wake(actor_user_id=7, expected_revision=store.read_state()["revision"])
        claim = store.claim_cycle(domain="reflection", reserve_tokens=200)
        finish(
            claim,
            goals=[
                {
                    "id": f"goal-{i}",
                    "title": f"research-{i}",
                    "domain": "reflection",
                    "status": "proposed",
                    "evidence_refs": ["receipt:one"],
                }
            ],
            interests=[
                {"topic": "可靠性", "confidence": 0.4 + i * 0.1, "evidence_refs": ["receipt:one"]}
            ],
            self_model={
                "assessment": "需要改进核对",
                "status": "verified",
                "evidence_refs": ["receipt:one"],
            },
        )
    state = store.read_state()
    assert len(state["goals"]) == 2
    assert len(state["interests"]) == 1
    assert state["interests"][0]["confidence"] == 0.5
    assert state["self_model"]["status"] == "hypothesis"
    assert state["self_model"]["owner_user_id"] == 7
    assert any(
        row["id"] == state["self_model"]["assessment_event_id"]
        for row in state["events"]
        if row["kind"] == "reflection"
    )
    assert len([event for event in state["events"] if event["kind"] == "reflection"]) == 2


def test_budget_updates_never_clear_consumption_or_allow_unbounded_authority(database):
    configure()
    finish(store.claim_cycle(domain="enterprise", reserve_tokens=200), actual_tokens=150)
    state = configure(daily_token_limit=100)
    assert state["budget"]["used_tokens"] == 150
    assert store.claim_cycle(domain="enterprise", reserve_tokens=1) is None
    # Neither paid nor zero-token activity may bypass the exhausted daily
    # quota. Returning None here is part of the mandatory stop gate.
    assert store.claim_cycle(domain="enterprise", reserve_tokens=0) is None
    assert store.read_state()["budget"]["reserved_tokens"] == 0
    assert not state["unknown_usage"]
    with pytest.raises(LifePolicyError, match="31"):
        configure(authorization_expires_at=(store.utcnow() + timedelta(days=32)).isoformat())


def test_api_scopes_mode_to_server_identity_and_rejects_forged_owners(database):
    identity = {"user": SimpleNamespace(id=7, is_admin=True)}
    app = FastAPI()
    app.include_router(api.router, prefix="/api/agent/butler")
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    with TestClient(app) as client:
        route = "/api/agent/butler/life"
        state = client.get(route).json()
        assert (
            client.put(
                route, json={"expected_revision": state["revision"], "level": 6, "owner_user_id": 8}
            ).status_code
            == 422
        )
        assert (
            client.put(route, json={"expected_revision": state["revision"], "level": 6}).status_code
            == 200
        )
        assert (
            client.put(route, json={"expected_revision": state["revision"], "level": 1}).status_code
            == 409
        )
        identity["user"].is_admin = False
        assert client.get(route).status_code == 403
        assert client.put(route, json={"expected_revision": 2, "level": 1}).status_code == 403


def test_authorization_expiry_is_checked_before_a_new_claim(database, monkeypatch):
    configure()
    later = store.utcnow() + timedelta(days=2)
    monkeypatch.setattr(store, "utcnow", lambda: later)
    assert store.claim_cycle(domain="enterprise", reserve_tokens=200) is None
    assert store.read_state()["status"] == "blocked"


@pytest.mark.parametrize("next_day", [False, True])
def test_crash_reconciliation_uses_original_model_receipt_without_replaying(
    database, monkeypatch, next_day
):
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    monkeypatch.setattr(store, "utcnow", lambda: now)
    monkeypatch.setattr(reconcile, "utcnow", lambda: now)
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    store.record_cycle_step(claim, kind="model", details={"request_id": "original-paid-call"})
    with database() as session:
        session.add(
            LlmClientRequest(
                user_id=7,
                client_request_id="original-paid-call",
                request_sha256="a" * 64,
                state="processing",
                done_json="{}",
            )
        )
        session.commit()
    later = now + timedelta(days=int(next_day), minutes=6)
    monkeypatch.setattr(store, "utcnow", lambda: later)
    monkeypatch.setattr(reconcile, "utcnow", lambda: later)
    assert reconcile.reconcile_usage() == {"resolved": 0, "waiting": 1}
    assert store.read_state()["budget"]["reserved_tokens"] == 200
    with database() as session:
        receipt = session.scalar(select(LlmClientRequest))
        receipt.state = "completed"
        receipt.done_json = json.dumps({"status": "settled", "actual_tokens": 63})
        session.commit()
    assert reconcile.reconcile_usage()["resolved"] == 1
    assert reconcile.reconcile_usage()["resolved"] == 0
    with database() as session:
        persisted = json.loads(session.get(XiaoCLifeState, store.IDENTITY_ID).state_json)
    assert persisted["budget"]["used_tokens"] == 63
    state = store.read_state()
    assert state["budget"]["date"] == store._day()
    assert state["budget"]["used_tokens"] == (0 if next_day else 63)
    assert state["budget"]["reserved_tokens"] == 0
    assert state["unknown_usage"] is False
    assert state["events"][0]["kind"] == "reconciliation"
    assert state["events"][0]["actual_tokens"] == 63
    original_day = date.fromisoformat(persisted["budget"]["date"])
    for offset, used in ((0, 63), (1, 0)):
        day = (original_day + timedelta(days=offset)).isoformat()
        monkeypatch.setattr(store, "_day", lambda: day)
        state = store.read_state()
        assert state["budget"]["date"] == day
        assert state["budget"]["used_tokens"] == used
        assert state["budget"]["reserved_tokens"] == 0
        assert state["unknown_usage"] is False
        assert state["events"][0]["kind"] == "reconciliation"
        assert state["events"][0]["actual_tokens"] == 63

    original_day = date.fromisoformat(persisted["budget"]["date"])
    for offset, used in ((0, 63), (1, 0)):
        day = (original_day + timedelta(days=offset)).isoformat()
        monkeypatch.setattr(store, "_day", lambda: day)
        state = store.read_state()
        assert state["budget"]["date"] == day
        assert state["budget"]["used_tokens"] == used
        assert state["budget"]["reserved_tokens"] == 0
        assert state["unknown_usage"] is False
        assert state["events"][0]["kind"] == "reconciliation"


def test_unknown_finished_cycle_reconciles_once_and_preserves_original_fact(database, monkeypatch):
    import json

    from modstore_server import xiaoc_life_reconciliation as reconcile

    monkeypatch.setattr(reconcile, "get_session_factory", lambda: database)
    configure()
    claim = store.claim_cycle(domain="exploration", reserve_tokens=100)
    store.record_cycle_step(claim, kind="model", details={"request_id": "original-response"})
    finish(claim, actual_tokens=None)
    with database() as session:
        session.add(
            LlmClientRequest(
                user_id=7,
                client_request_id="original-response",
                request_sha256="b" * 64,
                state="completed",
                done_json=json.dumps({"status": "settled", "actual_tokens": 30}),
            )
        )
        session.commit()
    assert reconcile.reconcile_usage()["resolved"] == 1
    assert reconcile.reconcile_usage()["resolved"] == 0
    state = store.read_state()
    assert state["budget"]["exploration_tokens"] == 30
    assert state["budget"]["reserved_tokens"] == 0
    original = next(row for row in state["events"] if row["id"] == "cycle:" + claim["cycle_id"])
    assert original["actual_tokens"] is None and original["status"] == "unknown"


def test_reconciled_history_cannot_starve_later_unknown_cycle(database, monkeypatch):
    from modstore_server import xiaoc_life_reconciliation as reconcile

    monkeypatch.setattr(reconcile, "get_session_factory", lambda: database)
    configure()
    with database() as session:
        for index in range(100):
            event_id = f"cycle:historical-{index}"
            store._event(
                session,
                event_id,
                kind="enterprise",
                status="unknown",
                summary="Original uncertain call",
                evidence_refs=[],
                actual_tokens=None,
            )
            store._event(
                session,
                "reconciled:" + event_id,
                kind="reconciliation",
                status="verified",
                summary="Original receipt recovered",
                evidence_refs=[event_id],
                actual_tokens=0,
            )
        session.commit()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    finish(claim, actual_tokens=None)
    assert store.read_state()["budget"]["reserved_tokens"] == 200

    assert reconcile.reconcile_usage() == {"resolved": 1, "waiting": 0}
    assert reconcile.reconcile_usage() == {"resolved": 0, "waiting": 0}
    state = store.read_state()
    assert state["budget"]["reserved_tokens"] == state["budget"]["used_tokens"] == 0
    assert state["unknown_usage"] is False
    with database() as session:
        original = session.get(XiaoCLifeEvent, "cycle:" + claim["cycle_id"])
        assert original.actual_tokens is None and original.status == "unknown"
        assert session.get(XiaoCLifeEvent, "reconciled:" + original.id) is not None


@pytest.mark.parametrize(
    "field,value", [("domain", "exploration"), ("owner_user_id", 8), ("reserved_tokens", 9999)]
)
def test_a_lease_cannot_be_repurposed_for_another_owner_domain_or_allowance(database, field, value):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    assert not store.cycle_active({**claim, field: value})


def test_crash_before_any_outbound_releases_hold_and_fences_late_dispatch(database, monkeypatch):
    from modstore_server import xiaoc_life_reconciliation as reconcile

    monkeypatch.setattr(reconcile, "get_session_factory", lambda: database)
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    later = store.utcnow() + timedelta(minutes=6)
    monkeypatch.setattr(store, "utcnow", lambda: later)
    monkeypatch.setattr(reconcile, "utcnow", lambda: later)
    assert reconcile.reconcile_usage() == {"resolved": 1, "waiting": 0}
    state = store.read_state()
    assert state["budget"]["reserved_tokens"] == state["budget"]["used_tokens"] == 0
    assert state["activity"] is None
    assert reconcile.reconcile_usage()["resolved"] == 0
    with pytest.raises(LifePolicyError):
        store.record_cycle_step(claim, kind="model", details={"request_id": "late-call"})


def test_journaled_intent_without_ledger_is_not_assumed_free(database, monkeypatch):
    from modstore_server import xiaoc_life_reconciliation as reconcile

    monkeypatch.setattr(reconcile, "get_session_factory", lambda: database)
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    store.record_cycle_step(claim, kind="model", details={"request_id": "uncertain-call"})
    later = store.utcnow() + timedelta(minutes=6)
    monkeypatch.setattr(store, "utcnow", lambda: later)
    monkeypatch.setattr(reconcile, "utcnow", lambda: later)
    assert reconcile.reconcile_usage() == {"resolved": 0, "waiting": 1}
    assert store.read_state()["budget"]["reserved_tokens"] == 200


def test_experience_cursor_preserves_records_with_identical_timestamps(database):
    store.read_state()
    timestamp = datetime.now(UTC)
    with database() as session:
        for event_id in ("a", "b"):
            session.add(
                XiaoCLifeEvent(
                    id=event_id,
                    identity_id=store.IDENTITY_ID,
                    kind="execution",
                    status="verified",
                    summary="实际回执",
                    evidence_json="[]",
                    details_json="{}",
                    model="",
                    actual_tokens=0,
                    created_at=timestamp,
                )
            )
        session.commit()
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, is_admin=True)
    with TestClient(app) as client:
        first = client.get("/life/experiences", params={"limit": 1}).json()
        second = client.get(
            "/life/experiences", params={"limit": 1, "before": first["next_cursor"]}
        ).json()
    assert [first["items"][0]["id"], second["items"][0]["id"]] == ["b", "a"]


@pytest.mark.parametrize("historical_reconciled", [True, False])
def test_usage_scan_excludes_settled_history_and_rotates_unresolved_batches(
    database, historical_reconciled
):
    configure()

    def seed(current, session):
        current["budget"].update(
            reserved_tokens=10 if historical_reconciled else 1010,
            used_tokens=100 if historical_reconciled else 0,
        )
        current["unknown_usage"] = True
        for index in range(101):
            event_id = f"cycle:{index:03}"
            store._event(
                session,
                event_id,
                kind="enterprise",
                status="unknown",
                summary="原调用仍待核对",
                evidence_refs=[],
                actual_tokens=None,
                details={
                    "owner_user_id": 7,
                    "reservation": 10,
                    "steps": [{"kind": "model", "request_id": f"original-{index:03}"}],
                },
            )
            if index < 100 and historical_reconciled:
                store._event(
                    session,
                    "reconciled:" + event_id,
                    kind="reconciliation",
                    status="verified",
                    summary="已核对原调用",
                    evidence_refs=[event_id],
                    actual_tokens=1,
                )
        session.add(
            LlmClientRequest(
                user_id=7,
                client_request_id="original-100",
                request_sha256="c" * 64,
                state="completed",
                done_json=json.dumps({"status": "settled", "actual_tokens": 3}),
            )
        )

    store._mutate(seed)
    if not historical_reconciled:
        assert reconcile.reconcile_usage() == {"resolved": 0, "waiting": 100}
    assert reconcile.reconcile_usage()["resolved"] == 1
    assert reconcile.reconcile_usage()["resolved"] == 0
    state = store.read_state()
    assert state["budget"]["used_tokens"] == (103 if historical_reconciled else 3)
    assert state["budget"]["reserved_tokens"] == (0 if historical_reconciled else 1000)
    with database() as session:
        assert session.get(XiaoCLifeEvent, "cycle:100").actual_tokens is None
        assert session.get(XiaoCLifeEvent, "reconciled:cycle:100").actual_tokens == 3
        if not historical_reconciled:
            session.add(
                LlmClientRequest(
                    user_id=7,
                    client_request_id="original-000",
                    request_sha256="d" * 64,
                    state="completed",
                    done_json=json.dumps({"status": "settled", "actual_tokens": 2}),
                )
            )
            session.commit()
    if not historical_reconciled:
        assert reconcile.reconcile_usage()["resolved"] == 1
        assert store.read_state()["budget"]["reserved_tokens"] == 990


def test_world_forecast_settles_across_real_sql_cycles_without_new_authority(database, monkeypatch):
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    monkeypatch.setattr(store, "utcnow", lambda: now)
    configure(authorization_expires_at=(now + timedelta(days=4)).isoformat())

    def observe(day, value, digest):
        nonlocal now
        now = datetime(2026, 11, 23, 4, tzinfo=UTC) + timedelta(days=day)
        store.wake(actor_user_id=7, expected_revision=store.read_state()["revision"])
        claim = store.claim_cycle(domain="reflection", reserve_tokens=200)
        state = finish(
            claim,
            details={
                "world_observations": {
                    "intent_accuracy": {
                        "observed_at": now.isoformat(),
                        "value": value,
                        "source_sha256": digest * 64,
                    }
                }
            },
        )
        assert finish(claim)["world_review"] == state["world_review"]
        return state

    observe(0, 0.4, "a")
    second = observe(1, 0.8, "b")
    frozen = second["world_review"]["series"]["intent_accuracy"]["pending"]
    third = observe(2, 0.5, "c")
    series = third["world_review"]["series"]["intent_accuracy"]
    assert series["evaluations"][0]["forecast"] == frozen
    assert series["evaluations"][0]["actual"]["value"] == 0.5
    assert third["goals"] == [] and third["interests"] == []
    assert third["events"][0]["details"]["world_review_snapshot"] == third["world_review"]


def test_world_forecast_does_not_learn_after_pause(database):
    configure()
    claim = store.claim_cycle(domain="reflection", reserve_tokens=200)
    store.update_settings(
        LifeUpdate(expected_revision=store.read_state()["revision"], paused=True),
        actor_user_id=7,
    )
    result = finish(
        claim,
        details={
            "world_observations": {
                "intent_accuracy": {
                    "observed_at": store.utcnow().isoformat(),
                    "value": 0.5,
                    "source_sha256": "a" * 64,
                }
            }
        },
    )
    assert "world_review" not in result
    assert result["budget"]["used_tokens"] == 50


def test_explicit_stop_survives_new_sessions_and_requires_explicit_start(database):
    initial = configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    store.record_cycle_phase(claim, "observe")
    running = store.read_state()
    assert running["state_version"] > initial["state_version"]
    assert running["activity"]["phase"] == "observe"
    assert "lease_token" not in running["activity"]
    assert len(running["activity"]["trace_cycle_sha256"]) == 64
    stopped = store.update_settings(
        LifeUpdate(expected_revision=running["revision"], stopped=True), actor_user_id=7
    )
    assert stopped["status"] == "stopped" and stopped["paused"]
    assert not store.cycle_active(claim)
    assert store.claim_cycle(domain="enterprise", reserve_tokens=100) is None
    with pytest.raises(LifePolicyError):
        store.update_settings(
            LifeUpdate(expected_revision=stopped["revision"], paused=False), actor_user_id=7
        )
    with pytest.raises(LifePolicyError):
        store.record_cycle_phase(claim, "decide")
    finished = finish(claim, actual_tokens=50)
    assert finished["identity_id"] == initial["identity_id"]
    assert finished["status"] == "stopped"
    assert finished["events"][0]["status"] == "policy_changed"
    restarted = store.update_settings(
        LifeUpdate(expected_revision=finished["revision"], stopped=False, paused=False),
        actor_user_id=7,
    )
    assert restarted["identity_id"] == initial["identity_id"]
    assert restarted["budget"]["used_tokens"] == 50
    assert not restarted["stopped"] and not restarted["paused"]
    assert not store.cycle_active(claim)
    assert (
        store.claim_cycle(domain="enterprise", reserve_tokens=100)["cycle_id"] != claim["cycle_id"]
    )


@pytest.mark.parametrize(
    ("command", "status"),
    [
        ({"paused": False, "stopped": False}, "thinking"),
        ({"paused": True}, "paused"),
        ({"stopped": True}, "stopped"),
    ],
)
def test_repeating_lifecycle_command_preserves_cycle_and_state(
    database, monkeypatch, command, status
):
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    monkeypatch.setattr(store, "utcnow", lambda: now)
    initial = configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    assert claim is not None
    store.record_cycle_phase(claim, "observe")
    if status != "thinking":
        store.update_settings(
            LifeUpdate(expected_revision=initial["revision"], **command), actor_user_id=7
        )
    before = store.read_state()
    with database() as session:
        cycle = json.loads(session.get(XiaoCLifeState, before["identity_id"]).state_json)[
            "active_cycle"
        ]
    assert before["status"] == status
    assert before["activity"]["id"] == cycle["cycle_id"] == claim["cycle_id"]
    assert before["budget"]["cycles"] == 1
    assert before["budget"]["reserved_tokens"] == 200
    assert cycle["lease_token"] == claim["lease_token"]
    now += timedelta(seconds=1)
    result = store.update_settings(
        LifeUpdate(expected_revision=before["revision"], **command), actor_user_id=7
    )
    for field in (
        "identity_id",
        "revision",
        "state_version",
        "activity",
        "budget",
        "next_wake_at",
        "updated_at",
        "events",
    ):
        assert result[field] == before[field]
    with database() as session:
        row = session.get(XiaoCLifeState, before["identity_id"])
        assert json.loads(row.state_json)["active_cycle"] == cycle
    assert store.cycle_active(claim) is (status == "thinking")


@pytest.mark.parametrize(
    "settings",
    [{"level": 5}, {"mission": "更新企业使命"}, {"policy": {"daily_cycle_limit": 8}}],
)
def test_repeated_lifecycle_flag_does_not_skip_settings_update(database, settings):
    initial = configure()
    paused = store.update_settings(
        LifeUpdate(expected_revision=initial["revision"], paused=True), actor_user_id=7
    )
    updated = store.update_settings(
        LifeUpdate(expected_revision=paused["revision"], paused=True, **settings), actor_user_id=7
    )
    assert updated["paused"]
    assert updated["revision"] == paused["revision"] + 1
    assert updated["state_version"] == paused["state_version"] + 1
    for field, value in settings.items():
        if field == "policy":
            assert updated["policy"]["daily_cycle_limit"] == value["daily_cycle_limit"]
        else:
            assert updated[field] == value


def test_repeated_lifecycle_command_still_checks_expected_revision(database):
    initial = configure()
    command = LifeUpdate(expected_revision=initial["revision"], paused=True)
    paused = store.update_settings(command, actor_user_id=7)
    with pytest.raises(LifePolicyError, match="全企业自主设置已变动"):
        store.update_settings(command, actor_user_id=7)
    assert store.read_state()["state_version"] == paused["state_version"]



def test_graph_act_outbound_and_closeout_have_idempotent_persistent_audit(database):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    assert claim is not None
    assert store.begin_cycle_graph(claim)
    assert not store.begin_cycle_graph(claim)
    for phase in ("observe", "decide"):
        store.record_cycle_phase(claim, phase)
    assert store.admit_cycle_act(claim)
    assert not store.admit_cycle_act(claim)
    store.mark_model_attempt(claim)
    store.mark_model_attempt(claim)
    store.record_cycle_phase(claim, "act")
    receipt = {"status": "verified", "actual_tokens": 0}
    assert store.prepare_native_closeout(claim, "checkpoint:original", receipt)
    assert store.prepare_native_closeout(claim, "checkpoint:original", receipt)
    with database() as session:
        rows = session.scalars(
            select(XiaoCLifeEvent).where(
                XiaoCLifeEvent.kind == "life_transition",
                XiaoCLifeEvent.id.in_(
                    [
                        f"life:graph:{claim['cycle_id']}",
                        f"life:act:{claim['cycle_id']}",
                        f"life:outbound:{claim['cycle_id']}",
                        f"life:closeout:{claim['cycle_id']}",
                    ]
                ),
            )
        ).all()
    assert len(rows) == 4
    assert {row.status for row in rows} == {
        "graph_started",
        "act_admitted",
        "model_attempted",
        "closeout_prepared",
    }
    details = [json.loads(row.details_json) for row in rows]
    assert "lease_token" not in json.dumps(details)


def test_experiences_api_keeps_lifecycle_audit_in_separate_state_feed(database):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    assert claim is not None
    store.record_cycle_phase(claim, "observe")
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=7, is_admin=True
    )
    with TestClient(app) as client:
        experiences = client.get("/life/experiences").json()
        status = client.get("/life").json()
    assert experiences["items"]
    assert all(item["kind"] != "life_transition" for item in experiences["items"])
    assert any(item["status"] == "observe" for item in status["lifecycle_events"])
    assert status["activity"]["id"] == claim["cycle_id"]


def test_lifecycle_phase_transitions_are_append_only_and_concurrent_retries_idempotent(
    database,
):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    assert claim is not None
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: store.record_cycle_phase(claim, "observe"), range(2)))
    for phase in ("decide", "act", "reflect"):
        store.record_cycle_phase(claim, phase)
    with database() as session:
        persisted = list(
            session.scalars(
                select(XiaoCLifeEvent).where(
                    XiaoCLifeEvent.kind == "life_transition",
                    XiaoCLifeEvent.id.startswith(f"life:phase:{claim['cycle_id']}:"),
                )
            )
        )
    by_status = {row.status: json.loads(row.details_json) for row in persisted}
    assert set(by_status) == {"claimed", "observe", "decide", "act", "reflect"}
    assert by_status["observe"]["from"] == "claimed"
    assert by_status["decide"]["from"] == "observe"
    assert by_status["act"]["from"] == "decide"
    assert by_status["reflect"]["from"] == "act"
    assert all(
        event["kind"] != "life_transition" for event in store.read_state()["events"]
    )
    assert (
        len(
            [
                event
                for event in store.read_state()["lifecycle_events"]
                if event["status"] == "observe"
            ]
        )
        == 1
    )
    finish(claim)
    with database() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(XiaoCLifeEvent).where(
                    XiaoCLifeEvent.kind == "life_transition",
                    XiaoCLifeEvent.id.startswith(f"life:phase:{claim['cycle_id']}:"),
                )
            )
            == 5
        )


@pytest.mark.parametrize("reason", ["paused", "stopped", "revoked", "expired"])
def test_admission_denial_persists_once_and_never_reclaims_on_repeat(
    database, monkeypatch, reason
):
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    monkeypatch.setattr(store, "utcnow", lambda: now)
    state = configure(
        authorization_expires_at=(now + timedelta(minutes=5)).isoformat()
    )
    if reason in ("paused", "stopped"):
        field = "paused" if reason == "paused" else "stopped"
        store.update_settings(
            LifeUpdate(expected_revision=state["revision"], **{field: True}),
            actor_user_id=7,
        )
    elif reason == "revoked":
        with database() as session:
            session.get(User, 7).is_admin = False
            session.commit()
    else:
        monkeypatch.setattr(store, "utcnow", lambda: now + timedelta(minutes=6))
    assert store.claim_cycle(domain="enterprise", reserve_tokens=200) is None
    first = store.read_state()
    expected_status = {
        "paused": "paused",
        "stopped": "stopped",
        "revoked": "blocked",
        "expired": "blocked",
    }[reason]
    assert first["status"] == expected_status
    assert store.claim_cycle(domain="enterprise", reserve_tokens=200) is None
    assert store.read_state()["state_version"] == first["state_version"]
    with database() as session:
        denial = list(
            session.scalars(
                select(XiaoCLifeEvent).where(
                    XiaoCLifeEvent.kind == "life_transition",
                    XiaoCLifeEvent.status == "blocked",
                )
            )
        )
    assert len(denial) == 1
    assert json.loads(denial[0].details_json)["reasons"]
    assert store.read_state()["budget"]["cycles"] == 0


def test_budget_exhaustion_has_immutable_admission_and_settlement_evidence(database):
    configure(daily_token_limit=200, exploration_percent=0)
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    assert claim is not None and store.cycle_active(claim)
    with database() as session:
        exhausted = session.get(XiaoCLifeEvent, f"life:limit:{claim['cycle_id']}")
        assert exhausted is not None and exhausted.status == "budget_exhausted"
        assert json.loads(exhausted.details_json)["budget_date"]
    finish(claim, actual_tokens=200)
    state = store.read_state()
    assert state["budget"]["used_tokens"] == 200
    assert state["budget"]["reserved_tokens"] == 0
    assert state["status"] == "blocked"
    assert state["events"][0]["details"]["terminal_status"] == "completed"
    store.wake(actor_user_id=7, expected_revision=state["revision"])
    assert store.claim_cycle(domain="enterprise", reserve_tokens=0) is None
    after_denial = store.read_state()
    assert store.claim_cycle(domain="enterprise", reserve_tokens=0) is None
    assert store.read_state()["state_version"] == after_denial["state_version"]
    with database() as session:
        assert (
            session.get(XiaoCLifeEvent, f"life:limit:{claim['cycle_id']}")
            is not None
        )
        assert session.get(XiaoCLifeEvent, f"cycle:{claim['cycle_id']}") is not None
        assert (
            session.scalar(
                select(func.count()).select_from(XiaoCLifeEvent).where(
                    XiaoCLifeEvent.kind == "life_transition",
                    XiaoCLifeEvent.status == "blocked",
                )
            )
            == 1
        )


def test_policy_audit_captures_stop_pause_resume_edges_without_duplicate_events(
    database,
):
    configured = configure()
    paused = store.update_settings(
        LifeUpdate(expected_revision=configured["revision"], paused=True),
        actor_user_id=7,
    )
    stopped = store.update_settings(
        LifeUpdate(expected_revision=paused["revision"], stopped=True),
        actor_user_id=7,
    )
    resumed = store.update_settings(
        LifeUpdate(
            expected_revision=stopped["revision"], stopped=False, paused=False
        ),
        actor_user_id=7,
    )
    assert resumed["status"] != "stopped"
    assert not resumed["paused"] and not resumed["stopped"]
    with database() as session:
        history = {
            row.id: json.loads(row.details_json)
            for row in session.scalars(
                select(XiaoCLifeEvent).where(XiaoCLifeEvent.kind == "policy")
            )
        }
    edges = [
        history[f"policy:{snapshot['revision']}"]
        for snapshot in (paused, stopped, resumed)
    ]
    assert [
        (item["before_paused"], item["paused"], item["before_stopped"], item["stopped"])
        for item in edges
    ] == [
        (False, True, False, False),
        (True, True, False, True),
        (True, False, True, False),
    ]
    duplicate = store.update_settings(
        LifeUpdate(expected_revision=resumed["revision"], stopped=False, paused=False),
        actor_user_id=7,
    )
    assert duplicate["state_version"] == resumed["state_version"]
    with database() as session:
        assert session.scalar(
            select(func.count()).select_from(XiaoCLifeEvent).where(
                XiaoCLifeEvent.kind == "policy"
            )
        ) == len(history)


def test_budget_exhaustion_blocks_even_zero_token_new_cycle(database):
    configure(daily_token_limit=200, exploration_percent=0)
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    assert store.cycle_active(claim)  # Its own reservation must not revoke it.
    finish(claim, actual_tokens=200)
    state = store.read_state()
    assert state["status"] == "blocked"
    assert "今日自主活动模型预算已耗尽" in state["blockers"]
    store.wake(actor_user_id=7, expected_revision=state["revision"])
    assert store.claim_cycle(domain="enterprise", reserve_tokens=0) is None


def test_phase_does_not_skip_or_rewind_and_original_receipt_is_preserved(database):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    with pytest.raises(LifePolicyError):
        store.record_cycle_phase(claim, "act")
    for phase in ("observe", "decide", "act", "reflect"):
        store.record_cycle_phase(claim, phase)
        assert store.read_state()["activity"]["phase"] == phase
    with pytest.raises(LifePolicyError):
        store.record_cycle_phase(claim, "observe")
    state = finish(claim)
    assert state["events"][0]["details"]["last_phase"] == "reflect"
    assert state["activity"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("domain", "exploration"),
        ("owner_user_id", 8),
        ("reserved_tokens", 9999),
        ("deadline", "forged"),
    ],
)
def test_wrong_lease_binding_cannot_journal_or_settle(database, field, value):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    forged = {**claim, field: value}
    with pytest.raises(LifePolicyError):
        store.record_cycle_step(forged, kind="model", details={"request_id": "forged-call"})
    with pytest.raises(LifePolicyError):
        finish(forged)
    assert store.read_state()["budget"]["reserved_tokens"] == 200
    assert store.cycle_active(claim)


def test_late_original_finish_after_recovery_is_idempotent(database, monkeypatch):
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    monkeypatch.setattr(store, "utcnow", lambda: now)
    monkeypatch.setattr(reconcile, "utcnow", lambda: now)
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    store.record_cycle_step(claim, kind="model", details={"request_id": "late-original"})
    with database() as session:
        session.add(
            LlmClientRequest(
                user_id=7,
                client_request_id="late-original",
                request_sha256="a" * 64,
                state="completed",
                done_json=json.dumps({"status": "settled", "actual_tokens": 63}),
            )
        )
        session.commit()
    later = now + timedelta(minutes=6)
    monkeypatch.setattr(store, "utcnow", lambda: later)
    monkeypatch.setattr(reconcile, "utcnow", lambda: later)
    assert reconcile.reconcile_usage()["resolved"] == 1
    state = finish(claim, actual_tokens=63, goals=[{"id": "stale-learning"}])
    assert state["budget"]["used_tokens"] == 63
    assert state["budget"]["reserved_tokens"] == 0
    assert state["goals"] == [] and state["activity"] is None
    assert reconcile.reconcile_usage()["resolved"] == 0


def test_same_cycle_graph_admission_is_single_flight(database):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    with ThreadPoolExecutor(max_workers=2) as pool:
        started = list(pool.map(lambda _: store.begin_cycle_graph(claim), range(2)))
    assert sorted(started) == [False, True]
    assert store.read_state()["budget"]["reserved_tokens"] == 200
    assert store.cycle_active(claim)


def test_revoked_cycle_can_record_receipt_only_reflection(database):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    for phase in ("observe", "decide", "act"):
        store.record_cycle_phase(claim, phase)
    store.update_settings(
        LifeUpdate(expected_revision=store.read_state()["revision"], stopped=True), actor_user_id=7
    )
    store.record_cycle_phase(claim, "reflect")
    with pytest.raises(LifePolicyError):
        store.record_cycle_step(claim, kind="model", details={"request_id": "new-call"})
    state = finish(claim, goals=[{"id": "stale-learning"}])
    assert state["goals"] == []
    assert state["events"][0]["status"] == "policy_changed"


def test_recovery_counts_new_calls_on_existing_task_and_requires_journal_receipt(
    database, monkeypatch
):
    calls = {
        "before": {"status": "settled", "actual_tokens": 10},
        "new": {"status": "settled", "actual_tokens": 25},
    }
    tasks = {"original-task": {"status": "completed", "calls": calls}}
    monkeypatch.setattr(reconcile, "portfolio_status", lambda *args, **kwargs: {"tasks": tasks})
    steps = [
        {
            "kind": "portfolio",
            "decision_id": "decision",
            "before_task_ids": ["original-task"],
            "before_call_ids": ["before"],
        },
        {
            "kind": "model",
            "decision_id": "decision",
            "opportunity_id": "original-task",
            "request_id": "new",
        },
    ]
    assert reconcile._verified_usage(steps, 7) == 25
    tasks["original-task"]["status"] = "waiting"
    assert reconcile._verified_usage(steps, 7) is None
    tasks["original-task"]["status"] = "completed"
    calls.pop("new")
    assert reconcile._verified_usage(steps, 7) is None


def _process_claim_life(db_url, start, output, connect_args):
    engine = create_engine(db_url, connect_args=connect_args)
    factory = sessionmaker(bind=engine)
    store.get_session_factory = lambda: factory
    try:
        if not start.wait(30):
            raise RuntimeError("test worker start timeout")
        claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
        output.put((store.read_state()["identity_id"], claim))
    finally:
        engine.dispose()


def _spawn_claims(database, connect_args, monkeypatch):
    import multiprocessing

    # Spawn resolves the target module afresh; FHD also has a tests package.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    output = ctx.Queue()
    url = database.kw["bind"].url
    workers = [
        ctx.Process(target=_process_claim_life, args=(url, start, output, connect_args))
        for _ in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        start.set()
        results = []
        for _ in workers:
            try:
                results.append(output.get(timeout=45))
            except Empty:
                exits = ", ".join(f"{worker.name}={worker.exitcode}" for worker in workers)
                pytest.fail(
                    f"Received {len(results)}/{len(workers)} claim results; exit codes: {exits}"
                )
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0, f"{worker.name} exit code: {worker.exitcode}"
        return results
    finally:
        for worker in workers:
            if worker.pid is not None:
                if worker.is_alive():
                    worker.terminate()
                worker.join(10)
                worker.close()
        output.close()
        output.join_thread()


def _assert_one_claim(results, state):
    assert {identity for identity, _ in results} == {state["identity_id"]}
    claims = [claim for _, claim in results if claim is not None]
    assert len(claims) == 1
    assert store.read_state()["activity"]["id"] == claims[0]["cycle_id"]
    return claims[0]


@pytest.mark.parametrize("preceding_test_root", [None, "FHD"])
def test_spawned_processes_share_persistent_identity_and_one_claim(
    database, monkeypatch, preceding_test_root
):
    if preceding_test_root:
        modstore_root = Path(__file__).resolve().parents[1]
        monkeypatch.syspath_prepend(str(modstore_root.parents[1] / preceding_test_root))
    state = configure()
    claim = _assert_one_claim(_spawn_claims(database, {"timeout": 10}, monkeypatch), state)
    assert finish(claim)["budget"]["used_tokens"] == 50


def _checkpoint_act(claim, actual_tokens):
    assert store.begin_cycle_graph(claim)
    for phase in ("observe", "decide", "act"):
        store.record_cycle_phase(claim, phase)
    store.record_cycle_step(claim, kind="model", details={"request_id": "checkpoint-original"})
    fields = {
        "result": {
            "status": "completed",
            "goals": [{"id": "original-goal", "decision_id": "original-decision"}],
        },
        "actual_tokens": actual_tokens,
        "evidence_refs": ["receipt:original"],
    }
    store.record_cycle_checkpoint(claim, "act", **fields)
    store.record_cycle_checkpoint(claim, "act", **fields)
    assert store.read_state()["activity"]["checkpoint_phase"] == "act"
    return fields


def test_crash_after_effect_checkpoint_preserves_original_readback_once(database, monkeypatch):
    now = datetime(2026, 11, 23, 4, tzinfo=UTC)
    monkeypatch.setattr(store, "utcnow", lambda: now)
    monkeypatch.setattr(reconcile, "utcnow", lambda: now)
    initial = configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    fields = _checkpoint_act(claim, 63)
    with pytest.raises(LifePolicyError):
        store.record_cycle_checkpoint(claim, "act", **{**fields, "actual_tokens": 99})
    # A persisted node result alone is not proof that the provider finished.
    later = now + timedelta(minutes=6)
    monkeypatch.setattr(store, "utcnow", lambda: later)
    monkeypatch.setattr(reconcile, "utcnow", lambda: later)
    assert reconcile.reconcile_usage() == {"resolved": 0, "waiting": 1}
    assert store.read_state()["budget"]["reserved_tokens"] == 200
    with database() as session:
        session.add(
            LlmClientRequest(
                user_id=7,
                client_request_id="checkpoint-original",
                request_sha256="c" * 64,
                state="completed",
                done_json=json.dumps({"status": "settled", "actual_tokens": 63}),
            )
        )
        session.commit()
    assert reconcile.reconcile_usage() == {"resolved": 1, "waiting": 0}
    assert reconcile.reconcile_usage() == {"resolved": 0, "waiting": 0}
    state = store.read_state()
    assert state["identity_id"] == initial["identity_id"]
    assert state["activity"] is None and state["goals"] == []
    assert state["budget"]["used_tokens"] == 63
    assert state["budget"]["reserved_tokens"] == 0
    recovered = state["events"][0]["details"]["graph_checkpoint_recovery"]
    assert recovered["phase"] == "act" and recovered["usage_matches_reported"] is True
    assert recovered["result_refs"] == ["goal:original-goal", "portfolio:original-decision"]
    assert not recovered["replayed"] and not recovered["learning_applied"]
    assert not recovered["business_outcome_verified"]
    assert finish(claim, actual_tokens=63)["budget"]["used_tokens"] == 63


def test_checkpoint_survives_stop_and_is_not_execution_authority(database):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    fields = _checkpoint_act(claim, None)
    store.update_settings(
        LifeUpdate(expected_revision=store.read_state()["revision"], stopped=True), actor_user_id=7
    )
    store.record_cycle_phase(claim, "reflect")
    with pytest.raises(LifePolicyError):
        store.record_cycle_checkpoint({**claim, "owner_user_id": 8}, "reflect", **fields)
    store.record_cycle_checkpoint(claim, "reflect", **fields)
    assert not store.cycle_active(claim)
    assert store.read_state()["activity"]["checkpoint_phase"] == "reflect"
    final = finish(claim, actual_tokens=None, goals=[{"id": "must-not-be-adopted"}])
    assert final["status"] == "stopped" and final["goals"] == []
    assert final["budget"]["reserved_tokens"] == 200
    assert final["events"][0]["details"]["graph_checkpoints"]["reflect"]["reported_tokens"] is None


@pytest.mark.skipif(
    not os.environ.get("MODSTORE_TEST_POSTGRES_URL"),
    reason="isolated native PostgreSQL acceptance requires MODSTORE_TEST_POSTGRES_URL",
)
def test_native_postgres_process_claim_checkpoint_and_pool_release(monkeypatch):
    url = os.environ["MODSTORE_TEST_POSTGRES_URL"]
    admin = create_engine(url)
    assert admin.dialect.name == "postgresql"
    schema = f"xiaoc_life_{uuid4().hex}"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = None
    try:
        options = {"options": f"-csearch_path={schema}"}
        engine = create_engine(url, connect_args=options, pool_pre_ping=True)
        factory = _prepare_database(engine, monkeypatch)
        initial = configure()
        claim = _assert_one_claim(_spawn_claims(factory, options, monkeypatch), initial)
        _checkpoint_act(claim, 63)
        with factory() as session:
            session.add(
                LlmClientRequest(
                    user_id=7,
                    client_request_id="checkpoint-original",
                    request_sha256="e" * 64,
                    state="completed",
                    done_json=json.dumps({"status": "settled", "actual_tokens": 63}),
                )
            )
            session.commit()
        stopped = store.update_settings(
            LifeUpdate(expected_revision=store.read_state()["revision"], stopped=True),
            actor_user_id=7,
        )
        assert stopped["status"] == "stopped" and not store.cycle_active(claim)
        later = store.utcnow() + timedelta(minutes=6)
        monkeypatch.setattr(store, "utcnow", lambda: later)
        monkeypatch.setattr(reconcile, "utcnow", lambda: later)
        assert reconcile.reconcile_usage()["resolved"] == 1
        assert reconcile.reconcile_usage()["resolved"] == 0
        state = store.read_state()
        assert state["identity_id"] == initial["identity_id"]
        assert state["budget"]["reserved_tokens"] == 0
        assert state["events"][0]["actual_tokens"] == 63
        assert not state["events"][0]["details"]["graph_checkpoint_recovery"]["replayed"]
        assert engine.pool.checkedout() == 0
    finally:
        try:
            if engine is not None:
                engine.dispose()
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            admin.dispose()


def test_unreceipted_provider_attempt_cannot_be_reconciled_as_zero(database, monkeypatch):
    now = datetime(2026, 11, 24, tzinfo=UTC)
    monkeypatch.setattr(store, "utcnow", lambda: now)
    monkeypatch.setattr(reconcile, "utcnow", lambda: now)
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
    store.mark_model_attempt(claim)
    assert store.read_state()["budget"]["reserved_tokens"] == 200
    late = now + timedelta(minutes=6)
    monkeypatch.setattr(store, "utcnow", lambda: late)
    monkeypatch.setattr(reconcile, "utcnow", lambda: late)
    assert reconcile.reconcile_usage() == {"resolved": 0, "waiting": 1}
    assert store.read_state()["budget"]["reserved_tokens"] == 200
    finish(claim, actual_tokens=None)
    assert reconcile.reconcile_usage() == {"resolved": 0, "waiting": 1}
    assert store.read_state()["budget"]["reserved_tokens"] == 200
    assert store.read_state()["unknown_usage"] is True
    assert store.claim_cycle(domain="enterprise", reserve_tokens=0) is None


def test_native_act_cas_is_permanent_and_preserves_original_task_identity(database):
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=120)
    assert store.begin_cycle_graph(claim)
    store.record_cycle_phase(claim, "observe")
    store.record_cycle_phase(claim, "decide")
    candidate = store.pending_native_act_claim()
    assert candidate is not None and candidate["cycle_id"] == claim["cycle_id"]
    assert candidate["lease_token"] == claim["lease_token"]
    assert store.admit_cycle_act(candidate)
    assert not store.admit_cycle_act(claim)
    assert store.pending_native_act_claim() is None
    store.record_cycle_phase(claim, "act")
    assert not store.admit_cycle_act(claim)
    assert finish(claim)["budget"]["used_tokens"] == 50


@pytest.mark.skipif(
    not os.environ.get("MODSTORE_TEST_POSTGRES_URL"),
    reason="requires isolated PostgreSQL for real connection fault injection",
)
def test_postgres_backend_disconnect_preserves_original_lease(monkeypatch):
    from sqlalchemy.exc import DBAPIError

    url = os.environ["MODSTORE_TEST_POSTGRES_URL"]
    admin = create_engine(url)
    schema = f"xiaoc_life_disconnect_{uuid4().hex}"
    with admin.begin() as ctl:
        ctl.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = None
    try:
        engine = create_engine(
            url,
            connect_args={"options": f"-csearch_path={schema}"},
            pool_pre_ping=True,
        )
        factory = _prepare_database(engine, monkeypatch)
        original = configure()
        claim = store.claim_cycle(domain="enterprise", reserve_tokens=200)
        assert claim is not None
        with factory() as session:
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            assert type(pid) is int
            with admin.begin() as ctl:
                assert ctl.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}) is True
            with pytest.raises(DBAPIError):
                session.execute(text("SELECT 1"))
            session.rollback()
        recovered = store.read_state()
        assert recovered["identity_id"] == original["identity_id"]
        assert recovered["activity"]["id"] == claim["cycle_id"]
        assert recovered["budget"]["reserved_tokens"] == 200
        assert store.claim_cycle(domain="enterprise", reserve_tokens=200) is None
        assert engine.pool.checkedout() == 0
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as ctl:
            ctl.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_functional_identity_receipt_uses_original_sql_ledger(database, monkeypatch):
    from modstore_server import xiaoc_self_model as self_model

    monkeypatch.setenv("MODSTORE_GIT_SHA", "a" * 40)
    monkeypatch.setenv("MODSTORE_EXPECTED_GIT_SHA", "a" * 40)
    monkeypatch.setenv("MODSTORE_RELEASE_ARTIFACT_SHA256", "b" * 64)
    configure()
    receipt = self_model.record_identity_check()
    assert receipt["status"] == "pass"
    state = store.read_state()
    assert self_model.project(state)["identity_readback"]["evidence_ref"] == receipt["evidence_ref"]
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=80)
    assert claim["execution_scope"] == self_model.execution_scope(state)
    finished = finish(claim)
    assert self_model.project(finished)["performance"]["current_scope_count"] == 1
    with database() as session:
        principal = session.get(User, 7)
        principal.account_state = "disabled"
        session.commit()
    assert self_model.project(store.read_state())["identity_readback"]["status"] == "unverified"


def test_due_identity_readback_refreshes_after_policy_change_without_consumption(
    database, monkeypatch
):
    from modstore_server import xiaoc_self_model as self_model

    monkeypatch.setenv("MODSTORE_GIT_SHA", "a" * 40)
    monkeypatch.setenv("MODSTORE_EXPECTED_GIT_SHA", "a" * 40)
    monkeypatch.setenv("MODSTORE_RELEASE_ARTIFACT_SHA256", "b" * 64)
    initial = configure()
    first = self_model.record_identity_check(only_if_due=True)
    assert first["status"] == "pass"
    assert self_model.record_identity_check(only_if_due=True) == {
        "status": "not_due",
        "evidence_ref": first["evidence_ref"],
    }
    paused = store.update_settings(
        LifeUpdate(expected_revision=initial["revision"], paused=True), actor_user_id=7
    )
    assert self_model.project(paused)["identity_readback"]["status"] == "unverified"
    second = self_model.record_identity_check(only_if_due=True)
    assert second["status"] == "pass" and second["evidence_ref"] != first["evidence_ref"]
    after = store.read_state()
    assert after["paused"] is True
    assert after["budget"] == paused["budget"]
    assert after["goals"] == paused["goals"]
    assert self_model.project(after)["identity_readback"]["evidence_ref"] == second["evidence_ref"]


def test_self_cost_reads_original_request_and_not_reservations(database, monkeypatch):
    from modstore_server import xiaoc_self_metrics as metrics

    monkeypatch.setenv("MODSTORE_GIT_SHA", "a" * 40)
    monkeypatch.setenv("MODSTORE_EXPECTED_GIT_SHA", "a" * 40)
    monkeypatch.setenv("MODSTORE_RELEASE_ARTIFACT_SHA256", "b" * 64)
    configure()
    claim = store.claim_cycle(domain="enterprise", reserve_tokens=80)
    store.record_cycle_step(claim, kind="model", details={"request_id": "self-cost-original"})
    receipt = {
        "request_id": "self-cost-original",
        "owner_user_id": 7,
        "status": "settled",
        "actual_tokens": 3,
        "accrued_cost_cents": 2,
        "reserved_cost_cents": 99,
        "cost_basis": "approved_company_tariff_accrual",
    }
    with database() as session:
        session.add(
            LlmClientRequest(
                user_id=7,
                client_request_id=receipt["request_id"],
                request_sha256="a" * 64,
                state="completed",
                done_json=json.dumps(receipt),
            )
        )
        session.commit()
    state = finish(
        claim,
        actual_tokens=3,
        model="provider/model",
        details={"private_customer_text": "not_part_of_self_metrics"},
    )
    snapshot = metrics.with_cycle_receipts(state)
    assert "not_part_of_self_metrics" not in json.dumps(snapshot["self_cycle_receipts"])
    cost = metrics.read_accrual(snapshot)
    assert cost["cost_cents"] == 2
    assert cost["supplier_cost_cents"] is None
    assert cost["known_cycle_refs"] == ["cycle:" + claim["cycle_id"]]
    with database() as session:
        row = session.scalar(select(LlmClientRequest))
        row.state = "unknown"
        session.commit()
    assert metrics.read_accrual(snapshot)["cost_cents"] is None


def test_self_audit_mapping_keeps_all_existing_anchors_unverified(monkeypatch):
    from modstore_server import strategy_planner, xiaoc_self_metrics

    monkeypatch.setattr(
        strategy_planner,
        "_domain_status",
        lambda: {
            "domains": [{"domain_id": "autonomy", "status": "PASS", "audited_at": "2026-11-23"}]
        },
    )
    result = xiaoc_self_metrics.audit_projection()
    assert result["domain_count"] == 18
    assert result["anchor_count"] == 108
    assert all(row["status"] == "unverified" for row in result["anchors"])
    assert result["historical_domains"]["autonomy"]["status"] == "PASS"


def test_independent_fixture_report_import_is_durable_idempotent_and_not_mastery(
    database, tmp_path
):
    import hashlib

    from modstore_server.xiaoc_self_evidence import (
        annotate_unverified_catalog,
        record_fixture_report,
    )

    layers = {
        "unit": "NOT RUN",
        "integration": "NOT RUN",
        "real_model": "NOT RUN",
        "real_business": "NOT RUN",
        "production": "NOT RUN",
    }
    standard = {
        "standard_version": "fixture-v1",
        "scoring_version": "fixture-only-v1",
        "digital_life_evaluation": {
            "protocol_version": "fixture-v1",
            "layers": list(layers),
            "seeds": [17],
            "scenarios": [
                {
                    "id": "memory",
                    "anchor": "autonomy-B3",
                    "positive": "tests/test_memory.py::test_positive",
                    "negative": "tests/test_memory.py::test_negative",
                }
            ],
        },
    }
    standard_path = tmp_path / "standard.json"
    standard_path.write_text(json.dumps(standard), encoding="utf-8")
    raw_standard = standard_path.read_bytes()
    report = {
        "standard_sha256": hashlib.sha256(raw_standard).hexdigest(),
        "standard_version": "fixture-v1",
        "scoring_version": "fixture-only-v1",
        "protocol_version": "fixture-v1",
        "seeds": [17],
        "domain_status": "UNRATED",
        "score": None,
        "evidence_scope": "isolated_fixture_only_not_attested",
        "model_and_budget": "fixture_only_no_live_model_claim",
        "source_sha": "a" * 40,
        "auditor_source_sha": "b" * 40,
        "dataset_sha256": "c" * 64,
        "environment_sha256": "d" * 64,
        "scenarios": [{"id": "memory", "anchor": "autonomy-B3", "layers": layers, "trials": []}],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    first = record_fixture_report(report_path, standard_path)
    assert first["status"] == "historical_fixture"
    assert record_fixture_report(report_path, standard_path) == first
    state = store.read_state()
    assert len(state["self_fixture_checks"]) == 1
    assert state["self_fixture_checks"][0]["id"] == first["evidence_ref"]
    catalog = {
        "status": "catalog_only",
        "standard_sha256": report["standard_sha256"],
        "anchors": [{"anchor_id": "autonomy-B3", "status": "unverified"}],
    }
    annotated = annotate_unverified_catalog(
        catalog, state["self_fixture_checks"], current_sha=report["source_sha"]
    )
    assert annotated["anchors"][0]["status"] == "unverified"
    assert annotated["anchors"][0]["fixture_history"][0]["reported_integration"] == "NOT RUN"
