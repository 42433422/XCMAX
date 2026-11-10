"""Isolated sales domain regressions with an explicit synthetic payload."""

import copy
import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.application.sales_app_service import SalesAppService
from app.db.db_base import Base
from app.db.models import (
    Customer,
    InventoryLedger,
    InventoryTransaction,
    JournalEntry,
    Product,
    PurchaseUnit,
    ReceivableAllocation,
    SalesOrder,
    SalesOrderItem,
    Warehouse,
)
from app.domain.shared_services.report_service import ReportService
from app.infrastructure.tenant_scope import tenant_scope


def _sales_payload():
    return {
        "idempotency_key": "sw-7f01ebcab5745fb63a5fa652f91fcdd081760410f6c9f08fd059e48a2130f299",
        "order": {
            "customer_name": "客户B",
            "customer_id": None,
            "customer_resolution": "current_tenant_exact_name",
            "currency": "CNY",
            "items": [
                {
                    "product_name": "A 产品",
                    "product_id": None,
                    "product_resolution": "current_tenant_exact_name",
                    "quantity": 10,
                    "unit": "个",
                    "unit_price": 100,
                    "line_total": 1000,
                }
            ],
            "total_amount": 1000,
        },
        "fulfillment": {
            "requested": True,
            "quantity": 10,
            "unit": "个",
            "warehouse_id": None,
            "warehouse_resolution": "current_tenant_default",
        },
        "invoice": {"requested": True, "amount": 1000, "currency": "CNY"},
        "payment_allocation": {"requested": True, "amount": 1000, "currency": "CNY"},
    }


def _payload_with_key(key: str) -> dict:
    """以生产路由的精确销售写载荷为底，替换为自定义幂等键（用于边界探针）。"""
    payload = copy.deepcopy(_sales_payload())
    payload["idempotency_key"] = key
    return payload


@pytest.fixture(scope="function")
def _e2e_db(tmp_path):
    """文件落盘 SQLite，由 ``Base.metadata`` 建表；返回会话工厂。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'erp_absorb_e2e.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    from sqlalchemy import text as _text

    with engine.begin() as conn:
        conn.execute(
            _text(
                "CREATE TABLE IF NOT EXISTS ai_action_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT (datetime('now')), actor TEXT, action TEXT NOT NULL, payload TEXT)"
            )
        )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    engine.dispose()


def _patch_sessionlocal(monkeypatch, factory):
    """把生产 ``get_db()`` 指到测试会话工厂（只替换 SessionLocal，不动领域逻辑）。"""
    monkeypatch.setattr("app.db.session.SessionLocal", factory)


def _seed_tenant(factory, tenant_id: int, warehouse_code: str, ledger_qty: int = 100) -> dict:
    """在显式 tenant_scope 下种子真实当前租户客户/产品/活动仓库/库存台账。"""
    with tenant_scope(tenant_id):
        db = factory()
        try:
            customer = Customer(customer_name="客户B")
            product = Product(name="A 产品", unit="个")
            warehouse = Warehouse(
                code=warehouse_code,
                name=f"仓{tenant_id}",
                status="active",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add_all([customer, product, warehouse])
            db.flush()
            ledger = InventoryLedger(
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=ledger_qty,
                available_quantity=ledger_qty,
                reserved_quantity=0,
                unit="个",
                in_date=datetime.now().date(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(ledger)
            db.commit()
            return {
                "tenant_id": tenant_id,
                "customer_id": customer.id,
                "product_id": product.id,
                "warehouse_id": warehouse.id,
                "ledger_id": ledger.id,
            }
        finally:
            db.close()


def _seed_purchase_unit_only(
    factory, tenant_id: int, warehouse_code: str, ledger_qty: int = 100, batch_no: str | None = None
) -> dict:
    """在显式 tenant_scope 下种子【仅采购单位】(桌面客户B) + 产品 + 活动仓库 + 库存台账。

    刻意不创建任何核心 ``Customer``：验证「采购单位吸收为核心客户」路径
    （core=0 且同租户精确 PurchaseUnit=1 → 恰好新建一个核心 Customer）。
    """
    with tenant_scope(tenant_id):
        db = factory()
        try:
            pu = PurchaseUnit(
                unit_name="客户B",
                contact_person="采购人B",
                contact_phone="13800000000",
                address="地址B",
            )
            product = Product(name="A 产品", unit="个")
            warehouse = Warehouse(
                code=warehouse_code,
                name=f"仓{tenant_id}",
                status="active",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add_all([pu, product, warehouse])
            db.flush()
            ledger = InventoryLedger(
                product_id=product.id,
                warehouse_id=warehouse.id,
                batch_no=batch_no,
                quantity=ledger_qty,
                available_quantity=ledger_qty,
                reserved_quantity=0,
                unit="个",
                in_date=datetime.now().date(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(ledger)
            db.commit()
            return {
                "tenant_id": tenant_id,
                "purchase_unit_id": pu.id,
                "product_id": product.id,
                "warehouse_id": warehouse.id,
                "ledger_id": ledger.id,
            }
        finally:
            db.close()


def _seed_product_warehouse_only(factory, tenant_id: int, warehouse_code: str) -> dict:
    """种子产品 + 活动仓库 + 库存台账，但不创建任何客户/采购单位（用于缺客户场景）。"""
    with tenant_scope(tenant_id):
        db = factory()
        try:
            product = Product(name="A 产品", unit="个")
            warehouse = Warehouse(
                code=warehouse_code,
                name=f"仓{tenant_id}",
                status="active",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add_all([product, warehouse])
            db.flush()
            ledger = InventoryLedger(
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=100,
                available_quantity=100,
                reserved_quantity=0,
                unit="个",
                in_date=datetime.now().date(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(ledger)
            db.commit()
            return {
                "tenant_id": tenant_id,
                "product_id": product.id,
                "warehouse_id": warehouse.id,
                "ledger_id": ledger.id,
            }
        finally:
            db.close()


def _count_table(factory, model, tenant_id: int) -> int:
    """按租户统计某业务表行数（全局 tenant filter 起作用）。"""
    with tenant_scope(tenant_id):
        db = factory()
        try:
            return db.query(model).count()
        finally:
            db.close()


def _count_business_rows(factory, tenant_id: int) -> dict[str, int]:
    return {
        "orders": _count_table(factory, SalesOrder, tenant_id),
        "items": _count_table(factory, SalesOrderItem, tenant_id),
        "inv_tx": _count_table(factory, InventoryTransaction, tenant_id),
        "journal": _count_table(factory, JournalEntry, tenant_id),
        "alloc": _count_table(factory, ReceivableAllocation, tenant_id),
    }


def _ledger_available(factory, tenant_id: int, product_id: int) -> float | None:
    with tenant_scope(tenant_id):
        db = factory()
        try:
            ledge = (
                db.query(InventoryLedger).filter(InventoryLedger.product_id == product_id).first()
            )
            return float(ledge.available_quantity) if ledge else None
        finally:
            db.close()


def _assert_one_exact_closed_loop_row_set(factory, seed) -> None:
    """断言真实 W1 闭环的精确业务行与后置条件（订单1+明细1、库存90、双平衡凭证、应收已收）。"""
    assert _ledger_available(factory, 1, seed["product_id"]) == 90.0
    with tenant_scope(1):
        db = factory()
        try:
            order = db.query(SalesOrder).first()
            assert order is not None
            assert order.customer_name == "客户B"
            assert order.state == "confirmed"
            assert order.invoice_status == "invoiced"
            assert order.payment_state == "paid"
            assert order.fulfillment_state() == "delivered"
            assert float(order.total_amount) == 1000.0
            assert float(order.paid_amount) == 1000.0
            items = db.query(SalesOrderItem).all()
            assert len(items) == 1
            item = items[0]
            assert item.product_name == "A 产品"
            assert float(item.quantity) == 10
            assert item.unit == "个"
            assert float(item.unit_price) == 100
            assert float(item.amount) == 1000
            inv_tx = db.query(InventoryTransaction).all()
            assert len(inv_tx) == 1
            assert inv_tx[0].transaction_type == "out"
            assert float(inv_tx[0].quantity) == -10
            entries = db.query(JournalEntry).all()
            assert len(entries) == 2
            for e in entries:
                assert e.is_balanced() is True
            allocs = db.query(ReceivableAllocation).all()
            assert len(allocs) == 1
            assert allocs[0].status == "paid"
            assert float(allocs[0].allocated_amount) == 1000.0
        finally:
            db.close()


class TestRealSqliteAtomicClosedLoop:
    def test_fractional_quantity_price_decimal_exact_accounting(self, _e2e_db, monkeypatch):
        """修正 B：0.10 × 0.20 = 0.020 全程 Decimal，无二进制浮点伪影。

        断言持久化订单总额、明细合计、凭证与收款分配均为精确定点 Decimal 0.02
        （Numeric(18,2) 的定点等价），证明复合账务不经任何 float 运算。
        """
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        payload = {
            "idempotency_key": "w1-10-fractional-decimal-e2e",
            "order": {
                "customer_id": seed["customer_id"],
                "customer_name": "客户B",
                "currency": "CNY",
                "total_amount": Decimal("0.020"),
                "items": [
                    {
                        "product_id": seed["product_id"],
                        "product_name": "A 产品",
                        "quantity": Decimal("0.10"),
                        "unit_price": Decimal("0.20"),
                        "line_total": Decimal("0.020"),
                        "unit": "个",
                    }
                ],
            },
            "fulfillment": {
                "requested": True,
                "quantity": Decimal("0.10"),
                "unit": "个",
                "warehouse_id": seed["warehouse_id"],
                "warehouse_resolution": "current_tenant_default",
            },
            "invoice": {"requested": True, "amount": Decimal("0.020"), "currency": "CNY"},
            "payment_allocation": {
                "requested": True,
                "amount": Decimal("0.020"),
                "currency": "CNY",
            },
        }
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is True, result

        def _fx(value) -> Decimal:
            return Decimal(str(value)).normalize()

        with tenant_scope(1):
            db = factory()
            try:
                order = db.query(SalesOrder).first()
                item = db.query(SalesOrderItem).first()
                entries = db.query(JournalEntry).all()
                alloc = db.query(ReceivableAllocation).first()
            finally:
                db.close()
        assert order is not None and item is not None and (alloc is not None)
        assert _fx(order.total_amount) == Decimal("0.020")
        assert _fx(order.paid_amount) == Decimal("0.020")
        assert _fx(item.quantity) == Decimal("0.1")
        assert _fx(item.unit_price) == Decimal("0.2")
        assert _fx(item.amount) == Decimal("0.020")
        assert len(entries) == 2
        for e in entries:
            assert _fx(e.debit_total) == Decimal("0.020")
            assert _fx(e.credit_total) == Decimal("0.020")
            for line in e.lines:
                assert _fx(line.debit) == Decimal("0.020") or _fx(line.credit) == Decimal("0.020")
        assert _fx(alloc.allocated_amount) == Decimal("0.020")

    @pytest.mark.parametrize("refunded", [False, True])
    @pytest.mark.parametrize("legacy_null_tenant", [False, True])
    def test_legacy_receipt_replay_requires_reconciliation(
        self, _e2e_db, monkeypatch, refunded, legacy_null_tenant
    ):
        from app.application.payment_service import refund

        if legacy_null_tenant:
            monkeypatch.setenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", "1")
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        with tenant_scope(1):
            payload = _sales_payload()
            service = SalesAppService()
            assert service.execute_closed_loop(payload)["success"]
            with factory() as db:
                receipt = db.query(ReceivableAllocation).filter_by(reference_type="payment").one()
                receipt_id = receipt.id
                receipt.request_key = receipt.request_fingerprint = None
                if legacy_null_tenant:
                    receipt.tenant_id = None
                db.commit()
            if refunded:
                assert refund(allocation_id=receipt_id)["success"]
            before = _count_business_rows(factory, 1)
            with factory() as db:
                paid = db.query(SalesOrder).one().paid_amount
            result = service.execute_closed_loop(payload)
            assert result["success"] is False
            assert result["failed_step"] == "payment_reconciliation"
            assert "人工核对" in result["message"]
            assert _count_business_rows(factory, 1) == before
            assert _ledger_available(factory, 1, seed["product_id"]) == 90.0
            with factory() as db:
                assert db.query(SalesOrder).one().paid_amount == paid
                assert db.get(ReceivableAllocation, receipt_id).request_key is None

    def test_missing_tenant_fail_closed_zero_writes(self, _e2e_db, monkeypatch):
        """后置条件 7：缺租户上下文 → fail-closed 零持久化。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        payload = _sales_payload()
        with tenant_scope(None):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert result["error_code"] == "NO_TENANT_CONTEXT"
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_injected_tenant_id_fail_closed(self, _e2e_db, monkeypatch):
        """后置条件 7：任意深度注入 tenant_id → 拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        payload = _sales_payload()
        payload["order"]["tenant_id"] = 1
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert result["error_code"] == "TENANT_ID_REJECTED"
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_missing_and_ambiguous_and_mismatch_resolution_fail_closed(self, _e2e_db, monkeypatch):
        """后置条件 7：缺/歧义/不匹配客户/产品/仓库、单位不匹配 → 零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        base = _sales_payload()

        def _run(payload):
            with tenant_scope(1):
                return SalesAppService().execute_closed_loop(payload)

        def _assert_fail(payload):
            res = _run(payload)
            assert res["success"] is False, res
            assert _count_business_rows(factory, 1) == {
                "orders": 0,
                "items": 0,
                "inv_tx": 0,
                "journal": 0,
                "alloc": 0,
            }

        p = dict(base)
        p["order"] = dict(base["order"], customer_name="不存在客户")
        _assert_fail(p)
        p = dict(base)
        p["order"] = dict(base["order"])
        p["order"]["items"] = [dict(base["order"]["items"][0], product_name="不存在产品")]
        _assert_fail(p)
        p = dict(base)
        p["fulfillment"] = dict(base["fulfillment"], warehouse_id=99999)
        _assert_fail(p)
        p = dict(base)
        p["order"] = dict(base["order"])
        p["order"]["items"] = [dict(base["order"]["items"][0], unit="支")]
        p["fulfillment"] = dict(base["fulfillment"], unit="支")
        _assert_fail(p)

    def test_ambiguous_customer_fail_closed(self, _e2e_db, monkeypatch):
        """后置条件 7：同租户同名客户多个精确匹配 → 拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        with tenant_scope(1):
            db = factory()
            try:
                db.add(Customer(customer_name="客户B"))
                db.commit()
            finally:
                db.close()
        payload = _sales_payload()
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_ambiguous_product_fail_closed(self, _e2e_db, monkeypatch):
        """后置条件 7：同租户同名产品多个精确匹配 → 拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        with tenant_scope(1):
            db = factory()
            try:
                db.add(Product(name="A 产品", unit="个"))
                db.commit()
            finally:
                db.close()
        payload = _sales_payload()
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_missing_warehouse_fail_closed(self, _e2e_db, monkeypatch):
        """后置条件 7：当前租户无活动仓库 → 拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        with tenant_scope(1):
            db = factory()
            try:
                db.add_all([Customer(customer_name="客户B"), Product(name="A 产品", unit="个")])
                db.commit()
            finally:
                db.close()
        payload = _sales_payload()
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert result.get("failed_step") == "resolve_warehouse"
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    @pytest.mark.parametrize("step", ["quote", "confirm", "deliver", "invoice", "payment"])
    def test_step_failure_rolls_back_whole_transaction(self, _e2e_db, monkeypatch, step):
        """后置条件 8：各拥有步注入失败 → 整单回滚，无订单/明细/库存/凭证/分配，台账仍 100。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        with patch.object(
            SalesAppService,
            step,
            return_value={"success": False, "message": f"injected {step} failure"},
        ):
            with tenant_scope(1):
                payload = _sales_payload()
                result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert result["failed_step"] == step
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }
        assert _ledger_available(factory, 1, seed["product_id"]) == 100.0

    def test_all_owning_steps_share_one_session_identity(self, _e2e_db, monkeypatch):
        """后置条件 9：quote/confirm/every deliver/invoice/payment 收到同一 SQLAlchemy 会话。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        recorded: list[object] = []
        patchers = []
        for method in ("quote", "confirm", "deliver", "invoice", "payment"):
            orig = getattr(SalesAppService, method)

            def make_wrapper(original):

                def wrapper(self, *args, **kwargs):
                    recorded.append(kwargs.get("db"))
                    return original(self, *args, **kwargs)

                return wrapper

            patchers.append(patch.object(SalesAppService, method, make_wrapper(orig)))
        for p in patchers:
            p.start()
        try:
            with tenant_scope(1):
                payload = _sales_payload()
                result = SalesAppService().execute_closed_loop(payload)
        finally:
            for p in patchers:
                p.stop()
        assert result["success"] is True, result
        assert len(recorded) == 5, recorded
        assert len({id(d) for d in recorded}) == 1, recorded

    def test_requested_flag_must_be_bool(self, _e2e_db, monkeypatch):
        """执行器正确性：requested 必须为 bool，真值非 bool 在分支前即拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        payload = _sales_payload()
        payload["fulfillment"]["requested"] = "yes"
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(payload)
        assert res["success"] is False, res
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_bool_and_invalid_decimal_rejected(self, _e2e_db, monkeypatch):
        """执行器正确性：bool 数量与 InvalidOperation 单价均被拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        base = _sales_payload()
        p = copy.deepcopy(base)
        p["order"]["items"][0]["quantity"] = True
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(p)
        assert res["success"] is False, res
        p2 = copy.deepcopy(base)
        p2["order"]["items"][0]["unit_price"] = "z"
        with tenant_scope(1):
            res2 = SalesAppService().execute_closed_loop(p2)
        assert res2["success"] is False, res2
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_explicit_cross_tenant_entity_rejected(self, _e2e_db, monkeypatch):
        """执行器正确性：显式传入他租户实体 id（客户/产品）→ 显式 current-tenant 校验拒绝。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        seed2 = _seed_tenant(factory, 2, "WH-T2")
        base = _sales_payload()
        p = copy.deepcopy(base)
        p["order"]["customer_id"] = seed2["customer_id"]
        p["order"]["customer_name"] = None
        p["order"]["customer_resolution"] = None
        p["order"]["items"][0]["product_id"] = seed2["product_id"]
        p["order"]["items"][0]["product_name"] = None
        p["order"]["items"][0]["product_resolution"] = None
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(p)
        assert res["success"] is False, res
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    @pytest.mark.parametrize("section", ["fulfillment", "invoice", "payment_allocation"])
    @pytest.mark.parametrize("bad", [0, "", None, [], {}])
    def test_requested_non_bool_rejected_all_sections(self, _e2e_db, monkeypatch, section, bad):
        """执行器正确性：requested 为 0/空串/None/list/dict（非 bool）→ 分支前拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        payload = _sales_payload()
        payload[section]["requested"] = bad
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(payload)
        assert res["success"] is False, res
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    @pytest.mark.parametrize(
        "bad_num", [float("nan"), float("inf"), float("-inf"), "nan", "inf", "-inf", True, "abc"]
    )
    def test_non_finite_and_bool_numeric_rejected(self, _e2e_db, monkeypatch, bad_num):
        """执行器正确性：NaN/±Infinity/bool/非法字符串等所有非有限数值 → 结构化拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        payload = _sales_payload()
        payload["order"]["items"][0]["quantity"] = bad_num
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(payload)
        assert res["success"] is False, res
        assert res["error_code"] == "INVALID_CLOSED_LOOP_PAYLOAD"
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_malformed_entity_ids_structured_failure(self, _e2e_db, monkeypatch):
        """执行器正确性：畸形实体 id（customer/product/warehouse）→ 结构化失败而非逃逸异常，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        base = _sales_payload()
        p = copy.deepcopy(base)
        p["order"]["customer_id"] = "abc"
        p["order"]["customer_name"] = None
        p["order"]["customer_resolution"] = None
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(p)
        assert res["success"] is False, res
        assert res["failed_step"] == "resolve_customer"
        p2 = copy.deepcopy(base)
        p2["order"]["items"][0]["product_id"] = "abc"
        p2["order"]["items"][0]["product_name"] = None
        p2["order"]["items"][0]["product_resolution"] = None
        with tenant_scope(1):
            res2 = SalesAppService().execute_closed_loop(p2)
        assert res2["success"] is False, res2
        assert res2["failed_step"] == "resolve_product"
        p3 = copy.deepcopy(base)
        p3["fulfillment"]["warehouse_id"] = "abc"
        p3["fulfillment"]["warehouse_resolution"] = None
        with tenant_scope(1):
            res3 = SalesAppService().execute_closed_loop(p3)
        assert res3["success"] is False, res3
        assert res3["failed_step"] == "resolve_warehouse"
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_unrelated_second_line_not_treated_as_replay(self, _e2e_db, monkeypatch):
        """复合命名空间边界：标记后紧跟换行的无关第二行绝不被当作幂等重放候选。

        预置一行 remark 恰为 ``idempotency:sales_quote:{key}\\n<无关文本>`` 的既有订单；
        生产路径查询同 key 不得把该行识别为重放，而应新建自己的复合单，
        且该无关行保持原样（remark 未追加复合指纹、未被改动）。
        """
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        key = "nsboundary"
        unrelated_text = "some arbitrary unrelated second line"
        unrelated_remark = f"idempotency:sales_quote:{key}\n{unrelated_text}"
        with tenant_scope(1):
            db = factory()
            try:
                unrelated = SalesOrder(
                    order_no="UNRELATED-NS-1",
                    customer_id=seed["customer_id"],
                    customer_name="客户B",
                    state="quote",
                    status="quote",
                    total_amount=Decimal("0"),
                    paid_amount=Decimal("0"),
                    currency="CNY",
                    remark=unrelated_remark,
                    created_at=datetime.now(),
                )
                db.add(unrelated)
                db.commit()
                unrelated_id = unrelated.id
            finally:
                db.close()
        payload = _payload_with_key(key)
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is True, result
        assert result["replayed"] is False
        with tenant_scope(1):
            db = factory()
            try:
                untouched = db.query(SalesOrder).filter(SalesOrder.id == unrelated_id).first()
                assert untouched is not None
                assert untouched.remark == unrelated_remark
                new_order = (
                    db.query(SalesOrder).filter(SalesOrder.id == result["data"]["order_id"]).first()
                )
                assert new_order is not None
                assert new_order.id != unrelated_id
                assert "\nw1-10-closed-loop-composite:" in new_order.remark
            finally:
                db.close()
        rows = _count_business_rows(factory, 1)
        assert rows["orders"] == 2


class TestIdempotencyPrefixBoundary:
    def test_prefix_key_replay_order_abcd_then_abc_distinct(self, _e2e_db, monkeypatch):
        """前缀键先建长键再建短键：``abcd`` 先行，``abc`` 不得被误判为 abcd 的重放。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        with tenant_scope(1):
            r_abcd = SalesAppService().execute_closed_loop(_payload_with_key("abcd"))
            assert r_abcd["success"] is True, r_abcd
            assert r_abcd["replayed"] is False
            r_abc = SalesAppService().execute_closed_loop(_payload_with_key("abc"))
            assert r_abc["success"] is True, r_abc
            assert r_abc["replayed"] is False
            assert r_abc["data"]["order_id"] != r_abcd["data"]["order_id"]
        rows = _count_business_rows(factory, 1)
        assert rows["orders"] == 2
        assert rows["items"] == 2

    def test_prefix_key_replay_order_abc_then_abcd_distinct(self, _e2e_db, monkeypatch):
        """反向：``abc`` 先行，``abcd`` 不得被误判为 abc 的重放。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 2, "WH-T2")
        with tenant_scope(2):
            r_abc = SalesAppService().execute_closed_loop(_payload_with_key("abc"))
            assert r_abc["success"] is True, r_abc
            assert r_abc["replayed"] is False
            r_abcd = SalesAppService().execute_closed_loop(_payload_with_key("abcd"))
            assert r_abcd["success"] is True, r_abcd
            assert r_abcd["replayed"] is False
            assert r_abcd["data"]["order_id"] != r_abc["data"]["order_id"]
        rows = _count_business_rows(factory, 2)
        assert rows["orders"] == 2
        assert rows["items"] == 2

    def test_like_metachars_do_not_cross_match(self, _e2e_db, monkeypatch):
        """键内 ``_`` / ``%`` 不得作为 SQL LIKE 通配符跨键匹配另一键。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        with tenant_scope(1):
            r_plain = SalesAppService().execute_closed_loop(_payload_with_key("abcXdef"))
            assert r_plain["success"] is True, r_plain
            assert r_plain["replayed"] is False
            r_under = SalesAppService().execute_closed_loop(_payload_with_key("abc_def"))
            assert r_under["success"] is True, r_under
            assert r_under["replayed"] is False
            assert r_under["data"]["order_id"] != r_plain["data"]["order_id"]
            r_pct = SalesAppService().execute_closed_loop(_payload_with_key("abc%def"))
            assert r_pct["success"] is True, r_pct
            assert r_pct["replayed"] is False
            assert r_pct["data"]["order_id"] not in (
                r_plain["data"]["order_id"],
                r_under["data"]["order_id"],
            )
        rows = _count_business_rows(factory, 1)
        assert rows["orders"] == 3
        assert rows["items"] == 3

    @pytest.mark.parametrize("key", ["abc", "长" * 129])
    def test_exact_key_replay_after_fingerprint_appended(self, _e2e_db, monkeypatch, key):
        """指纹追加后，同一精确键 + 完整载荷仍幂等重放，不增行、不动库存。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        payload = _payload_with_key("abc")
        with tenant_scope(1):
            first = SalesAppService().execute_closed_loop(payload)
            assert first["success"] is True, first
            assert first["replayed"] is False
            db = factory()
            try:
                order = (
                    db.query(SalesOrder).filter(SalesOrder.id == first["data"]["order_id"]).first()
                )
                assert order.remark.startswith("idempotency:sales_quote:abc")
                assert "\nw1-10-closed-loop-composite:" in order.remark
            finally:
                db.close()
            before = _count_business_rows(factory, 1)
            before_avail = _ledger_available(factory, 1, seed["product_id"])
            assert before_avail == 90.0
            second = SalesAppService().execute_closed_loop(payload)
            assert second["success"] is True, second
            assert second["replayed"] is True
            assert second["data"]["order_id"] == first["data"]["order_id"]
        assert _count_business_rows(factory, 1) == before
        assert _ledger_available(factory, 1, seed["product_id"]) == before_avail == 90.0


class TestPurchaseUnitToCoreCustomerAbsorption:
    def test_purchase_unit_only_absorbs_to_one_core_customer(self, _e2e_db, monkeypatch):
        """仅采购单位「客户B」→ 恰好一个同租户 PurchaseUnit → 恰好新建一个核心 Customer。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_purchase_unit_only(factory, 1, "WH-T1")
        with tenant_scope(1):
            payload = _sales_payload()
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is True, result
        with tenant_scope(1):
            db = factory()
            try:
                customers = db.query(Customer).filter(Customer.customer_name == "客户B").all()
                assert len(customers) == 1, customers
                c = customers[0]
                assert c.tenant_id == 1
                assert c.contact_person == "采购人B"
                assert c.contact_phone == "13800000000"
                assert c.contact_address == "地址B"
                order = db.query(SalesOrder).first()
                assert order is not None
                assert order.customer_id == c.id
                assert order.customer_name == "客户B"
            finally:
                db.close()
        _assert_one_exact_closed_loop_row_set(factory, seed)

    def test_purchase_unit_bridge_delivers_from_unique_batched_inventory(
        self, _e2e_db, monkeypatch
    ):
        """桌面带批次入库 100 时，闭环解析唯一台账并真实扣减 100→90。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_purchase_unit_only(factory, 1, "WH-T1", batch_no="W110-DESKTOP-BATCH")
        with tenant_scope(1):
            payload = _sales_payload()
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is True, result
        assert _ledger_available(factory, 1, seed["product_id"]) == 90.0
        with tenant_scope(1):
            db = factory()
            try:
                out_txn = (
                    db.query(InventoryTransaction)
                    .filter(InventoryTransaction.transaction_type == "out")
                    .one()
                )
                assert out_txn.batch_no == "W110-DESKTOP-BATCH"
                assert float(out_txn.before_quantity) == 100.0
                assert float(out_txn.after_quantity) == 90.0
            finally:
                db.close()

    def test_purchase_unit_no_tenant_fail_closed(self, _e2e_db, monkeypatch):
        """缺租户上下文 → NO_TENANT_CONTEXT，零核心客户、零业务行。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_purchase_unit_only(factory, 1, "WH-T1")
        payload = _sales_payload()
        with tenant_scope(None):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert result["error_code"] == "NO_TENANT_CONTEXT"
        assert _count_table(factory, Customer, 1) == 0
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_purchase_unit_cross_tenant_fail_closed(self, _e2e_db, monkeypatch):
        """跨租户：采购单位「客户B」仅在他租户(2)，当前租户(1)无匹配 → fail-closed 零吸收。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_purchase_unit_only(factory, 2, "WH-T2")
        _seed_product_warehouse_only(factory, 1, "WH-T1")
        with tenant_scope(1):
            payload = _sales_payload()
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False, result
        assert result["failed_step"] == "resolve_customer"
        assert _count_table(factory, Customer, 1) == 0
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_purchase_unit_ambiguous_fail_closed(self, _e2e_db, monkeypatch):
        """歧义：同租户两个同名采购单位「客户B」→ fail-closed，零吸收、零订单。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_product_warehouse_only(factory, 1, "WH-T1")
        with tenant_scope(1):
            db = factory()
            try:
                db.add_all([PurchaseUnit(unit_name="客户B"), PurchaseUnit(unit_name="客户B")])
                db.commit()
            finally:
                db.close()
        with tenant_scope(1):
            payload = _sales_payload()
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False, result
        assert result["failed_step"] == "resolve_customer"
        assert _count_table(factory, Customer, 1) == 0
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_purchase_unit_missing_purchase_unit_fail_closed(self, _e2e_db, monkeypatch):
        """缺失：当前租户既无核心客户也无采购单位「客户B」→ fail-closed，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_product_warehouse_only(factory, 1, "WH-T1")
        with tenant_scope(1):
            payload = _sales_payload()
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False, result
        assert result["failed_step"] == "resolve_customer"
        assert _count_table(factory, Customer, 1) == 0
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_purchase_unit_later_step_failure_rolls_back_absorbed_customer(
        self, _e2e_db, monkeypatch
    ):
        """回滚：后续收款步失败 → 连同新建的核心客户整单回滚（零客户、零业务行、库存仍 100）。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_purchase_unit_only(factory, 1, "WH-T1")
        with patch.object(
            SalesAppService,
            "payment",
            return_value={"success": False, "message": "injected payment failure"},
        ):
            with tenant_scope(1):
                payload = _sales_payload()
                result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert result["failed_step"] == "payment"
        assert _count_table(factory, Customer, 1) == 0
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }
        assert _ledger_available(factory, 1, seed["product_id"]) == 100.0

    def test_purchase_unit_no_duplicate_customer_on_rerun(self, _e2e_db, monkeypatch):
        """不重复：同采购单位先后以不同幂等键执行两次 → 仍恰好一个核心 Customer（无重复吸收）。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_purchase_unit_only(factory, 1, "WH-T1")
        with tenant_scope(1):
            payload = _sales_payload()
            r1 = SalesAppService().execute_closed_loop(payload)
            assert r1["success"] is True, r1
            payload2 = copy.deepcopy(payload)
            payload2["idempotency_key"] = "sw-purchase-unit-no-dup"
            r2 = SalesAppService().execute_closed_loop(payload2)
            assert r2["success"] is True, r2
            assert r2["data"]["order_id"] != r1["data"]["order_id"]
        with tenant_scope(1):
            db = factory()
            try:
                customers = db.query(Customer).filter(Customer.customer_name == "客户B").all()
                assert len(customers) == 1, customers
            finally:
                db.close()
        assert _ledger_available(factory, 1, seed["product_id"]) == 80.0

    def test_purchase_unit_core_duplicate_fail_closed(self, _e2e_db, monkeypatch):
        """核心重复：同租户两个同名核心 Customer「客户B」→ fail-closed，零业务行、不桥接。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_product_warehouse_only(factory, 1, "WH-T1")
        with tenant_scope(1):
            db = factory()
            try:
                db.add_all([Customer(customer_name="客户B"), Customer(customer_name="客户B")])
                db.commit()
            finally:
                db.close()
        with tenant_scope(1):
            payload = _sales_payload()
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False, result
        assert result["failed_step"] == "resolve_customer"
        assert _count_table(factory, Customer, 1) == 2
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_purchase_unit_same_payload_idempotent_no_duplicate_inventory_90(
        self, _e2e_db, monkeypatch
    ):
        """幂等：同载荷（同幂等键）执行两次 → 仍恰好一个核心 Customer/一张订单，库存保持 90。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_purchase_unit_only(factory, 1, "WH-T1")
        with tenant_scope(1):
            payload = _sales_payload()
            r1 = SalesAppService().execute_closed_loop(payload)
            assert r1["success"] is True, r1
            r2 = SalesAppService().execute_closed_loop(payload)
            assert r2["success"] is True, r2
            assert r2["data"]["order_id"] == r1["data"]["order_id"]
        with tenant_scope(1):
            db = factory()
            try:
                customers = db.query(Customer).filter(Customer.customer_name == "客户B").all()
                assert len(customers) == 1, customers
                assert db.query(SalesOrder).count() == 1
            finally:
                db.close()
        assert _ledger_available(factory, 1, seed["product_id"]) == 90.0
