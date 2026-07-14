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


def test_non_admin_cannot_credit_target_user_wallet(client):
    target_id, user_headers = _auth_headers_for_user()

    resp = client.post(
        f"/api/admin/users/{target_id}/wallet/credit",
        json={"amount": 1},
        headers=user_headers,
    )

    assert resp.status_code == 403
