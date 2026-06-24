"""统一计费：计次配额 llm_calls 已删，LLM 一律按 token 从钱包 ¥ 扣。

- require/consume_llm_credit 不再走计次配额（即便存在 llm_calls Quota 行也忽略）。
- consume_llm_credit 接受按 token 算出的 charge(¥)，低于最低按最低收。
- 套餐 quotas_json 不再发放 llm_calls。
- PAYMENT_BACKEND=java 时交由 Java 钱包结算（这里放行/不在 python 侧扣）。
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from modstore_server import quota_middleware as qm


@pytest.fixture(autouse=True)
def _init_db():
    """建表（直连 session 的测试不经 app 启动，需手动初始化 schema）。"""
    from modstore_server.db.base import init_db

    init_db()
    yield


def _new_user_with_wallet(balance: str) -> int:
    from modstore_server.models import User, Wallet, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        u = User(
            username=f"bill_{uuid.uuid4().hex[:10]}",
            email=f"bill_{uuid.uuid4().hex[:8]}@pytest.local",
            password_hash="x",
        )
        session.add(u)
        session.commit()
        session.refresh(u)
        uid = int(u.id)
        session.add(Wallet(user_id=uid, balance=Decimal(balance)))
        session.commit()
    return uid


def _balance(uid: int) -> Decimal:
    from modstore_server.models import Wallet, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        w = session.query(Wallet).filter(Wallet.user_id == uid).first()
        return Decimal(str(w.balance)) if w else Decimal("0")


# ─────────────── require_llm_credit ───────────────


def test_require_wallet_sufficient(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    uid = _new_user_with_wallet("1.00")
    from modstore_server.models import get_session_factory

    with get_session_factory()() as s:
        assert qm.require_llm_credit(s, uid, 1) == "wallet"


def test_require_wallet_insufficient_raises_402(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    uid = _new_user_with_wallet("0.00")
    from modstore_server.models import get_session_factory

    with get_session_factory()() as s:
        with pytest.raises(HTTPException) as ei:
            qm.require_llm_credit(s, uid, 1)
        assert ei.value.status_code == 402


def test_require_java_backend_passes(monkeypatch):
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    uid = _new_user_with_wallet("0.00")  # java 侧结算，python 不拦
    from modstore_server.models import get_session_factory

    with get_session_factory()() as s:
        assert qm.require_llm_credit(s, uid, 1) == "java_wallet"


def test_require_ignores_leftover_llm_calls_quota(monkeypatch):
    """关键回归：即便有耗尽的 llm_calls 计次配额行，也不再 403——计次已退役。"""
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    uid = _new_user_with_wallet("1.00")
    from modstore_server.models import Quota, get_session_factory

    with get_session_factory()() as s:
        s.add(Quota(user_id=uid, quota_type="llm_calls", total=0, used=0))  # 已耗尽
        s.commit()
    with get_session_factory()() as s:
        # 旧逻辑此处会 403 配额不足；新逻辑忽略计次、看钱包 → 放行
        assert qm.require_llm_credit(s, uid, 1) == "wallet"


# ─────────────── consume_llm_credit ───────────────


def test_consume_token_charge_deducts_wallet(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    uid = _new_user_with_wallet("1.00")
    from modstore_server.models import get_session_factory

    with get_session_factory()() as s:
        assert qm.consume_llm_credit(s, uid, 1, charge=Decimal("0.05")) == "wallet"
    assert _balance(uid) == Decimal("0.95")


def test_consume_below_min_charges_min(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    monkeypatch.setenv("COSER_DEFAULT_MIN_CHARGE", "0.02")
    uid = _new_user_with_wallet("1.00")
    from modstore_server.models import get_session_factory

    with get_session_factory()() as s:
        qm.consume_llm_credit(s, uid, 1, charge=Decimal("0.001"))  # 低于最低
    assert _balance(uid) == Decimal("0.98")  # 收最低 0.02


def test_consume_no_charge_uses_min(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    monkeypatch.setenv("COSER_DEFAULT_MIN_CHARGE", "0.02")
    uid = _new_user_with_wallet("1.00")
    from modstore_server.models import get_session_factory

    with get_session_factory()() as s:
        qm.consume_llm_credit(s, uid, 1)  # 无 charge → 最低
    assert _balance(uid) == Decimal("0.98")


def test_consume_ignores_llm_calls_quota_charges_wallet(monkeypatch):
    """有 llm_calls 配额也不再走计次，照样按 token 扣钱包。"""
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    uid = _new_user_with_wallet("1.00")
    from modstore_server.models import Quota, get_session_factory

    with get_session_factory()() as s:
        s.add(Quota(user_id=uid, quota_type="llm_calls", total=5000, used=0))
        s.commit()
    with get_session_factory()() as s:
        qm.consume_llm_credit(s, uid, 1, charge=Decimal("0.05"))
    # 钱包被扣（旧逻辑会扣计次、钱包不动）
    assert _balance(uid) == Decimal("0.95")


def test_consume_insufficient_raises_402(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    uid = _new_user_with_wallet("0.01")
    from modstore_server.models import get_session_factory

    with get_session_factory()() as s:
        with pytest.raises(HTTPException) as ei:
            qm.consume_llm_credit(s, uid, 1, charge=Decimal("0.05"))
        assert ei.value.status_code == 402


def test_consume_java_backend_no_python_deduction(monkeypatch):
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    uid = _new_user_with_wallet("1.00")
    from modstore_server.models import get_session_factory

    with get_session_factory()() as s:
        assert qm.consume_llm_credit(s, uid, 1, charge=Decimal("0.05")) == "java_wallet"
    assert _balance(uid) == Decimal("1.00")  # python 钱包不动，交 java


# ─────────────── 套餐不再发计次 ───────────────


# ─────────────── bill_internal_llm_floor（防免费洞） ───────────────


def test_bill_floor_python_charges_min(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    monkeypatch.setenv("COSER_DEFAULT_MIN_CHARGE", "0.02")
    uid = _new_user_with_wallet("1.00")
    from modstore_server.llm_billing import bill_internal_llm_floor

    charged = asyncio.run(bill_internal_llm_floor("", user_id=uid, label="workflow:1"))
    assert charged == Decimal("0.02")
    assert _balance(uid) == Decimal("0.98")


def test_bill_floor_python_token_amount(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    uid = _new_user_with_wallet("1.00")
    from modstore_server.llm_billing import bill_internal_llm_floor

    charged = asyncio.run(
        bill_internal_llm_floor("", user_id=uid, label="wf", amount=Decimal("0.07"))
    )
    assert charged == Decimal("0.07")
    assert _balance(uid) == Decimal("0.93")


def test_bill_floor_java_uses_java_wallet(monkeypatch):
    """java 后端经 JavaWallet 预授权+结算，绝不免费。"""
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.setenv("COSER_DEFAULT_MIN_CHARGE", "0.02")
    calls = {}

    class _FakeHold:
        enabled = True
        hold_no = "h1"

    class _FakeJavaWallet:
        enabled = True

        async def preauthorize(self, auth, amount, provider, model, rid):
            calls["preauth"] = amount
            calls["auth"] = auth
            return _FakeHold()

        async def settle(self, auth, hold, amount, rid):
            calls["settle"] = amount

    import modstore_server.llm_billing as lb

    monkeypatch.setattr(lb, "JavaWalletClient", _FakeJavaWallet)
    charged = asyncio.run(lb.bill_internal_llm_floor("Bearer tok", user_id=5, label="wf"))
    assert charged == Decimal("0.02")
    assert calls["preauth"] == Decimal("0.02")
    assert calls["settle"] == Decimal("0.02")
    assert calls["auth"] == "Bearer tok"  # 带登录态


def test_plan_templates_no_llm_calls():
    import re

    for mod_path in ("modstore_server/db/base.py", "modstore_server/models_db.py"):
        with open(mod_path, encoding="utf-8") as fh:
            src = fh.read()
        assert "llm_calls" not in src, f"{mod_path} 仍在发放 llm_calls 计次配额"
        # quotas_json 仍合法且含 employee_count/storage_mb
        for q in re.findall(r"quotas_json\"?:\s*'(\{[^}]*\})'", src)[:3]:
            import json

            d = json.loads(q)
            assert "llm_calls" not in d
            assert "storage_mb" in d
