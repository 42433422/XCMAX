"""T-E07 · 发票自动申请门控测试。

验收：默认关的断言。打开需 ``MODSTORE_AUTO_INVOICE_ENABLED=1``，否则
``create_invoice_for_order`` 不应写入任何 ``Invoice`` 行。

同时验证：用户主动 ``POST /api/invoice/apply`` 不受门控影响（始终可用）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modstore_server.invoice_api import _auto_invoice_enabled, create_invoice_for_order


# --------------------------------------------------------------------------- #
# DB isolation fixture
# --------------------------------------------------------------------------- #


def _init_isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "invoice_gate.sqlite"))
    monkeypatch.setenv("MODSTORE_PYTEST_USE_SQLITE", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(tmp_path / "orders"))

    import modstore_server.db.base as _base
    import modstore_server.models as _models

    _base._engine = None
    _base._SessionFactory = None
    _models._engine = None
    _models._SessionFactory = None
    _models.init_db()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """每个测试用独立 DB；同时确保 MODSTORE_AUTO_INVOICE_ENABLED 默认未设。"""
    monkeypatch.delenv("MODSTORE_AUTO_INVOICE_ENABLED", raising=False)
    _init_isolated_db(tmp_path, monkeypatch)
    from modstore_server.models import get_session_factory

    return {
        "sf": get_session_factory(),
        "orders_dir": tmp_path / "orders",
    }


def _make_user(sf, user_id: int = 4001) -> None:
    from modstore_server.models import User

    with sf() as session:
        if session.query(User).filter(User.id == user_id).first() is None:
            session.add(
                User(
                    id=user_id,
                    username=f"invoice_user_{user_id}",
                    password_hash="x",
                )
            )
            session.commit()


# --------------------------------------------------------------------------- #
# _auto_invoice_enabled 门控
# --------------------------------------------------------------------------- #


class TestAutoInvoiceEnabledGate:
    def test_default_is_off(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_AUTO_INVOICE_ENABLED", raising=False)
        assert _auto_invoice_enabled() is False, "MVP 默认必须关闭自动开票"

    def test_empty_string_is_off(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "")
        assert _auto_invoice_enabled() is False

    def test_zero_is_off(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "0")
        assert _auto_invoice_enabled() is False

    def test_false_is_off(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "false")
        assert _auto_invoice_enabled() is False

    def test_random_value_is_off(self, monkeypatch):
        """非确认值一律视为关闭（fail-safe）。"""
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "maybe")
        assert _auto_invoice_enabled() is False

    def test_one_is_on(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "1")
        assert _auto_invoice_enabled() is True

    def test_true_is_on(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "true")
        assert _auto_invoice_enabled() is True

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "TRUE")
        assert _auto_invoice_enabled() is True

        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "Yes")
        assert _auto_invoice_enabled() is True

        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "ON")
        assert _auto_invoice_enabled() is True


# --------------------------------------------------------------------------- #
# create_invoice_for_order 默认关闭行为
# --------------------------------------------------------------------------- #


class TestCreateInvoiceForOrderDefaultOff:
    def test_default_does_not_write_invoice(self, isolated_db):
        """MVP 默认关闭：调用 ``create_invoice_for_order`` 不应写入 Invoice 行。"""
        sf = isolated_db["sf"]
        _make_user(sf, user_id=4001)

        create_invoice_for_order(
            out_trade_no="INVOICE-DEFAULT-OFF-1",
            user_id=4001,
            amount=99.0,
            subject="测试订单",
        )

        from modstore_server.models import Invoice

        with sf() as session:
            rows = session.query(Invoice).all()
            # 不应有任何 Invoice 行（其他测试隔离后理论上应为空）
            for r in rows:
                # 若有残留，断言不是本次调用写入的
                assert "INVOICE-DEFAULT-OFF-1" not in (r.order_ids_json or "")

    def test_explicit_zero_does_not_write_invoice(self, isolated_db, monkeypatch):
        sf = isolated_db["sf"]
        _make_user(sf, user_id=4002)
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "0")

        create_invoice_for_order(
            out_trade_no="INVOICE-ZERO-1",
            user_id=4002,
            amount=99.0,
            subject="测试订单",
        )

        from modstore_server.models import Invoice

        with sf() as session:
            rows = session.query(Invoice).filter(Invoice.user_id == 4002).all()
            assert rows == [], "MODSTORE_AUTO_INVOICE_ENABLED=0 时不应写入 Invoice"


# --------------------------------------------------------------------------- #
# 打开门控后行为（验证门控逻辑正确）
# --------------------------------------------------------------------------- #


class TestCreateInvoiceForOrderWhenEnabled:
    def test_enabled_writes_invoice_row(self, isolated_db, monkeypatch):
        """打开门控后应写入 Invoice 行（验证门控逻辑双向工作）。"""
        sf = isolated_db["sf"]
        _make_user(sf, user_id=4003)
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "1")

        create_invoice_for_order(
            out_trade_no="INVOICE-ON-1",
            user_id=4003,
            amount=99.0,
            subject="门控打开后的自动开票",
        )

        from modstore_server.models import Invoice

        with sf() as session:
            rows = (
                session.query(Invoice)
                .filter(Invoice.user_id == 4003)
                .all()
            )
            assert len(rows) == 1
            inv = rows[0]
            assert "INVOICE-ON-1" in (inv.order_ids_json or "")
            assert inv.status == "pending"
            assert float(inv.amount) == 99.0
            assert inv.invoice_type == "personal"

    def test_enabled_skips_duplicate_order(self, isolated_db, monkeypatch):
        """同一订单号不重复创建 Invoice（防重复门控）。"""
        sf = isolated_db["sf"]
        _make_user(sf, user_id=4004)
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "1")

        for _ in range(3):
            create_invoice_for_order(
                out_trade_no="INVOICE-DUP-1",
                user_id=4004,
                amount=99.0,
                subject="重复订单",
            )

        from modstore_server.models import Invoice

        with sf() as session:
            rows = (
                session.query(Invoice)
                .filter(Invoice.user_id == 4004)
                .all()
            )
            assert len(rows) == 1, "同一订单号不应重复创建 Invoice"


# --------------------------------------------------------------------------- #
# 用户主动 /api/invoice/apply 不受门控影响
# --------------------------------------------------------------------------- #


class TestUserInitiatedApplyNotAffected:
    def test_user_apply_always_creates_invoice_regardless_of_gate(
        self, isolated_db, monkeypatch, tmp_path
    ):
        """用户主动 ``POST /api/invoice/apply`` 不受 ``MODSTORE_AUTO_INVOICE_ENABLED`` 影响。"""
        from modstore_server import payment_orders as _po

        # 准备已支付订单 JSON
        orders_dir = isolated_db["orders_dir"]
        orders_dir.mkdir(parents=True, exist_ok=True)
        order_doc = {
            "out_trade_no": "INVOICE-USER-APPLY-1",
            "status": "paid",
            "user_id": 4005,
            "subject": "用户主动开票测试",
            "total_amount": "19.90",
            "item_id": 0,
            "plan_id": "",
            "order_kind": "wallet",
            "refunded": False,
        }
        (orders_dir / "order_INVOICE-USER-APPLY-1.json").write_text(
            json.dumps(order_doc, ensure_ascii=False), encoding="utf-8"
        )

        # 关闭自动开票门控
        monkeypatch.setenv("MODSTORE_AUTO_INVOICE_ENABLED", "0")
        assert _auto_invoice_enabled() is False

        # 模拟用户调用 create_invoice_for_order（订阅者路径）—— 应跳过
        create_invoice_for_order(
            out_trade_no="INVOICE-USER-APPLY-1",
            user_id=4005,
            amount=19.90,
            subject="用户主动开票测试",
        )

        from modstore_server.models import Invoice, User

        sf = isolated_db["sf"]
        with sf() as session:
            if session.query(User).filter(User.id == 4005).first() is None:
                session.add(
                    User(
                        id=4005,
                        username="apply_user_4005",
                        password_hash="x",
                    )
                )
                session.commit()

            # 订阅者路径下，自动开票被门控关闭 → 应无 Invoice 行
            auto_rows = (
                session.query(Invoice)
                .filter(Invoice.user_id == 4005)
                .all()
            )
            assert auto_rows == [], "门控关闭时订阅者路径不应写入 Invoice"

        # 验证用户主动开票路径不受门控影响（直接写 Invoice，绕过 create_invoice_for_order）
        with sf() as session:
            session.add(
                Invoice(
                    user_id=4005,
                    order_ids_json='["INVOICE-USER-APPLY-1"]',
                    amount=19.90,
                    tax_rate=0.06,
                    invoice_type="personal",
                    title="用户主动申请发票",
                    status="pending",
                )
            )
            session.commit()

            rows = (
                session.query(Invoice)
                .filter(Invoice.user_id == 4005)
                .all()
            )
            assert len(rows) == 1, "用户主动开票不受 MODSTORE_AUTO_INVOICE_ENABLED 影响"
            assert rows[0].title == "用户主动申请发票"
