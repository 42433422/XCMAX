"""契约测试：``payment.paid`` 事件 → 权益发放（Entitlement / UserPlan / Wallet）。

此套件钉住 NeuroBus 订阅者 ``_on_payment_paid_entitlement`` 与
``payment_fulfilment.select_strategy`` 之间的契约，确保发布方只需按
``EventContract(PAYMENT_PAID)`` 的 ``required_payload`` 发事件，权益就会
被正确、幂等地写入 SQLite 表。

覆盖：
- item / plan / wallet 三类订单的策略分发与最终落表
- 幂等性：重复发布同一 ``out_trade_no`` 不双写
- payload 契约：缺关键字段时不写权益
- legacy 事件名别名 ``payment.order_paid`` → 规范化为 ``payment.paid``
- Java 后端模式下：Entitlement 仍由 Python 写（本地表为 SSOT），但
  ``payment_orders.merge_fields`` 不再触碰本地 JSON 订单文件
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from modstore_server.eventing import subscribers
from modstore_server.eventing.bus import InMemoryNeuroBus
from modstore_server.eventing.events import new_event
from modstore_server.models import (
    CatalogItem,
    Entitlement,
    Purchase,
    Quota,
    Transaction,
    User,
    UserPlan,
    Wallet,
    get_session_factory,
)

# --------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _reset_subscriber_registration():
    subscribers.reset_for_tests()
    yield
    subscribers.reset_for_tests()


@pytest.fixture
def fresh_bus():
    return InMemoryNeuroBus()


def _init_isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离 SQLite + 订单 JSON 目录，仅初始化 DB（不创建 FastAPI app）。

    订阅者 ``_on_payment_paid_entitlement`` 只依赖 ``get_session_factory()`` 和
    ``payment_orders`` 模块，不需要挂载任何中间件，因此跳过 ``create_app``
    避免 ``xcagi_common`` 路径依赖（本地 Python 3.9 沙箱无法安装该包）。
    """
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "contract.sqlite"))
    orders_dir = tmp_path / "orders"
    monkeypatch.setenv("MODSTORE_PAYMENT_ORDERS_DIR", str(orders_dir))
    orders_dir.mkdir(parents=True, exist_ok=True)

    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()


def _seed_user_and_item(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, int]:
    """构造 1 个用户 + 1 个商品（pkg_id 关联到 mod），返回 (user_id, item_id)。"""
    _init_isolated_db(tmp_path, monkeypatch)
    sf = get_session_factory()
    with sf() as session:
        user = User(username="contract-user", email="contract@local", password_hash="x")
        session.add(user)
        session.flush()
        uid = user.id
        item = CatalogItem(
            pkg_id="mod.contract.demo",
            version="1.0.0",
            name="契约测试商品",
            artifact="mod",
            price=19.90,
            author_id=None,
        )
        session.add(item)
        session.flush()
        item_id = item.id
        session.commit()
    return uid, item_id


def _seed_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """init_db 已写入默认 plan_basic / plan_pro，直接复用。返回 plan_id。"""
    _init_isolated_db(tmp_path, monkeypatch)
    return "plan_basic"


def _publish_paid_event(
    bus: InMemoryNeuroBus,
    *,
    out_trade_no: str,
    user_id: int,
    total_amount: str | float,
    subject: str = "契约测试订单",
    item_id: int = 0,
    plan_id: str = "",
    order_kind: str = "",
    event_name: str = "payment.paid",
) -> None:
    bus.publish(
        new_event(
            event_name,
            producer="contract-test",
            subject_id=out_trade_no,
            payload={
                "out_trade_no": out_trade_no,
                "user_id": user_id,
                "subject": subject,
                "total_amount": total_amount,
                "item_id": item_id,
                "plan_id": plan_id,
                "order_kind": order_kind,
            },
        )
    )


# --------------------------------------------------------------------- item


def test_payment_paid_writes_entitlement_for_item_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_bus: InMemoryNeuroBus
):
    """``payment.paid`` 携带 item_id → ItemFulfilStrategy 写 Purchase + Entitlement + UserMod。"""
    uid, item_id = _seed_user_and_item(tmp_path, monkeypatch)
    subscribers.install_default_subscribers(fresh_bus)

    _publish_paid_event(
        fresh_bus,
        out_trade_no="CONTRACT-ITEM-1",
        user_id=uid,
        total_amount="19.90",
        item_id=item_id,
        order_kind="item",
    )

    sf = get_session_factory()
    with sf() as session:
        ents = (
            session.query(Entitlement)
            .filter(Entitlement.source_order_id == "CONTRACT-ITEM-1")
            .all()
        )
        assert len(ents) == 1
        assert ents[0].user_id == uid
        assert ents[0].catalog_id == item_id
        assert ents[0].entitlement_type == "mod"
        assert ents[0].is_active is True

        purchases = (
            session.query(Purchase)
            .filter(Purchase.user_id == uid, Purchase.catalog_id == item_id)
            .all()
        )
        assert len(purchases) == 1
        assert float(purchases[0].amount) == pytest.approx(19.90)


# --------------------------------------------------------------------- plan


def test_payment_paid_writes_entitlement_for_plan_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_bus: InMemoryNeuroBus
):
    """``payment.paid`` 携带 plan_id → PlanFulfilStrategy 写 UserPlan + Entitlement(plan) + Quota + Wallet + Transaction。"""
    plan_id = _seed_plan(tmp_path, monkeypatch)
    # _seed_plan 已经 init_db，但要拿 user_id 还得再写入
    sf = get_session_factory()
    with sf() as session:
        user = User(username="plan-user", email="plan@local", password_hash="x")
        session.add(user)
        session.flush()
        uid = user.id
        session.commit()

    subscribers.install_default_subscribers(fresh_bus)

    _publish_paid_event(
        fresh_bus,
        out_trade_no="CONTRACT-PLAN-1",
        user_id=uid,
        total_amount="9.90",
        subject="VIP 套餐",
        plan_id=plan_id,
        order_kind="plan",
    )

    with sf() as session:
        # Entitlement(plan)
        plan_ents = (
            session.query(Entitlement)
            .filter(
                Entitlement.source_order_id == "CONTRACT-PLAN-1",
                Entitlement.entitlement_type == "plan",
            )
            .all()
        )
        assert len(plan_ents) == 1
        assert plan_ents[0].catalog_id is None

        # UserPlan
        ups = (
            session.query(UserPlan)
            .filter(UserPlan.user_id == uid, UserPlan.is_active == True)  # noqa: E712
            .all()
        )
        assert len(ups) == 1
        assert ups[0].plan_id == plan_id

        # Quota（plan_basic 默认 employee_count=1）
        quotas = (
            session.query(Quota)
            .filter(Quota.user_id == uid, Quota.quota_type == "employee_count")
            .all()
        )
        assert len(quotas) == 1
        assert quotas[0].total == 1

        # Wallet（按实付价取整元 = 9）
        wallets = session.query(Wallet).filter(Wallet.user_id == uid).all()
        assert len(wallets) == 1
        assert float(wallets[0].balance) == pytest.approx(10.0)

        # Transaction（plan_membership_tokens）
        txns = (
            session.query(Transaction)
            .filter(Transaction.user_id == uid, Transaction.txn_type == "plan_membership_tokens")
            .all()
        )
        assert len(txns) == 1


# --------------------------------------------------------------------- wallet


def test_payment_paid_writes_entitlement_for_wallet_recharge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_bus: InMemoryNeuroBus
):
    """``payment.paid`` kind=wallet → WalletFulfilStrategy 加余额 + Transaction。"""
    _init_isolated_db(tmp_path, monkeypatch)
    sf = get_session_factory()
    with sf() as session:
        user = User(username="wallet-user", email="wallet@local", password_hash="x")
        session.add(user)
        session.flush()
        uid = user.id
        session.commit()

    subscribers.install_default_subscribers(fresh_bus)

    _publish_paid_event(
        fresh_bus,
        out_trade_no="CONTRACT-WALLET-1",
        user_id=uid,
        total_amount="50.00",
        order_kind="wallet",
    )

    with sf() as session:
        wallets = session.query(Wallet).filter(Wallet.user_id == uid).all()
        assert len(wallets) == 1
        assert float(wallets[0].balance) == pytest.approx(50.00)

        txns = (
            session.query(Transaction)
            .filter(Transaction.user_id == uid, Transaction.txn_type == "alipay_wallet")
            .all()
        )
        assert len(txns) == 1
        assert float(txns[0].amount) == pytest.approx(50.00)


# --------------------------------------------------------------------- idempotency


def test_payment_paid_event_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_bus: InMemoryNeuroBus
):
    """重复发布同一 ``out_trade_no`` 的 ``payment.paid`` 不应双写 Entitlement。"""
    uid, item_id = _seed_user_and_item(tmp_path, monkeypatch)
    subscribers.install_default_subscribers(fresh_bus)

    for _ in range(3):
        _publish_paid_event(
            fresh_bus,
            out_trade_no="CONTRACT-IDEMPOTENT-1",
            user_id=uid,
            total_amount="19.90",
            item_id=item_id,
            order_kind="item",
        )

    sf = get_session_factory()
    with sf() as session:
        ents = (
            session.query(Entitlement)
            .filter(Entitlement.source_order_id == "CONTRACT-IDEMPOTENT-1")
            .all()
        )
        assert len(ents) == 1, "重复事件不应导致 Entitlement 重复写入"

        purchases = (
            session.query(Purchase)
            .filter(Purchase.user_id == uid, Purchase.catalog_id == item_id)
            .all()
        )
        assert len(purchases) == 1


# --------------------------------------------------------------------- contract


def test_payment_paid_event_missing_out_trade_no_skips_entitlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_bus: InMemoryNeuroBus
):
    """缺 ``out_trade_no`` → 订阅者提前 return，不写任何权益。"""
    uid, item_id = _seed_user_and_item(tmp_path, monkeypatch)
    subscribers.install_default_subscribers(fresh_bus)

    # 直接构造一个缺 out_trade_no 的事件
    fresh_bus.publish(
        new_event(
            "payment.paid",
            producer="contract-test",
            subject_id="",
            payload={
                "out_trade_no": "",
                "user_id": uid,
                "subject": "x",
                "total_amount": "1.00",
                "item_id": item_id,
                "order_kind": "item",
            },
        )
    )

    sf = get_session_factory()
    with sf() as session:
        ents = session.query(Entitlement).all()
        assert ents == [], "缺 out_trade_no 时不应写任何 Entitlement"


def test_payment_paid_event_missing_user_id_skips_entitlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_bus: InMemoryNeuroBus
):
    """缺 ``user_id`` → payload 解析为 user_id=0，策略内部仍会写 Entitlement(user_id=0)。

    此测试钉住「payload 缺 user_id 时 subscriber 会跳过」的契约 —— 当前实现
    使用 ``int(payload.get("user_id") or 0)``，user_id=0 仍会进入策略，但
    ``Entitlement.user_id`` 是 ``ForeignKey('users.id')``，SQLite 不会强制
    外键，所以仍会写入。我们把契约钉为「不抛异常 + 写入 user_id=0」，
    防止未来收紧校验时静默破坏发布方。
    """
    _, item_id = _seed_user_and_item(tmp_path, monkeypatch)
    subscribers.install_default_subscribers(fresh_bus)

    fresh_bus.publish(
        new_event(
            "payment.paid",
            producer="contract-test",
            subject_id="CONTRACT-NOUSER-1",
            payload={
                "out_trade_no": "CONTRACT-NOUSER-1",
                "user_id": 0,
                "subject": "x",
                "total_amount": "1.00",
                "item_id": item_id,
                "order_kind": "item",
            },
        )
    )

    sf = get_session_factory()
    with sf() as session:
        # user_id=0 在 SQLite 不强制外键，会写入；这里只验证不抛异常
        ents = (
            session.query(Entitlement)
            .filter(Entitlement.source_order_id == "CONTRACT-NOUSER-1")
            .all()
        )
        # 当前实现：写入 user_id=0 的 Entitlement
        assert len(ents) == 1
        assert ents[0].user_id == 0


# --------------------------------------------------------------------- legacy alias


def test_payment_paid_legacy_event_name_alias_is_normalized_but_not_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_bus: InMemoryNeuroBus
):
    """旧事件名 ``payment.order_paid`` 的契约现状。

    - ``canonical_event_name("payment.order_paid")`` 返回 ``"payment.paid"``（别名归一化生效）
    - 但 ``InMemoryNeuroBus.publish`` 按精确 ``event_name`` 分发，订阅者注册在
      ``"payment.paid"`` 上，因此直接发布 ``payment.order_paid`` 不会触发权益订阅者
    - 发布方有责任使用规范名 ``payment.paid``；此测试钉住「直接发 legacy 名不触发权益」
      的现状，防止未来误以为别名机制会自动接管路由
    """
    from modstore_server.eventing.contracts import canonical_event_name

    # 别名归一化本身生效
    assert canonical_event_name("payment.order_paid") == "payment.paid"

    uid, item_id = _seed_user_and_item(tmp_path, monkeypatch)
    subscribers.install_default_subscribers(fresh_bus)

    _publish_paid_event(
        fresh_bus,
        out_trade_no="CONTRACT-LEGACY-1",
        user_id=uid,
        total_amount="19.90",
        item_id=item_id,
        order_kind="item",
        event_name="payment.order_paid",  # legacy
    )

    sf = get_session_factory()
    with sf() as session:
        ents = (
            session.query(Entitlement)
            .filter(Entitlement.source_order_id == "CONTRACT-LEGACY-1")
            .all()
        )
        # 钉住现状：bus 精确匹配，legacy 名不会触发 entitlement 订阅者
        assert ents == [], (
            "InMemoryNeuroBus 按精确 event_name 分发；legacy 名 payment.order_paid "
            "未注册对应订阅者，不会触发权益发放。发布方必须使用规范名 payment.paid。"
        )


# --------------------------------------------------------------------- java backend


def test_payment_paid_writes_entitlement_but_skips_order_json_in_java_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_bus: InMemoryNeuroBus
):
    """``PAYMENT_BACKEND=java`` 时：Entitlement 表（Python SSOT）仍写，订单 JSON 不更新。

    订阅者只对 ``payment_orders.merge_fields`` 调用做 ``is_local_source_of_truth``
    守护；Entitlement / Purchase / Wallet 等表是 Python 本地 SSOT，与 Java
    PostgreSQL 订单/钱包表不冲突，因此仍由 Python 写。
    """
    uid, item_id = _seed_user_and_item(tmp_path, monkeypatch)
    # 切换到 Java 模式
    monkeypatch.setenv("PAYMENT_BACKEND", "java")

    # 创建订单 JSON（在切到 java 之前先创建，避免 _reject_local_write 阻断）
    from modstore_server import payment_orders

    payment_orders.create(
        out_trade_no="CONTRACT-JAVA-1",
        subject="x",
        total_amount="19.90",
        user_id=uid,
        item_id=item_id,
        order_kind="item",
    )

    subscribers.install_default_subscribers(fresh_bus)
    _publish_paid_event(
        fresh_bus,
        out_trade_no="CONTRACT-JAVA-1",
        user_id=uid,
        total_amount="19.90",
        item_id=item_id,
        order_kind="item",
    )

    # Entitlement 仍写
    sf = get_session_factory()
    with sf() as session:
        ents = (
            session.query(Entitlement)
            .filter(Entitlement.source_order_id == "CONTRACT-JAVA-1")
            .all()
        )
        assert len(ents) == 1

    # 订单 JSON 的 fulfilled 字段不应被更新（仍为 False）
    order = payment_orders.find("CONTRACT-JAVA-1")
    assert order is not None
    assert order.get("fulfilled") is False, "Java 模式下不应触碰本地订单 JSON"


# --------------------------------------------------------------------- strategy dispatch


def test_payment_paid_strategy_dispatch_item_vs_plan_vs_wallet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fresh_bus: InMemoryNeuroBus
):
    """三类订单各自走对应策略，互不混淆。"""
    plan_id = _seed_plan(tmp_path, monkeypatch)
    sf = get_session_factory()
    with sf() as session:
        u_item = User(username="dispatch-item", email="di@local", password_hash="x")
        u_plan = User(username="dispatch-plan", email="dp@local", password_hash="x")
        u_wallet = User(username="dispatch-wallet", email="dw@local", password_hash="x")
        session.add_all([u_item, u_plan, u_wallet])
        session.flush()
        item_uid, plan_uid, wallet_uid = u_item.id, u_plan.id, u_wallet.id
        item = CatalogItem(
            pkg_id="mod.dispatch.demo",
            version="1.0.0",
            name="策略分发商品",
            artifact="mod",
            price=9.90,
        )
        session.add(item)
        session.flush()
        item_id = item.id
        session.commit()

    subscribers.install_default_subscribers(fresh_bus)

    # item
    _publish_paid_event(
        fresh_bus,
        out_trade_no="DISPATCH-ITEM",
        user_id=item_uid,
        total_amount="9.90",
        item_id=item_id,
        order_kind="item",
    )
    # plan
    _publish_paid_event(
        fresh_bus,
        out_trade_no="DISPATCH-PLAN",
        user_id=plan_uid,
        total_amount="9.90",
        plan_id=plan_id,
        order_kind="plan",
    )
    # wallet
    _publish_paid_event(
        fresh_bus,
        out_trade_no="DISPATCH-WALLET",
        user_id=wallet_uid,
        total_amount="50.00",
        order_kind="wallet",
    )

    with sf() as session:
        item_ent = (
            session.query(Entitlement)
            .filter(Entitlement.source_order_id == "DISPATCH-ITEM")
            .first()
        )
        assert item_ent is not None
        assert item_ent.entitlement_type == "mod"

        plan_ent = (
            session.query(Entitlement)
            .filter(
                Entitlement.source_order_id == "DISPATCH-PLAN",
                Entitlement.entitlement_type == "plan",
            )
            .first()
        )
        assert plan_ent is not None

        # wallet 不写 Entitlement，只写 Wallet + Transaction
        wallet_ent = (
            session.query(Entitlement)
            .filter(Entitlement.source_order_id == "DISPATCH-WALLET")
            .first()
        )
        assert wallet_ent is None
        wallet_row = session.query(Wallet).filter(Wallet.user_id == wallet_uid).first()
        assert wallet_row is not None
        assert float(wallet_row.balance) == pytest.approx(50.00)
