"""Real SQL ownership, concurrent mode changes and lifecycle accounting."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
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


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'life.sqlite'}", connect_args={"timeout": 10})
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
    yield factory
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
            {**self_model, "status": "hypothesis"} if learned else before["self_model"]
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
    assert len([event for event in state["events"] if event["kind"] == "reflection"]) == 2


def test_budget_updates_never_clear_consumption_or_allow_unbounded_authority(database):
    configure()
    finish(store.claim_cycle(domain="enterprise", reserve_tokens=200), actual_tokens=150)
    state = configure(daily_token_limit=100)
    assert state["budget"]["used_tokens"] == 150
    assert store.claim_cycle(domain="enterprise", reserve_tokens=1) is None
    readback = store.claim_cycle(domain="enterprise", reserve_tokens=0)
    assert readback["reserved_tokens"] == 0
    state = finish(readback, actual_tokens=0)
    assert state["budget"]["reserved_tokens"] == 0
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
