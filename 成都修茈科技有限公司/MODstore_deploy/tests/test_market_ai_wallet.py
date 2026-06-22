from __future__ import annotations

import uuid
from decimal import Decimal


def _auth_headers_for_user() -> tuple[int, dict[str, str]]:
    from modstore_server.auth_service import create_access_token
    from modstore_server.models import User, get_session_factory

    username = f"ai_wallet_{uuid.uuid4().hex[:10]}"
    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=username,
            email=f"{username}@pytest.local",
            password_hash="x",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = int(user.id)
    token = create_access_token(user_id, username)
    return user_id, {"Authorization": f"Bearer {token}"}


def _set_wallet_balance(user_id: int, amount: str) -> None:
    from modstore_server.models import Wallet, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        wallet = session.query(Wallet).filter(Wallet.user_id == user_id).first()
        if wallet is None:
            wallet = Wallet(user_id=user_id, balance=Decimal("0.00"))
            session.add(wallet)
            session.flush()
        wallet.balance = Decimal(amount)
        session.commit()


def test_ai_wallet_preauthorize_and_settle_are_idempotent(client):
    user_id, auth_headers = _auth_headers_for_user()
    _set_wallet_balance(user_id, "0.10")

    preauth_body = {
        "amount": 0.03,
        "provider": "xcauto",
        "model": "xcauto-account",
        "request_id": "run-1:llm-1",
        "idempotency_key": "run-1:llm-1:preauth",
    }
    first = client.post("/api/wallet/ai/preauthorize", json=preauth_body, headers=auth_headers)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["ok"] is True
    assert first_body["balance"] == "0.07"
    hold_no = first_body["hold"]["hold_no"]

    duplicate = client.post("/api/wallet/ai/preauthorize", json=preauth_body, headers=auth_headers)
    assert duplicate.status_code == 200, duplicate.text
    duplicate_body = duplicate.json()
    assert duplicate_body["idempotent"] is True
    assert duplicate_body["hold"]["hold_no"] == hold_no
    assert duplicate_body["balance"] == "0.07"

    settle_body = {
        "hold_no": hold_no,
        "actual_amount": 0.02,
        "idempotency_key": "run-1:llm-1:settle",
    }
    settled = client.post("/api/wallet/ai/settle", json=settle_body, headers=auth_headers)
    assert settled.status_code == 200, settled.text
    assert settled.json()["balance"] == "0.08"
    assert settled.json()["hold"]["status"] == "settled"

    settled_again = client.post("/api/wallet/ai/settle", json=settle_body, headers=auth_headers)
    assert settled_again.status_code == 200, settled_again.text
    assert settled_again.json()["idempotent"] is True
    assert settled_again.json()["balance"] == "0.08"


def test_ai_wallet_refund_settled_hold_is_idempotent(client):
    user_id, auth_headers = _auth_headers_for_user()
    _set_wallet_balance(user_id, "0.10")

    preauth = client.post(
        "/api/wallet/ai/preauthorize",
        json={
            "amount": 0.03,
            "provider": "xcauto",
            "model": "xcauto-account",
            "request_id": "run-refund:tool-1",
            "idempotency_key": "run-refund:tool-1:preauth",
        },
        headers=auth_headers,
    )
    assert preauth.status_code == 200, preauth.text
    hold_no = preauth.json()["hold"]["hold_no"]

    settled = client.post(
        "/api/wallet/ai/settle",
        json={
            "hold_no": hold_no,
            "actual_amount": 0.02,
            "idempotency_key": "run-refund:tool-1:settle",
        },
        headers=auth_headers,
    )
    assert settled.status_code == 200, settled.text
    assert settled.json()["balance"] == "0.08"

    refund_body = {
        "hold_no": hold_no,
        "refund_amount": 0.02,
        "reason": "tool failed",
        "idempotency_key": "run-refund:tool-1:refund",
    }
    refunded = client.post("/api/wallet/ai/refund", json=refund_body, headers=auth_headers)
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["balance"] == "0.10"
    assert refunded.json()["refund"]["status"] == "refunded"
    assert refunded.json()["refund"]["amount"] == "0.02"

    refunded_again = client.post("/api/wallet/ai/refund", json=refund_body, headers=auth_headers)
    assert refunded_again.status_code == 200, refunded_again.text
    assert refunded_again.json()["idempotent"] is True
    assert refunded_again.json()["balance"] == "0.10"

    over_refund = client.post(
        "/api/wallet/ai/refund",
        json={
            "hold_no": hold_no,
            "refund_amount": 0.01,
            "reason": "duplicate refund",
            "idempotency_key": "run-refund:tool-1:refund-extra",
        },
        headers=auth_headers,
    )
    assert over_refund.status_code == 400
    assert "超过可退余额" in over_refund.text


def test_ai_wallet_preauthorize_rejects_insufficient_balance(client):
    user_id, auth_headers = _auth_headers_for_user()
    _set_wallet_balance(user_id, "0.01")

    r = client.post(
        "/api/wallet/ai/preauthorize",
        json={
            "amount": 0.03,
            "provider": "xcauto",
            "model": "xcauto-account",
            "request_id": "run-low",
            "idempotency_key": "run-low:preauth",
        },
        headers=auth_headers,
    )

    assert r.status_code == 402
    assert "余额不足" in r.text
