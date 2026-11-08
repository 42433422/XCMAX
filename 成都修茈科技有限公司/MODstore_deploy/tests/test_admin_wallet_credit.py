from __future__ import annotations

import uuid
from decimal import Decimal


def _auth_headers_for_user(*, is_admin: bool = False) -> tuple[int, dict[str, str]]:
    from modstore_server.auth_service import create_access_token
    from modstore_server.models import User, get_session_factory

    username = f"wallet_credit_{uuid.uuid4().hex[:10]}"
    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=username,
            email=f"{username}@pytest.local",
            password_hash="x",
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = int(user.id)
    token = create_access_token(user_id, username, is_admin=is_admin)
    return user_id, {"Authorization": f"Bearer {token}"}


def test_admin_can_credit_target_user_wallet(client):
    from modstore_server.models import Transaction, Wallet, get_session_factory

    target_id, _ = _auth_headers_for_user()
    _, admin_headers = _auth_headers_for_user(is_admin=True)

    resp = client.post(
        f"/api/admin/users/{target_id}/wallet/credit",
        json={"amount": 12.34, "description": "后台测试加款"},
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["user_id"] == target_id
    assert body["amount"] == "12.34"
    assert body["balance"] == "12.34"
    sf = get_session_factory()
    with sf() as session:
        wallet = session.query(Wallet).filter(Wallet.user_id == target_id).first()
        assert wallet is not None
        assert Decimal(str(wallet.balance)) == Decimal("12.34")
        txn = (
            session.query(Transaction)
            .filter(Transaction.user_id == target_id, Transaction.txn_type == "admin_credit")
            .first()
        )
        assert txn is not None
        assert Decimal(str(txn.amount)) == Decimal("12.34")
        assert txn.description == "后台测试加款"
        assert txn.idempotency_key.startswith("admin_credit:")


def test_admin_wallet_list_includes_accounts_without_wallet_rows(client):
    target_id, _ = _auth_headers_for_user()
    _, admin_headers = _auth_headers_for_user(is_admin=True)

    resp = client.get("/api/admin/wallets?limit=500", headers=admin_headers)

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    target = next(item for item in items if item["user_id"] == target_id)
    assert target["id"] is None
    assert float(target["balance"]) == 0.0


def test_admin_can_credit_same_user_twice(client):
    from modstore_server.models import Transaction, Wallet, get_session_factory

    target_id, _ = _auth_headers_for_user()
    _, admin_headers = _auth_headers_for_user(is_admin=True)

    for amount in ("1.00", "2.00"):
        resp = client.post(
            f"/api/admin/users/{target_id}/wallet/credit",
            json={"amount": amount, "description": "连续后台加款"},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text

    sf = get_session_factory()
    with sf() as session:
        wallet = session.query(Wallet).filter(Wallet.user_id == target_id).first()
        assert wallet is not None
        assert Decimal(str(wallet.balance)) == Decimal("3.00")
        txns = (
            session.query(Transaction)
            .filter(Transaction.user_id == target_id, Transaction.txn_type == "admin_credit")
            .order_by(Transaction.id)
            .all()
        )
        assert len(txns) == 2
        keys = [txn.idempotency_key for txn in txns]
        assert all(key.startswith("admin_credit:") for key in keys)
        assert len(set(keys)) == 2


def test_java_backend_credits_the_java_wallet_and_leaves_python_empty(client, monkeypatch):
    from modstore_server.models import Wallet, get_session_factory

    target_id, _ = _auth_headers_for_user()
    _, admin_headers = _auth_headers_for_user(is_admin=True)
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.setenv("MODSTORE_INTERNAL_API_KEY", "internal-test")
    monkeypatch.setenv("JAVA_PAYMENT_SERVICE_URL", "http://java.test")
    seen: dict = {}

    class _Response:
        status_code = 200

        def json(self):
            return {
                "ok": True,
                "source": "java_postgresql",
                "user_id": target_id,
                "amount": "12.34",
                "balance": "12.34",
                "new_balance": "12.34",
            }

    def _request(method, url, **kwargs):
        seen["method"] = method
        seen["url"] = url
        seen["json"] = kwargs.get("json")
        seen["headers"] = kwargs.get("headers")
        return _Response()

    monkeypatch.setattr("modstore_server.java_wallet_admin.httpx.request", _request)

    resp = client.post(
        f"/api/admin/users/{target_id}/wallet/credit",
        json={"amount": 12.34, "description": "Java 账加款"},
        headers=admin_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "java_postgresql"
    assert body["balance"] == "12.34"
    assert seen["method"] == "POST"
    assert seen["url"] == "http://java.test/api/internal/payment/wallet/credit"
    assert seen["headers"]["X-Internal-Api-Key"] == "internal-test"
    assert seen["json"]["user_id"] == target_id
    assert seen["json"]["description"] == "Java 账加款"
    assert seen["json"]["idempotency_key"].startswith(f"admin_credit:{target_id}:")
    sf = get_session_factory()
    with sf() as session:
        wallet = session.query(Wallet).filter(Wallet.user_id == target_id).first()
        assert wallet is None


def test_java_backend_wallet_list_reads_java(client, monkeypatch):
    _, admin_headers = _auth_headers_for_user(is_admin=True)
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.setenv("MODSTORE_INTERNAL_API_KEY", "internal-test")

    class _Response:
        status_code = 200

        def json(self):
            return {
                "ok": True,
                "source": "java_postgresql",
                "items": [{"user_id": 33, "balance": "0.83"}],
                "total": 1,
            }

    monkeypatch.setattr(
        "modstore_server.java_wallet_admin.httpx.request",
        lambda *args, **kwargs: _Response(),
    )

    resp = client.get("/api/admin/wallets?limit=20&offset=0", headers=admin_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["source"] == "java_postgresql"
    assert resp.json()["items"][0]["balance"] == "0.83"


def test_java_backend_refuses_credit_without_the_internal_key(client, monkeypatch):
    from modstore_server.models import Wallet, get_session_factory

    target_id, _ = _auth_headers_for_user()
    _, admin_headers = _auth_headers_for_user(is_admin=True)
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.delenv("MODSTORE_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)

    resp = client.post(
        f"/api/admin/users/{target_id}/wallet/credit",
        json={"amount": 1},
        headers=admin_headers,
    )

    assert resp.status_code == 503
    sf = get_session_factory()
    with sf() as session:
        assert session.query(Wallet).filter(Wallet.user_id == target_id).first() is None


def test_non_admin_cannot_credit_target_user_wallet(client):
    target_id, user_headers = _auth_headers_for_user()

    resp = client.post(
        f"/api/admin/users/{target_id}/wallet/credit",
        json={"amount": 1},
        headers=user_headers,
    )

    assert resp.status_code == 403
