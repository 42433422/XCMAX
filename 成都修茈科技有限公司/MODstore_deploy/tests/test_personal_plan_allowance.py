"""Free activation must not mint unverified credit or bypass the active ledger."""

from __future__ import annotations

import importlib.util
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from alembic.migration import MigrationContext
from alembic.operations import Operations
from modstore_server.models import (
    PersonalPlanAllowanceClaim,
    Transaction,
    User,
    VerificationCode,
    Wallet,
    get_engine,
    get_session_factory,
    init_db,
)


@pytest.fixture(autouse=True)
def allowance_database(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "allowance.db"))
    monkeypatch.setenv("MODSTORE_PERSONAL_ALLOWANCE_BUDGET_CENTS", "1000")
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)


@pytest.fixture
def client(isolated_modstore):
    # Each case is a separate transport peer; retain the production rate limiter.
    transport = TestClient(
        isolated_modstore["client"].app, client=(f"allowance-{uuid.uuid4().hex}", 50000)
    )
    yield transport
    transport.close()


def _register(client, *, verified=False):
    name = f"allowance_{uuid.uuid4().hex[:12]}"
    body = {"username": name, "password": "allowance-pass-12"}
    if verified:
        body.update(email=f"{name}@example.test", verification_code="437619")
        with get_session_factory().begin() as session:
            session.add(
                VerificationCode(
                    email=body["email"],
                    code=body["verification_code"],
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
    response = client.post("/api/auth/register", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    return data["user"]["id"], {"Authorization": f"Bearer {data['access_token']}"}


@pytest.fixture
def java_wallet(monkeypatch):
    """Real HTTP at the existing internal Java contract; no Java runtime substitute."""
    state = {"requests": [], "credits": {}, "drop_ack": False, "fail": False, "override": {}}
    secret = uuid.uuid4().hex

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/api/internal/payment/wallet/credit"
            assert self.headers["X-Internal-Api-Key"] == secret
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(body)
            if state["fail"]:
                self.send_response(503)
                self.end_headers()
                return
            state["credits"].setdefault(body["idempotency_key"], body)
            if state["drop_ack"]:
                self.close_connection = True
                return
            payload = json.dumps(
                {
                    "ok": True,
                    "source": "java_postgresql",
                    "user_id": body["user_id"],
                    "amount": body["amount"],
                    "idempotency_key": body["idempotency_key"],
                    "status": "completed",
                    "balance": str(
                        sum(
                            Decimal(credit["amount"])
                            for credit in state["credits"].values()
                            if credit["user_id"] == body["user_id"]
                        )
                    ),
                    **state["override"],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.setenv("MODSTORE_INTERNAL_API_KEY", secret)
    monkeypatch.setenv("JAVA_PAYMENT_SERVICE_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_unverified_accounts_can_activate_without_minting_platform_credit(client):
    for _ in range(3):
        user_id, headers = _register(client)
        response = client.post("/api/account/personal-plan", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["desktop_access"] is True
        with get_session_factory()() as session:
            assert session.query(Wallet).filter_by(user_id=user_id).one().balance == 0
        assert response.json()["allowance"]["status"] == "verification_required"


def test_verified_activation_credits_the_active_java_ledger_once(client, java_wallet):
    user_id, headers = _register(client, verified=True)
    for _ in range(2):
        response = client.post("/api/account/personal-plan", headers=headers)
        assert response.status_code == 200, response.text
    assert len(java_wallet["credits"]) == 1
    assert java_wallet["requests"][0]["idempotency_key"].startswith(
        f"saas-personal-free:{user_id}:"
    )
    assert Decimal(java_wallet["requests"][0]["amount"]) == 5
    with get_session_factory()() as session:
        assert session.query(Wallet).filter_by(user_id=user_id).one().balance == 0
    assert response.json()["allowance"]["status"] == "granted"


@pytest.mark.parametrize("budget", [None, "", "0", "499", "unlimited", "-1", "9" * 30])
def test_no_authorized_campaign_budget_still_enables_the_free_plan(client, monkeypatch, budget):
    if budget is None:
        monkeypatch.delenv("MODSTORE_PERSONAL_ALLOWANCE_BUDGET_CENTS")
    else:
        monkeypatch.setenv("MODSTORE_PERSONAL_ALLOWANCE_BUDGET_CENTS", budget)
    user_id, headers = _register(client, verified=True)
    response = client.post("/api/account/personal-plan", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["active_plan_id"] == "saas-personal-free"
    assert response.json()["allowance"]["status"] == "unavailable"
    with get_session_factory()() as session:
        assert session.query(Wallet).filter_by(user_id=user_id).one().balance == 0
        assert session.query(PersonalPlanAllowanceClaim).count() == 0


def _code(email, *, expired=False, used=False):
    with get_session_factory().begin() as session:
        session.add(
            VerificationCode(
                email=email,
                code="681492",
                used=used,
                expires_at=datetime.now(UTC) + timedelta(minutes=-1 if expired else 5),
            )
        )


@pytest.mark.parametrize("proof", ["none", "historical", "changed_mailbox"])
def test_nonempty_email_or_historical_used_code_is_not_verified_identity(client, proof):
    user_id, headers = _register(client, verified=proof == "changed_mailbox")
    email = f"unverified-{uuid.uuid4().hex}@example.test"
    with get_session_factory().begin() as session:
        session.get(User, user_id).email = email
    if proof == "historical":
        _code(email, used=True)
    response = client.post("/api/account/personal-plan", headers=headers)
    assert response.json()["allowance"]["status"] == "verification_required"
    with get_session_factory()() as session:
        assert session.query(Wallet).filter_by(user_id=user_id).one().balance == 0


def test_blank_account_can_verify_once_and_cannot_replay_or_rebind(client):
    user_id, headers = _register(client)
    assert client.post("/api/account/personal-plan", headers=headers).status_code == 200
    email = "verified-first@example.test"
    _code(email)
    body = {"email": email.upper(), "verification_code": "681492"}
    response = client.post("/api/account/personal-plan", headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["allowance"]["status"] == "granted"
    bootstrap = client.get("/api/account/bootstrap", headers=headers).json()
    assert bootstrap["account"]["allowance"]["status"] == "granted"
    assert bootstrap["user"]["email"] == email
    assert client.post("/api/account/personal-plan", headers=headers, json=body).status_code == 400
    _code("replacement@example.test")
    replacement = {"email": "replacement@example.test", "verification_code": "681492"}
    assert (
        client.post("/api/account/personal-plan", headers=headers, json=replacement).status_code
        == 409
    )
    with get_session_factory()() as session:
        assert session.get(User, user_id).email == email
        assert session.query(Wallet).filter_by(user_id=user_id).one().balance == 5
        assert session.query(PersonalPlanAllowanceClaim).count() == 1


@pytest.mark.parametrize("invalid", ["expired", "used", "wrong"])
def test_invalid_email_proof_never_grants_or_binds_identity(client, invalid):
    user_id, headers = _register(client)
    email = "invalid-proof@example.test"
    _code(email, expired=invalid == "expired", used=invalid == "used")
    response = client.post(
        "/api/account/personal-plan",
        headers=headers,
        json={"email": email, "verification_code": "000000" if invalid == "wrong" else "681492"},
    )
    assert response.status_code == 400, response.text
    with get_session_factory()() as session:
        assert session.get(User, user_id).email is None
        assert session.query(PersonalPlanAllowanceClaim).count() == 0
        assert session.query(Wallet).filter_by(user_id=user_id).one().balance == 0


def test_verified_identity_cannot_reclaim_after_the_old_account_releases_email(client):
    old_id, old_headers = _register(client, verified=True)
    assert (
        client.post("/api/account/personal-plan", headers=old_headers).json()["allowance"]["status"]
        == "granted"
    )
    with get_session_factory().begin() as session:
        old = session.get(User, old_id)
        email = old.email
        old.email = None
        old.verified_email_sha256 = None
        old.deleted_at = datetime.now(UTC)
    new_id, headers = _register(client)
    _code(email)
    response = client.post(
        "/api/account/personal-plan",
        headers=headers,
        json={"email": email, "verification_code": "681492"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["allowance"]["status"] == "already_claimed"
    with get_session_factory()() as session:
        assert session.query(Wallet).filter_by(user_id=new_id).one().balance == 0
        assert session.query(PersonalPlanAllowanceClaim).count() == 1


def test_campaign_budget_serializes_different_accounts(client, monkeypatch):
    monkeypatch.setenv("MODSTORE_PERSONAL_ALLOWANCE_BUDGET_CENTS", "500")
    accounts = [_register(client, verified=True) for _ in range(2)]
    barrier = threading.Barrier(2)

    def activate(account):
        barrier.wait(timeout=10)
        return client.post("/api/account/personal-plan", headers=account[1])

    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(activate, accounts))
    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["allowance"]["status"] for response in responses) == [
        "granted",
        "unavailable",
    ]
    with get_session_factory()() as session:
        assert session.query(PersonalPlanAllowanceClaim).one().amount_cents == 500
        assert sum(wallet.balance for wallet in session.query(Wallet).all()) == 5


def test_same_email_proof_cannot_be_consumed_by_concurrent_accounts(client):
    accounts = [_register(client) for _ in range(2)]
    email = "one-mailbox@example.test"
    _code(email)
    barrier = threading.Barrier(2)

    def activate(account):
        barrier.wait(timeout=10)
        return client.post(
            "/api/account/personal-plan",
            headers=account[1],
            json={"email": email, "verification_code": "681492"},
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(activate, accounts))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with get_session_factory()() as session:
        assert session.query(PersonalPlanAllowanceClaim).count() == 1
        assert sum(wallet.balance for wallet in session.query(Wallet).all()) == 5


@pytest.mark.parametrize("failure", ["drop_ack", "fail"])
def test_unknown_java_outcome_retains_budget_and_backend_for_retry(
    client, java_wallet, monkeypatch, failure
):
    monkeypatch.setenv("MODSTORE_PERSONAL_ALLOWANCE_BUDGET_CENTS", "500")
    user_id, headers = _register(client, verified=True)
    _, other = _register(client, verified=True)
    java_wallet[failure] = True
    response = client.post("/api/account/personal-plan", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["allowance"]["status"] == "pending"
    blocked = client.post("/api/account/personal-plan", headers=other)
    assert blocked.json()["allowance"]["status"] == "unavailable"
    with get_session_factory()() as session:
        claim = session.query(PersonalPlanAllowanceClaim).one()
        key = claim.idempotency_key
        assert claim.status == "pending"
        assert claim.backend == "java"
    java_wallet[failure] = False
    monkeypatch.setenv("PAYMENT_BACKEND", "python")
    monkeypatch.setenv("MODSTORE_PERSONAL_ALLOWANCE_BUDGET_CENTS", "0")
    retried = client.post("/api/account/personal-plan", headers=headers)
    assert retried.json()["allowance"]["status"] == "granted"
    assert [request["idempotency_key"] for request in java_wallet["requests"]] == [key, key]
    assert len(java_wallet["credits"]) == 1
    with get_session_factory()() as session:
        assert session.query(PersonalPlanAllowanceClaim).one().status == "confirmed"
        assert session.query(Wallet).filter_by(user_id=user_id).one().balance == 0
        assert session.query(Transaction).filter_by(user_id=user_id).count() == 0


@pytest.mark.parametrize("first_backend", ["python", "java"])
def test_confirmed_claim_cannot_credit_again_after_backend_switch(
    client, java_wallet, monkeypatch, first_backend
):
    user_id, headers = _register(client, verified=True)
    monkeypatch.setenv("PAYMENT_BACKEND", first_backend)
    first = client.post("/api/account/personal-plan", headers=headers)
    assert first.json()["allowance"]["status"] == "granted"
    monkeypatch.setenv("PAYMENT_BACKEND", "java" if first_backend == "python" else "python")
    assert (
        client.post("/api/account/personal-plan", headers=headers).json()["allowance"]["status"]
        == "granted"
    )
    with get_session_factory()() as session:
        assert session.query(PersonalPlanAllowanceClaim).one().backend == first_backend
        assert session.query(Wallet).filter_by(user_id=user_id).one().balance == (
            5 if first_backend == "python" else 0
        )
    assert len(java_wallet["credits"]) == int(first_backend == "java")


@pytest.mark.parametrize("committed", [False, True])
def test_java_ack_then_local_confirmation_failure_retries_the_same_claim(
    client, java_wallet, monkeypatch, committed
):
    from modstore_server import personal_plan_allowance

    _, headers = _register(client, verified=True)
    factory = get_session_factory()

    class FailingCommit(Session):
        def commit(self):
            self.flush()
            if committed:
                super().commit()
            raise RuntimeError("lost claim commit acknowledgement")

    failed = sessionmaker(bind=factory.kw["bind"], class_=FailingCommit)
    with monkeypatch.context() as scoped:
        scoped.setattr(personal_plan_allowance, "get_session_factory", lambda: failed)
        with pytest.raises(RuntimeError, match="lost claim commit"):
            client.post("/api/account/personal-plan", headers=headers)
    with factory() as session:
        assert session.query(PersonalPlanAllowanceClaim).one().status == (
            "confirmed" if committed else "pending"
        )
    retried = client.post("/api/account/personal-plan", headers=headers)
    assert retried.json()["allowance"]["status"] == "granted"
    assert len(java_wallet["credits"]) == 1
    assert len({request["idempotency_key"] for request in java_wallet["requests"]}) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"ok": False},
        {"source": "python"},
        {"user_id": -1},
        {"amount": "4.00"},
        {"balance": "NaN"},
        {"idempotency_key": "different-key"},
        {"status": "pending"},
    ],
)
def test_java_receipt_must_match_the_reserved_credit(client, java_wallet, override):
    _, headers = _register(client, verified=True)
    java_wallet["override"] = override
    response = client.post("/api/account/personal-plan", headers=headers)
    assert response.json()["allowance"]["status"] == "pending"
    with get_session_factory()() as session:
        assert session.query(PersonalPlanAllowanceClaim).one().status == "pending"
    java_wallet["override"] = {}
    assert (
        client.post("/api/account/personal-plan", headers=headers).json()["allowance"]["status"]
        == "granted"
    )
    assert len(java_wallet["credits"]) == 1


def test_concurrent_java_activation_uses_one_reserved_key(client, java_wallet):
    _, headers = _register(client, verified=True)
    barrier = threading.Barrier(2)

    def activate(_):
        barrier.wait(timeout=10)
        return client.post("/api/account/personal-plan", headers=headers)

    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(activate, range(2)))
    assert [response.json()["allowance"]["status"] for response in responses] == [
        "granted",
        "granted",
    ]
    assert len(java_wallet["requests"]) == 1
    assert len(java_wallet["credits"]) == 1


def test_retry_uses_the_reserved_amount_after_catalog_change(client, java_wallet, monkeypatch):
    from modstore_server import personal_plan_allowance

    _, headers = _register(client, verified=True)
    java_wallet["drop_ack"] = True
    assert (
        client.post("/api/account/personal-plan", headers=headers).json()["allowance"]["status"]
        == "pending"
    )
    monkeypatch.setattr(
        personal_plan_allowance, "account_license_plan", lambda _: {"quota_cents": 1000}
    )
    java_wallet["drop_ack"] = False
    response = client.post("/api/account/personal-plan", headers=headers)
    assert response.json()["allowance"] == {
        "status": "granted",
        "amount_cents": 500,
        "message": "AI 额度已入账。",
    }
    assert [request["amount"] for request in java_wallet["requests"]] == ["5.00", "5.00"]


@pytest.mark.parametrize("committed", [False, True])
def test_java_reservation_must_commit_before_remote_credit(
    client, java_wallet, monkeypatch, committed
):
    from modstore_server import account_api

    _, headers = _register(client, verified=True)
    factory = get_session_factory()

    class FailingCommit(Session):
        def commit(self):
            self.flush()
            if committed:
                super().commit()
            raise RuntimeError("reservation commit failed")

    failed = sessionmaker(bind=factory.kw["bind"], class_=FailingCommit)
    with monkeypatch.context() as scoped:
        scoped.setattr(account_api, "get_session_factory", lambda: failed)
        with pytest.raises(RuntimeError, match="reservation commit failed"):
            client.post("/api/account/personal-plan", headers=headers)
    assert java_wallet["requests"] == []
    with factory() as session:
        assert session.query(PersonalPlanAllowanceClaim).count() == int(committed)
    response = client.post("/api/account/personal-plan", headers=headers)
    assert response.json()["allowance"]["status"] == "granted"
    assert len(java_wallet["credits"]) == 1


@pytest.mark.parametrize("migration_path", ["alembic", "alembic_interrupted", "init_db"])
def test_existing_database_upgrades_idempotently_without_trusting_existing_email(
    client, migration_path, monkeypatch
):
    user_id, _ = _register(client, verified=True)
    engine = get_engine()
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE personal_plan_allowance_claims")
        connection.exec_driver_sql("ALTER TABLE users DROP COLUMN verified_email_sha256")
    if migration_path == "init_db":
        init_db()
        init_db()
    else:
        path = (
            Path(__file__).resolve().parents[1] / "alembic/versions/20261119_personal_allowance.py"
        )
        spec = importlib.util.spec_from_file_location("personal_allowance_migration", path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                if migration_path == "alembic_interrupted":

                    def interrupted_create(*_args, **_kwargs):
                        raise RuntimeError("interrupted after verification column DDL")

                    with monkeypatch.context() as scoped:
                        scoped.setattr(migration.op, "create_table", interrupted_create)
                        with pytest.raises(RuntimeError, match="interrupted after"):
                            migration.upgrade()
                    assert not sa.inspect(connection).has_table("personal_plan_allowance_claims")
                migration.upgrade()
                migration.upgrade()
    constraints = sa.inspect(engine).get_unique_constraints("personal_plan_allowance_claims")
    assert {tuple(item["column_names"]) for item in constraints} == {
        ("plan_id", "identity_sha256"),
        ("idempotency_key",),
    }
    with get_session_factory()() as session:
        assert session.get(User, user_id).email
        assert session.get(User, user_id).verified_email_sha256 is None
        assert session.query(PersonalPlanAllowanceClaim).count() == 0


def test_shared_java_ledger_transaction_does_not_double_count_reserved_budget(
    client, java_wallet, monkeypatch
):
    user_id, headers = _register(client, verified=True)
    assert (
        client.post("/api/account/personal-plan", headers=headers).json()["allowance"]["status"]
        == "granted"
    )
    # Production can share PostgreSQL tables; represent Java's actual financial row.
    with get_session_factory().begin() as session:
        claim = session.query(PersonalPlanAllowanceClaim).one()
        session.add(
            Transaction(
                user_id=user_id,
                amount=5,
                txn_type="admin_credit",
                status="completed",
                idempotency_key=claim.idempotency_key,
            )
        )
    monkeypatch.setenv("PAYMENT_BACKEND", "python")
    _, next_headers = _register(client, verified=True)
    response = client.post("/api/account/personal-plan", headers=next_headers)
    assert response.json()["allowance"]["status"] == "granted"
    _, last_headers = _register(client, verified=True)
    assert (
        client.post("/api/account/personal-plan", headers=last_headers).json()["allowance"][
            "status"
        ]
        == "unavailable"
    )


def test_prior_release_grant_counts_toward_budget_and_cannot_be_credited_again(client, java_wallet):
    user_id, headers = _register(client, verified=True)
    with get_session_factory().begin() as session:
        session.add(
            Transaction(
                user_id=user_id,
                amount=5,
                txn_type="account_license_quota",
                status="completed",
                idempotency_key=f"saas-personal-free:{user_id}",
            )
        )
    assert (
        client.post("/api/account/personal-plan", headers=headers).json()["allowance"]["status"]
        == "granted"
    )
    assert java_wallet["requests"] == []
    _, next_headers = _register(client, verified=True)
    assert (
        client.post("/api/account/personal-plan", headers=next_headers).json()["allowance"][
            "status"
        ]
        == "granted"
    )
    _, last_headers = _register(client, verified=True)
    assert (
        client.post("/api/account/personal-plan", headers=last_headers).json()["allowance"][
            "status"
        ]
        == "unavailable"
    )
    assert len(java_wallet["credits"]) == 1
