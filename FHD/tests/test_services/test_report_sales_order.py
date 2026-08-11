"""W1-07 报表读模型：SalesOrder 正交读模型聚合测试。

验证（业务后置条件）：
1. 新 SalesOrder 数据对销售报表可见（主源）。
2. 遗留 ShipmentRecord 数据不能冒充销售主源（默认 source=sales_order 不读它）。
3. 销售汇总金额与 SalesOrder.total_amount 一致（产品 / 客户 / 日期三维度）。
4. 多租户隔离（tenant 之间互不可见）。
5. 遗留 ShipmentRecord 兼容路径仍可用（source="shipment"）。
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

import app.services.report_service as report_service
from app.db.base import Base
from app.db.models import Customer, Product, SalesOrder, SalesOrderItem, ShipmentRecord
from app.infrastructure.tenant_scope import tenant_scope
from app.services.report_service import ReportService


@pytest.fixture(scope="function")
def report_env():
    """共享内存库 + 将 report_service.get_db 指向同一持久会话。"""
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

    # 预置客户与产品，满足 sales_orders.customer_id / sales_order_items.product_id 外键
    persistent.add_all(
        [
            Customer(customer_name="客户A"),
            Customer(customer_name="客户B"),
            Product(model_number="P-1", name="产品A", unit="个"),
            Product(model_number="P-2", name="产品B", unit="个"),
        ]
    )
    persistent.flush()

    with patch.object(report_service, "get_db", test_db):
        yield {"test_db": test_db, "session_factory": session_factory}
    persistent.close()


def _add_order(
    db,
    *,
    order_no: str,
    customer_name: str,
    customer_id: int,
    total_amount: str,
    created_at: datetime,
    items: list[dict],
) -> int:
    """构造一笔 SalesOrder + 明细。明细 amount 之和等于订单 total_amount。"""
    order = SalesOrder(
        order_no=order_no,
        customer_id=customer_id,
        customer_name=customer_name,
        total_amount=Decimal(total_amount),
        state="confirmed",
        status="confirmed",
        invoice_status="invoiced",
        payment_state="paid",
        created_at=created_at,
    )
    db.add(order)
    db.flush()
    for it in items:
        item = SalesOrderItem(
            order_id=order.id,
            product_id=it["product_id"],
            product_name=it["product_name"],
            quantity=Decimal(str(it["quantity"])),
            unit_price=Decimal(str(it["price"])),
            amount=Decimal(str(it["amount"])),
            ordered_quantity=Decimal(str(it["quantity"])),
            delivered_quantity=Decimal(str(it["quantity"])),
        )
        db.add(item)
    db.flush()
    return order.id


def _add_shipment(db, *, product_name: str, amount: str) -> int:
    record = ShipmentRecord(
        purchase_unit="客户A",
        unit_id=1,
        product_name=product_name,
        quantity_kg=50.0,
        quantity_tins=1,
        amount=Decimal(amount),
    )
    db.add(record)
    db.flush()
    return record.id


# ---------------------------------------------------------------------------
# 1. 新 SalesOrder 数据可见（主源）
# ---------------------------------------------------------------------------
class TestSalesOrderDataVisible:
    def test_product_group_aggregates_sales_order_items(self, report_env):
        with report_env["test_db"]() as db:
            _add_order(
                db,
                order_no="SO-1",
                customer_name="客户A",
                customer_id=1,
                total_amount="600.00",
                created_at=datetime(2026, 1, 10, 9, 30),
                items=[
                    {
                        "product_id": 1,
                        "product_name": "产品A",
                        "quantity": 2,
                        "price": 300,
                        "amount": 600,
                    },
                ],
            )
            _add_order(
                db,
                order_no="SO-2",
                customer_name="客户A",
                customer_id=1,
                total_amount="400.00",
                created_at=datetime(2026, 1, 15, 10, 0),
                items=[
                    {
                        "product_id": 2,
                        "product_name": "产品B",
                        "quantity": 1,
                        "price": 400,
                        "amount": 400,
                    },
                ],
            )

        svc = ReportService()
        result = svc.get_sales_report()  # 默认 source=sales_order
        assert result["success"] is True
        products = {d["product_name"]: d for d in result["data"]}
        assert products["产品A"]["amount"] == 600.0
        assert products["产品A"]["quantity"] == 2.0
        assert products["产品B"]["amount"] == 400.0
        assert result["summary"]["total_amount"] == 1000.0


# ---------------------------------------------------------------------------
# 2. 遗留 ShipmentRecord 不能冒充销售主源
# ---------------------------------------------------------------------------
class TestLegacyCannotMasquerade:
    def test_legacy_only_data_is_not_primary_sales(self, report_env):
        with report_env["test_db"]() as db:
            _add_shipment(db, product_name="产品A", amount="5000.00")

        svc = ReportService()
        result = svc.get_sales_report()  # 默认 sales_order，不读 ShipmentRecord
        assert result["success"] is True
        assert result["data"] == []
        assert result["summary"]["total_amount"] == 0.0

    def test_sales_order_is_authoritative_over_legacy(self, report_env):
        with report_env["test_db"]() as db:
            _add_order(
                db,
                order_no="SO-1",
                customer_name="客户A",
                customer_id=1,
                total_amount="100.00",
                created_at=datetime(2026, 1, 10, 9, 30),
                items=[
                    {
                        "product_id": 1,
                        "product_name": "产品A",
                        "quantity": 1,
                        "price": 100,
                        "amount": 100,
                    },
                ],
            )
            _add_shipment(db, product_name="产品A", amount="9999.00")

        svc = ReportService()
        result = svc.get_sales_report()
        # 遗留 ShipmentRecord 的 9999 不得计入主源销售汇总
        assert result["summary"]["total_amount"] == 100.0

    def test_legacy_shipment_source_still_available_as_compat(self, report_env):
        with report_env["test_db"]() as db:
            _add_shipment(db, product_name="产品A", amount="5000.00")

        svc = ReportService()
        result = svc.get_sales_report(source="shipment")
        assert result["success"] is True
        assert result["data"][0]["product_name"] == "产品A"
        assert result["summary"]["total_amount"] == 5000.0


# ---------------------------------------------------------------------------
# 3. 汇总金额与 SalesOrder.total_amount 一致（多维聚合）
# ---------------------------------------------------------------------------
class TestTotalsConsistency:
    def test_summary_total_amount_matches_sales_order_totals(self, report_env):
        with report_env["test_db"]() as db:
            _add_order(
                db,
                order_no="SO-1",
                customer_name="客户A",
                customer_id=1,
                total_amount="900.00",
                created_at=datetime(2026, 1, 10, 9, 30),
                items=[
                    {
                        "product_id": 1,
                        "product_name": "产品A",
                        "quantity": 2,
                        "price": 300,
                        "amount": 600,
                    },
                    {
                        "product_id": 2,
                        "product_name": "产品B",
                        "quantity": 1,
                        "price": 300,
                        "amount": 300,
                    },
                ],
            )
            _add_order(
                db,
                order_no="SO-2",
                customer_name="客户B",
                customer_id=2,
                total_amount="250.00",
                created_at=datetime(2026, 1, 10, 14, 0),
                items=[
                    {
                        "product_id": 1,
                        "product_name": "产品A",
                        "quantity": 1,
                        "price": 250,
                        "amount": 250,
                    },
                ],
            )

        svc = ReportService()
        # 产品维度：产品A 600+250=850，产品B 300；总额 1150
        by_product = svc.get_sales_report(group_by="product")
        products = {d["product_name"]: d for d in by_product["data"]}
        assert products["产品A"]["amount"] == 850.0
        assert products["产品B"]["amount"] == 300.0
        assert by_product["summary"]["total_amount"] == 1150.0

        # 客户维度：客户A 900，客户B 250；总额 1150
        by_customer = svc.get_sales_report(group_by="customer")
        customers = {d["customer_name"]: d for d in by_customer["data"]}
        assert customers["客户A"]["amount"] == 900.0
        assert customers["客户B"]["amount"] == 250.0
        assert by_customer["summary"]["total_amount"] == 1150.0

        # 日期维度：两单同一天 2026-01-10；总额 1150
        by_date = svc.get_sales_report(group_by="date")
        dates = {d["date"]: d for d in by_date["data"]}
        assert dates["2026-01-10"]["amount"] == 1150.0
        assert dates["2026-01-10"]["order_count"] == 2
        assert by_date["summary"]["total_amount"] == 1150.0

    def test_date_and_customer_filters_scope_to_sales_order(self, report_env):
        with report_env["test_db"]() as db:
            _add_order(
                db,
                order_no="SO-1",
                customer_name="客户A",
                customer_id=1,
                total_amount="100.00",
                created_at=datetime(2026, 1, 10, 9, 30),
                items=[
                    {
                        "product_id": 1,
                        "product_name": "产品A",
                        "quantity": 1,
                        "price": 100,
                        "amount": 100,
                    },
                ],
            )
            _add_order(
                db,
                order_no="SO-2",
                customer_name="客户A",
                customer_id=1,
                total_amount="200.00",
                created_at=datetime(2026, 2, 5, 9, 30),
                items=[
                    {
                        "product_id": 1,
                        "product_name": "产品A",
                        "quantity": 2,
                        "price": 100,
                        "amount": 200,
                    },
                ],
            )

        svc = ReportService()
        result = svc.get_sales_report(
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 1, 31),
            customer_id=1,
        )
        # 仅 Jan 的单：100
        assert result["summary"]["total_amount"] == 100.0
        assert result["summary"]["total_quantity"] == 1.0


# ---------------------------------------------------------------------------
# 4. 多租户隔离
# ---------------------------------------------------------------------------
class TestTenantIsolation:
    def test_tenants_are_isolated(self, report_env):
        # conftest 已默认 tenant_scope(1)；显式再包一层保证清晰
        with tenant_scope(1):
            with report_env["test_db"]() as db:
                _add_order(
                    db,
                    order_no="SO-T1",
                    customer_name="租户1客户",
                    customer_id=1,
                    total_amount="100.00",
                    created_at=datetime(2026, 1, 10, 9, 30),
                    items=[
                        {
                            "product_id": 1,
                            "product_name": "产品A",
                            "quantity": 1,
                            "price": 100,
                            "amount": 100,
                        },
                    ],
                )

        with tenant_scope(2):
            with report_env["test_db"]() as db:
                _add_order(
                    db,
                    order_no="SO-T2",
                    customer_name="租户2客户",
                    customer_id=2,
                    total_amount="700.00",
                    created_at=datetime(2026, 1, 10, 9, 30),
                    items=[
                        {
                            "product_id": 1,
                            "product_name": "产品A",
                            "quantity": 7,
                            "price": 100,
                            "amount": 700,
                        },
                    ],
                )

        with tenant_scope(1):
            svc = ReportService()
            r1 = svc.get_sales_report()
            assert r1["summary"]["total_amount"] == 100.0
            assert any(d["product_name"] == "产品A" for d in r1["data"])

        with tenant_scope(2):
            svc = ReportService()
            r2 = svc.get_sales_report()
            assert r2["summary"]["total_amount"] == 700.0

        # 租户 1 看不到租户 2 的 700
        with tenant_scope(1):
            svc = ReportService()
            r1_again = svc.get_sales_report()
            assert r1_again["summary"]["total_amount"] == 100.0


# ---------------------------------------------------------------------------
# R1：summary.total_amount 以 SalesOrder.total_amount 为准（权威）
# ---------------------------------------------------------------------------
class TestSummaryUsesSalesOrderTotal:
    def test_summary_total_uses_order_total_not_item_sum(self, report_env):
        """明细 amount 之和与订单 total_amount 不一致时，summary 以订单总额为准。"""
        with report_env["test_db"]() as db:
            order = SalesOrder(
                order_no="SO-DIV",
                customer_id=1,
                customer_name="客户A",
                total_amount=Decimal("1000.00"),
                state="confirmed",
                status="confirmed",
                invoice_status="invoiced",
                payment_state="paid",
                created_at=datetime(2026, 1, 10, 9, 30),
            )
            db.add(order)
            db.flush()
            # 明细 amount 之和 = 600 + 300 = 900，但订单总额 = 1000（权威字段）
            db.add_all(
                [
                    SalesOrderItem(
                        order_id=order.id,
                        product_id=1,
                        product_name="产品A",
                        quantity=Decimal("2"),
                        unit_price=Decimal("300"),
                        amount=Decimal("600"),
                        ordered_quantity=Decimal("2"),
                        delivered_quantity=Decimal("2"),
                    ),
                    SalesOrderItem(
                        order_id=order.id,
                        product_id=2,
                        product_name="产品B",
                        quantity=Decimal("1"),
                        unit_price=Decimal("300"),
                        amount=Decimal("300"),
                        ordered_quantity=Decimal("1"),
                        delivered_quantity=Decimal("1"),
                    ),
                ]
            )
            db.flush()

        svc = ReportService()
        # 客户维度：明细之和 900，但 summary 应等于订单总额 1000
        result = svc.get_sales_report(group_by="customer")
        assert result["success"] is True
        assert result["summary"]["total_amount"] == 1000.0

        by_product = svc.get_sales_report(group_by="product")
        assert by_product["summary"]["total_amount"] == 1000.0

        by_date = svc.get_sales_report(group_by="date")
        assert by_date["summary"]["total_amount"] == 1000.0


# ---------------------------------------------------------------------------
# R1：主源 group_by 无效值 fail-closed
# ---------------------------------------------------------------------------
class TestGroupByFailClosed:
    def test_unknown_group_by_fails_closed_on_sales_order_source(self, report_env):
        with report_env["test_db"]() as db:
            _add_order(
                db,
                order_no="SO-1",
                customer_name="客户A",
                customer_id=1,
                total_amount="100.00",
                created_at=datetime(2026, 1, 10, 9, 30),
                items=[
                    {
                        "product_id": 1,
                        "product_name": "产品A",
                        "quantity": 1,
                        "price": 100,
                        "amount": 100,
                    },
                ],
            )

        svc = ReportService()
        result = svc.get_sales_report(group_by="unknown")  # 默认 source=sales_order
        assert result["success"] is False
        assert "unknown" in result["message"]
