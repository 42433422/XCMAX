# mypy: disable-error-code="no-any-return"
"""Tests for app.services.fulfillment_service — 履行/预留/backorder/return 模块（ODOO-W1-03）。

用真实 sqlite :memory:（StaticPool 复用同一引擎），patch inventory_service 与
fulfillment_service 的 get_db 指向同一持久会话，并在 tenant_scope(1) 内执行，
确保租户作用域与真实库存/流水落库均可验证。
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.fulfillment_service as fulfill_mod
import app.services.inventory_service as inv_mod
from app.db.base import Base
from app.db.models import (
    InventoryLedger,
    InventoryTransaction,
    Product,
    SalesOrder,
    SalesOrderItem,
    Warehouse,
)
from app.infrastructure.tenant_scope import tenant_scope
from app.services.fulfillment_service import FulfillmentService
from app.services.inventory_service import InventoryService


@pytest.fixture(scope="function")
def env():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )
    persistent = session_factory()

    @contextlib.contextmanager
    def test_db():
        yield persistent

    with (
        patch.object(inv_mod, "get_db", test_db),
        patch.object(fulfill_mod, "get_db", test_db),
    ):
        with tenant_scope(1):
            yield {"test_db": test_db, "session_factory": session_factory}
    persistent.close()


def _seed_order(env, ordered: int = 10, stock: int = 100) -> tuple:
    """种入产品 + 仓库 + 销售订单 + 单明细，并给产品注入库存。"""
    with env["test_db"]() as db:
        product = Product(model_number="P-FULF", name="履行品", unit="个")
        warehouse = Warehouse(code="WH-FULF", name="履行仓", status="active")
        db.add_all([product, warehouse])
        db.flush()
        order = SalesOrder(
            order_no="SO-FULF-001",
            customer_name="客户X",
            state="confirmed",
            status="confirmed",
            total_amount=Decimal("1000.00"),
            created_at=datetime.now(),
        )
        db.add(order)
        db.flush()
        item = SalesOrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=Decimal(str(ordered)),
            ordered_quantity=Decimal(str(ordered)),
            reserved_quantity=Decimal("0"),
            delivered_quantity=Decimal("0"),
            returned_quantity=Decimal("0"),
            amount=Decimal("0"),
            unit="个",
            status="pending",
            created_at=datetime.now(),
        )
        db.add(item)

    # 库存注入（独立提交，走被 patch 的 inventory get_db）
    inv = InventoryService()
    r = inv.inventory_in(product_id=product.id, warehouse_id=warehouse.id, quantity=float(stock))
    assert r["success"] is True, r.get("message")

    with env["test_db"]() as db:
        db.refresh(order)
        db.refresh(item)
        db.refresh(product)
        db.refresh(warehouse)
        return order, item, product, warehouse


def _ledger(env, product_id, warehouse_id) -> InventoryLedger:
    with env["test_db"]() as db:
        ledger = (
            db.query(InventoryLedger)
            .filter_by(product_id=product_id, warehouse_id=warehouse_id)
            .first()
        )
        return ledger


def _txns(env, item_id, transaction_type=None) -> list:
    with env["test_db"]() as db:
        q = db.query(InventoryTransaction).filter_by(sales_order_item_id=item_id)
        if transaction_type:
            q = q.filter_by(transaction_type=transaction_type)
        return q.order_by(InventoryTransaction.id).all()


# ---------------------------------------------------------------------------
# 预留（reserve）
# ---------------------------------------------------------------------------
class TestReserve:
    def test_reserve_increases_ledger_reserved_and_writes_move(self, env):
        order, item, product, warehouse = _seed_order(env)
        svc = FulfillmentService()

        result = svc.reserve(order.id, item.id, 4, warehouse_id=warehouse.id, operator="tester")
        assert result["success"] is True, result.get("message")
        assert result["data"]["reserved_quantity"] == 4.0

        ledger = _ledger(env, product.id, warehouse.id)
        assert float(ledger.reserved_quantity) == 4.0
        # 100 库存 - 4 预留 = 96 可用
        assert float(ledger.available_quantity) == 96.0
        assert float(ledger.quantity) == 100.0  # 物理库存不变

        txns = _txns(env, item.id, "reserve")
        assert len(txns) == 1
        assert txns[0].sales_order_id == order.id
        assert float(txns[0].ordered_quantity) == 4.0
        assert txns[0].reference_type == "sale_reserve"

    def test_reserve_exceeding_ordered_rejected(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()
        result = svc.reserve(order.id, item.id, 11, warehouse_id=warehouse.id)
        assert result["success"] is False
        assert "预留超量" in result["message"]
        # 库存未被改动
        ledger = _ledger(env, product.id, warehouse.id)
        assert float(ledger.reserved_quantity) == 0.0

    def test_reserve_insufficient_available_rejected(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10, stock=3)
        svc = FulfillmentService()
        result = svc.reserve(order.id, item.id, 5, warehouse_id=warehouse.id)
        assert result["success"] is False
        assert "库存不足" in result["message"]


# ---------------------------------------------------------------------------
# 交付（partial / backorder）
# ---------------------------------------------------------------------------
class TestDeliver:
    def test_full_delivery_consumes_reservation(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()
        svc.reserve(order.id, item.id, 10, warehouse_id=warehouse.id)

        result = svc.deliver(order.id, item.id, 10, warehouse_id=warehouse.id)
        assert result["success"] is True, result.get("message")
        assert result["data"]["partial"] is False
        assert result["data"]["backorder"] is False
        assert result["data"]["delivered_quantity"] == 10.0
        assert result["data"]["fulfillment"] == "delivered"

        ledger = _ledger(env, product.id, warehouse.id)
        assert float(ledger.quantity) == 90.0  # 100 - 10
        assert float(ledger.reserved_quantity) == 0.0  # 预留被消耗
        assert float(ledger.available_quantity) == 90.0

        txns = _txns(env, item.id, "out")
        assert len(txns) == 1
        assert float(txns[0].quantity) == -10.0
        assert float(txns[0].ordered_quantity) == 10.0
        assert float(txns[0].delivered_quantity) == 10.0
        assert txns[0].reference_type == "sale_delivery"

    def test_partial_delivery_triggers_backorder(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()

        result = svc.deliver(order.id, item.id, 6, warehouse_id=warehouse.id)
        assert result["success"] is True, result.get("message")
        assert result["data"]["partial"] is True
        assert result["data"]["backorder"] is True
        assert result["data"]["backorder_quantity"] == 4.0
        assert result["data"]["fulfillment"] == "partial"

        # 剩余部分继续交付，backorder 归零
        result2 = svc.deliver(order.id, item.id, 4, warehouse_id=warehouse.id)
        assert result2["success"] is True
        assert result2["data"]["backorder_quantity"] == 0.0
        assert result2["data"]["fulfillment"] == "delivered"

        ledger = _ledger(env, product.id, warehouse.id)
        assert float(ledger.quantity) == 90.0

    def test_over_delivery_rejected(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()
        result = svc.deliver(order.id, item.id, 11, warehouse_id=warehouse.id)
        assert result["success"] is False
        assert "超量" in result["message"]
        # 库存与交付未变
        ledger = _ledger(env, product.id, warehouse.id)
        assert float(ledger.quantity) == 100.0

    def test_deliver_insufficient_stock_rejected(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10, stock=3)
        svc = FulfillmentService()
        result = svc.deliver(order.id, item.id, 5, warehouse_id=warehouse.id)
        assert result["success"] is False
        assert "库存不足" in result["message"]


# ---------------------------------------------------------------------------
# 退货（return）
# ---------------------------------------------------------------------------
class TestReturn:
    def test_return_creates_reversing_move_and_restores_inventory(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()
        svc.deliver(order.id, item.id, 10, warehouse_id=warehouse.id)
        assert float(_ledger(env, product.id, warehouse.id).quantity) == 90.0

        result = svc.return_sale(order.id, item.id, 4, warehouse_id=warehouse.id)
        assert result["success"] is True, result.get("message")
        assert result["data"]["returned_quantity"] == 4.0

        ledger = _ledger(env, product.id, warehouse.id)
        assert float(ledger.quantity) == 94.0  # 90 + 4 回补
        assert float(ledger.available_quantity) == 94.0

        txns = _txns(env, item.id, "return")
        assert len(txns) == 1
        assert float(txns[0].quantity) == 4.0
        assert txns[0].reference_type == "sale_return"
        assert txns[0].sales_order_id == order.id

    def test_return_exceeding_delivered_rejected(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()
        svc.deliver(order.id, item.id, 5, warehouse_id=warehouse.id)
        result = svc.return_sale(order.id, item.id, 6, warehouse_id=warehouse.id)
        assert result["success"] is False
        assert "退货超过" in result["message"]
        # 库存未被改动
        assert float(_ledger(env, product.id, warehouse.id).quantity) == 95.0


# ---------------------------------------------------------------------------
# 幂等（idempotency）
# ---------------------------------------------------------------------------
class TestIdempotency:
    def test_duplicate_deliver_with_same_key_is_noop(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()

        first = svc.deliver(
            order.id, item.id, 6, warehouse_id=warehouse.id, idempotency_key="del-001"
        )
        assert first["success"] is True
        assert float(first["data"]["delivered_quantity"]) == 6.0

        second = svc.deliver(
            order.id, item.id, 6, warehouse_id=warehouse.id, idempotency_key="del-001"
        )
        assert second["success"] is True
        assert second.get("idempotent") is True
        # 不重复扣减/累加
        assert float(second["data"]["delivered_quantity"]) == 6.0
        assert float(_ledger(env, product.id, warehouse.id).quantity) == 94.0
        assert len(_txns(env, item.id, "out")) == 1

    def test_duplicate_return_with_same_key_is_noop(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()
        svc.deliver(order.id, item.id, 10, warehouse_id=warehouse.id)

        first = svc.return_sale(
            order.id, item.id, 4, warehouse_id=warehouse.id, idempotency_key="ret-001"
        )
        assert first["success"] is True
        second = svc.return_sale(
            order.id, item.id, 4, warehouse_id=warehouse.id, idempotency_key="ret-001"
        )
        assert second["success"] is True
        assert second.get("idempotent") is True
        assert float(second["data"]["returned_quantity"]) == 4.0
        assert len(_txns(env, item.id, "return")) == 1


# ---------------------------------------------------------------------------
# 履行派生口径 + 视图
# ---------------------------------------------------------------------------
class TestFulfillmentDerivation:
    def test_fulfillment_state_derived_only_from_quantities(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()

        assert svc.fulfillment_state(order.id)["state"] == "unfulfilled"

        svc.deliver(order.id, item.id, 6, warehouse_id=warehouse.id)
        assert svc.fulfillment_state(order.id)["state"] == "partial"

        svc.deliver(order.id, item.id, 4, warehouse_id=warehouse.id)
        assert svc.fulfillment_state(order.id)["state"] == "delivered"

        # return 后履行不再是 delivered
        svc.return_sale(order.id, item.id, 10, warehouse_id=warehouse.id)
        assert svc.fulfillment_state(order.id)["state"] == "return"

    def test_get_fulfillment_view(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()
        svc.deliver(order.id, item.id, 6, warehouse_id=warehouse.id)

        view = svc.get_fulfillment(order.id)
        assert view["success"] is True
        assert view["data"]["fulfillment"] == "partial"
        assert view["data"]["items"][0]["ordered_quantity"] == 10.0
        assert view["data"]["items"][0]["delivered_quantity"] == 6.0
        assert view["data"]["items"][0]["backorder_quantity"] == 4.0


# ---------------------------------------------------------------------------
# 错误路径
# ---------------------------------------------------------------------------
class TestErrorPaths:
    def test_order_not_found(self, env):
        assert FulfillmentService().deliver(9999, 1, 1, warehouse_id=1)["success"] is False

    def test_item_not_found(self, env):
        order, item, product, warehouse = _seed_order(env)
        result = FulfillmentService().deliver(order.id, 9999, 1, warehouse_id=warehouse.id)
        assert result["success"] is False
        assert "明细不存在" in result["message"]

    def test_zero_quantity_rejected(self, env):
        order, item, product, warehouse = _seed_order(env)
        svc = FulfillmentService()
        assert svc.deliver(order.id, item.id, 0, warehouse_id=warehouse.id)["success"] is False
        assert svc.reserve(order.id, item.id, 0, warehouse_id=warehouse.id)["success"] is False
        assert svc.return_sale(order.id, item.id, 0, warehouse_id=warehouse.id)["success"] is False


# ---------------------------------------------------------------------------
# backorder 子单实体（ODOO-W1-03 review fix）
# 部分交付必须实体化一张真实 SalesOrder 子单（backorder_of_id 指向父单），
# 且子单含未交付量；后续部分交付更新未交付量而不重复建单；终次交付解析。
# ---------------------------------------------------------------------------
def _backorder_children(env, order_id) -> list:
    with env["test_db"]() as db:
        return (
            db.query(SalesOrder)
            .filter(SalesOrder.backorder_of_id == order_id)
            .order_by(SalesOrder.id.asc())
            .all()
        )


class TestBackorderChild:
    def test_partial_delivery_materializes_backorder_child(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()

        result = svc.deliver(order.id, item.id, 6, warehouse_id=warehouse.id)
        assert result["success"] is True, result.get("message")
        assert result["data"]["backorder"] is True
        assert result["data"]["backorder_quantity"] == 4.0
        # 返回实体子单信息
        assert result["data"]["backorder_order_id"] is not None
        assert result["data"]["backorder_order_no"].endswith("-BO")

        children = _backorder_children(env, order.id)
        assert len(children) == 1
        child = children[0]
        assert child.backorder_of_id == order.id
        assert child.order_no == f"{order.order_no}-BO"
        assert child.tenant_id == 1
        # 子单含未交付量
        assert len(child.items) == 1
        assert child.items[0].quantity == Decimal("4")
        assert child.items[0].ordered_quantity == Decimal("4")
        # 子单明细 remark 记录来源（父单明细）id
        assert child.items[0].remark == f"backorder source_item_id={item.id}"

        # get_backorder 视图反映关联与剩余量
        view = svc.get_backorder(order.id)
        assert view["success"] is True
        assert view["backorder"]["order_id"] == child.id
        assert view["backorder"]["backorder_of_id"] == order.id
        assert view["backorder"]["remaining_quantity"] == 4.0

    def test_later_partial_delivery_updates_child_without_duplicating(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()
        svc.deliver(order.id, item.id, 6, warehouse_id=warehouse.id)
        svc.deliver(order.id, item.id, 2, warehouse_id=warehouse.id)

        children = _backorder_children(env, order.id)
        assert len(children) == 1  # 不重复建单
        child = children[0]
        assert len(child.items) == 1
        # 剩余未交付量已更新为 10 - 8 = 2
        assert child.items[0].ordered_quantity == Decimal("2")
        assert svc.get_backorder(order.id)["backorder"]["remaining_quantity"] == 2.0

    def test_backorder_same_tenant_idempotent_retry_no_duplicate_child(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()

        first = svc.deliver(
            order.id, item.id, 6, warehouse_id=warehouse.id, idempotency_key="bo-retry"
        )
        assert first["success"] is True
        second = svc.deliver(
            order.id, item.id, 6, warehouse_id=warehouse.id, idempotency_key="bo-retry"
        )
        assert second["success"] is True
        assert second.get("idempotent") is True

        children = _backorder_children(env, order.id)
        assert len(children) == 1  # 幂等重试不重复建子单
        assert children[0].items[0].ordered_quantity == Decimal("4")

    def test_final_delivery_resolves_backorder_child(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()
        svc.deliver(order.id, item.id, 6, warehouse_id=warehouse.id)
        assert _backorder_children(env, order.id)[0].items[0].ordered_quantity == Decimal("4")

        final = svc.deliver(order.id, item.id, 4, warehouse_id=warehouse.id)
        assert final["success"] is True
        assert final["data"]["backorder"] is False
        assert final["data"]["backorder_quantity"] == 0.0

        children = _backorder_children(env, order.id)
        assert len(children) == 1
        # 终次交付：子单未交付量解析归零
        assert children[0].items[0].ordered_quantity == Decimal("0")
        assert svc.get_backorder(order.id)["backorder"]["remaining_quantity"] == 0.0


# ---------------------------------------------------------------------------
# 活跃租户隔离（ODOO-W1-03 review fix）
# 用仓储层 tenant_scope 机制验证：backorder 子单落在活跃租户，跨租户不可见。
# ---------------------------------------------------------------------------
class TestTenantIsolation:
    def test_active_tenant_isolation(self, env):
        order, item, product, warehouse = _seed_order(env)
        svc = FulfillmentService()
        svc.deliver(order.id, item.id, 6, warehouse_id=warehouse.id)

        with env["test_db"]() as db:
            child = db.query(SalesOrder).filter(SalesOrder.backorder_of_id == order.id).first()
            assert child is not None
            assert child.tenant_id == 1
            assert order.tenant_id == 1

        # 切换活跃租户 2：父单与子单均不可见（严格隔离）
        with tenant_scope(2):
            with env["test_db"]() as db:
                assert db.query(SalesOrder).filter(SalesOrder.id == order.id).first() is None
                assert db.query(SalesOrder).filter(SalesOrder.id == child.id).first() is None
            # 履行服务在租户 2 下查不到父单 → fail-closed
            res = svc.deliver(order.id, item.id, 1, warehouse_id=warehouse.id)
            assert res["success"] is False
            assert "不存在" in res["message"]


# ---------------------------------------------------------------------------
# Decimal 安全（ODOO-W1-03 review fix）
# 数量突变路径使用 Decimal 运算与赋值，float 仅在响应边界转换；
# 0.1 + 0.2 精确为 0.3，而非 float 的 0.30000000000000004。
# ---------------------------------------------------------------------------
class TestDecimalSafety:
    def test_reserve_returns_exact_decimal_response(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10, stock=100)
        inv = InventoryService()
        r1 = inv.reserve_for_order(
            product.id,
            warehouse.id,
            0.1,
            sales_order_id=order.id,
            sales_order_item_id=item.id,
        )
        r2 = inv.reserve_for_order(
            product.id,
            warehouse.id,
            0.2,
            sales_order_id=order.id,
            sales_order_item_id=item.id,
        )
        assert r1["success"] is True, r1.get("message")
        assert r2["success"] is True, r2.get("message")
        # Decimal 精确累计 0.3，非 float 近似
        assert r2["reserved_quantity"] == 0.3
        with env["test_db"]() as db:
            ledger = (
                db.query(InventoryLedger)
                .filter_by(product_id=product.id, warehouse_id=warehouse.id)
                .first()
            )
            assert ledger.reserved_quantity == Decimal("0.3")

    def test_deliver_accumulates_exact_decimal(self, env):
        order, item, product, warehouse = _seed_order(env, ordered=10)
        svc = FulfillmentService()
        svc.deliver(order.id, item.id, 0.1, warehouse_id=warehouse.id)
        r = svc.deliver(order.id, item.id, 0.2, warehouse_id=warehouse.id)
        assert r["success"] is True, r.get("message")
        assert r["data"]["delivered_quantity"] == 0.3
        with env["test_db"]() as db:
            db.refresh(item)
            assert item.delivered_quantity == Decimal("0.3")
