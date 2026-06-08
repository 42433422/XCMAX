"""账号等级与经验体系：单元 + 集成（Python 路径）。"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("fastapi")


def _make_user(username_prefix: str = "lvl_user"):
    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=f"{username_prefix}_{uuid.uuid4().hex[:10]}",
            email=f"{username_prefix}_{uuid.uuid4().hex[:6]}@pytest.local",
            password_hash="x",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


def _get_user_exp(user_id: int) -> int:
    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        u = session.query(User).filter(User.id == user_id).first()
        return int(getattr(u, "experience", 0) or 0)


def test_xp_from_amount_one_yuan_equals_100():
    from modstore_server import account_level_service

    assert account_level_service.xp_from_amount(1) == 100
    assert account_level_service.xp_from_amount(0.99) == 99
    assert account_level_service.xp_from_amount(12.34) == 1234
    assert account_level_service.xp_from_amount(0) == 0
    assert account_level_service.xp_from_amount(-5) == 0
    assert account_level_service.xp_from_amount(None) == 0


def test_build_level_profile_thresholds_and_progress():
    from modstore_server import account_level_service

    p0 = account_level_service.build_level_profile(0)
    assert p0.level == 1 and p0.title == "新手"
    assert p0.next_level_min_exp == 1_000
    assert p0.progress == 0.0

    p_mid = account_level_service.build_level_profile(2_500)
    assert p_mid.level == 2 and p_mid.title == "探索者"
    assert p_mid.current_level_min_exp == 1_000
    assert p_mid.next_level_min_exp == 5_000
    assert 0.0 < p_mid.progress < 1.0

    p_top = account_level_service.build_level_profile(10_000_000)
    assert p_top.next_level_min_exp is None
    assert p_top.progress == 1.0


def test_apply_order_xp_idempotent_and_includes_wallet(client):
    from modstore_server import account_level_service
    from modstore_server.models import AccountExperienceLedger, get_session_factory

    sf = get_session_factory()
    user_id = _make_user("lvl_apply")
    order_no = f"PYTEST-XP-{uuid.uuid4().hex[:10]}"

    with sf() as session:
        first = account_level_service.apply_order_xp(
            session,
            user_id=user_id,
            out_trade_no=order_no,
            amount_yuan=12.34,
            order_kind="item",
            item_id=42,
        )
        session.commit()
    assert first == 1234
    assert _get_user_exp(user_id) == 1234

    with sf() as session:
        second = account_level_service.apply_order_xp(
            session,
            user_id=user_id,
            out_trade_no=order_no,
            amount_yuan=12.34,
            order_kind="item",
            item_id=42,
        )
        session.commit()
    assert second == 0
    assert _get_user_exp(user_id) == 1234

    # 钱包充值同样计入：99 元 = 9900 经验
    with sf() as session:
        wallet_xp = account_level_service.apply_order_xp(
            session,
            user_id=user_id,
            out_trade_no=f"WALLET-{uuid.uuid4().hex[:8]}",
            amount_yuan=99,
            order_kind="wallet",
        )
        session.commit()
    assert wallet_xp == 9900
    assert _get_user_exp(user_id) == 1234 + 9900

    with sf() as session:
        ledger = (
            session.query(AccountExperienceLedger)
            .filter(AccountExperienceLedger.user_id == user_id)
            .all()
        )
    assert len(ledger) == 2
    assert {e.source_type for e in ledger} == {"order_paid"}


def test_revoke_order_xp_idempotent(client):
    from modstore_server import account_level_service
    from modstore_server.models import get_session_factory

    sf = get_session_factory()
    user_id = _make_user("lvl_revoke")
    order_no = f"PYTEST-XP-RV-{uuid.uuid4().hex[:10]}"

    with sf() as session:
        account_level_service.apply_order_xp(
            session,
            user_id=user_id,
            out_trade_no=order_no,
            amount_yuan=5,
            order_kind="plan",
            plan_id="plan_basic",
        )
        session.commit()
    assert _get_user_exp(user_id) == 500

    with sf() as session:
        revoked = account_level_service.revoke_order_xp(
            session,
            user_id=user_id,
            out_trade_no=order_no,
        )
        session.commit()
    assert revoked == 500
    assert _get_user_exp(user_id) == 0

    with sf() as session:
        revoked_again = account_level_service.revoke_order_xp(
            session,
            user_id=user_id,
            out_trade_no=order_no,
        )
        session.commit()
    assert revoked_again == 0
    assert _get_user_exp(user_id) == 0

    with sf() as session:
        unknown = account_level_service.revoke_order_xp(
            session,
            user_id=user_id,
            out_trade_no=f"NEVER-PAID-{uuid.uuid4().hex[:6]}",
        )
        session.commit()
    assert unknown == 0


def test_me_returns_level_profile(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "level_profile" in data
    profile = data["level_profile"]
    assert profile["level"] == 1
    assert profile["title"] == "新手"
    assert profile["experience"] == 0
    assert profile["next_level_min_exp"] == 1_000
    assert profile["progress"] == 0.0
