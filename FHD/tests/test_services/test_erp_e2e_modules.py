"""
ERP 模块端到端真实链路验证测试（Task 7, upgrade-erp-modules-odoo18）

用真实 sqlite :memory:（StaticPool 复用同一引擎），通过 patch 让
purchase/inventory/manufacturing/accounting 四个服务模块的 get_db 指向同一内存库，
并种入默认科目（seed_default_chart_of_accounts）。多租户过滤由 conftest 的
``tenant_scope(1)`` autouse fixture 提供，本文件内再显式 tenant_scope(1) 兜底，
保证继承 TenantScopedMixin 的模型读写不被全局 tenant filter deny。

逐条验证 5 条真实闭环：
1. 采购入库 → 应付记账（借1401库存 / 贷2201应付，借贷平衡，伴供应商 partner）
2. 库存盘点（未确认不改库存 → 确认后库存=实盘并写 count 流水）
3. 按 BOM 生产（领料扣原料 → 完工成品+M → 工单 done）
4. 客户多地址（add_address delivery → get_addresses 关联且类型正确）
5. 凭证冲销（反向分录借贷平衡、原凭证标记、重复冲销被拒）
"""

from __future__ import annotations

import contextlib
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.accounting_services as acct_svc_mod
import app.services.inventory_service as inv_svc_mod
import app.services.manufacturing_service as mrp_svc_mod
import app.services.purchase_service as purchase_svc_mod
from app.application.customer_app_service import CustomerApplicationService
from app.db.base import Base
from app.db.models import (
    Customer,
    CustomerAddress,
    InventoryLedger,
    InventoryTransaction,
    JournalEntry,
    Product,
    Supplier,
    Warehouse,
)
from app.db.models.mrp import ManufacturingOrder
from app.infrastructure.tenant_scope import tenant_scope
from app.services.accounting_services import (
    create_journal_entry,
    journal_entry_reverse,
    seed_default_chart_of_accounts,
)
from app.services.inventory_service import InventoryService
from app.services.manufacturing_service import ManufacturingService
from app.services.purchase_service import PurchaseService


@pytest.fixture(scope="function")
def erp_env():
    """共享内存库 + 统一 patch 四个服务模块的 get_db 指向同一持久会话。

    参照 tests/test_services/test_accounting_services.py：四个服务模块的 get_db
    都 yield 同一个持久会话（persistent），避免跨会话返回 ORM 对象导致
    DetachedInstanceError。返回 ``test_db``（contextmanager）与
    ``session_factory``（供客户服务开独立会话）供用例校验。
    """
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
        _patch_get_db(purchase_svc_mod, test_db),
        _patch_get_db(inv_svc_mod, test_db),
        _patch_get_db(mrp_svc_mod, test_db),
        _patch_get_db(acct_svc_mod, test_db),
    ):
        with tenant_scope(1):
            seed_result = seed_default_chart_of_accounts()
            assert seed_result["success"] is True
            yield {"test_db": test_db, "session_factory": session_factory}
    persistent.close()


@contextlib.contextmanager
def _patch_get_db(module, fn):
    from unittest.mock import patch

    with patch.object(module, "get_db", fn):
        yield


# ---------------------------------------------------------------------------
# 链路 1：采购入库 → 应付记账（借1401库存 / 贷2201应付）
# ---------------------------------------------------------------------------
class TestPurchaseInboundAPChain:
    def test_inbound_posts_balanced_ap_entry(self, erp_env):
        with erp_env["test_db"]() as db:
            supplier = Supplier(code="S-E2E-01", name="供应商A", status="active")
            db.add(supplier)
            db.flush()
            product = Product(model_number="RAW-E2E", name="原料A", unit="个")
            db.add(product)
            db.flush()
            wh = Warehouse(code="WH-E2E", name="主仓库", status="active")
            db.add(wh)
            db.flush()
            supplier_id, product_id, wh_id = supplier.id, product.id, wh.id

        svc = PurchaseService()
        result = svc.create_purchase_inbound(
            {
                "inbound_no": "PI-E2E-001",
                "supplier_id": supplier_id,
                "warehouse_id": wh_id,
                "handler": "tester",
                "items": [{"product_id": product_id, "quantity": 50, "unit_price": 10}],
            }
        )
        assert result["success"] is True, result.get("message")

        with erp_env["test_db"]() as db:
            # 原料库存 +50
            ledger = (
                db.query(InventoryLedger)
                .filter_by(product_id=product_id, warehouse_id=wh_id)
                .first()
            )
            assert ledger is not None
            assert float(ledger.quantity) == 50.0

            # 存在采购入库的借贷平衡分录：借1401 / 贷2201（伴供应商 partner）
            entry = (
                db.query(JournalEntry)
                .filter(JournalEntry.reference_type == "purchase_inbound")
                .first()
            )
            assert entry is not None
            assert entry.is_balanced() is True

            lines = {l.account_code: l for l in entry.lines}
            assert lines["1401"].debit == 500.0
            assert lines["1401"].credit == 0
            assert lines["2201"].credit == 500.0
            assert lines["2201"].debit == 0
            assert lines["2201"].partner_id == supplier_id
            assert lines["2201"].partner_name == "供应商A"
            # 借贷各自合计 500，总体平衡
            assert sum(float(l.debit) for l in entry.lines) == 500.0
            assert sum(float(l.credit) for l in entry.lines) == 500.0


# ---------------------------------------------------------------------------
# 链路 2：库存盘点（未确认不改库存 → 确认后库存=实盘并写 count 流水）
# ---------------------------------------------------------------------------
class TestInventoryCountChain:
    def test_count_confirm_adjusts_stock_and_writes_ledger(self, erp_env):
        with erp_env["test_db"]() as db:
            product = Product(model_number="CT-E2E", name="盘点品", unit="个")
            db.add(product)
            db.flush()
            wh = Warehouse(code="WH-CT", name="盘点仓", status="active")
            db.add(wh)
            db.flush()
            product_id, wh_id = product.id, wh.id

        inv = InventoryService()
        pre = inv.inventory_in(product_id=product_id, warehouse_id=wh_id, quantity=100)
        assert pre["success"] is True

        # 未确认：返回差异，不改库存
        unconfirmed = inv.inventory_count(
            product_id=product_id,
            warehouse_id=wh_id,
            actual_quantity=120,
            confirmed=False,
        )
        assert unconfirmed["success"] is True
        assert unconfirmed["confirmed"] is False
        assert unconfirmed["data"]["diff"] == 20.0

        with erp_env["test_db"]() as db:
            ledger = (
                db.query(InventoryLedger)
                .filter_by(product_id=product_id, warehouse_id=wh_id)
                .first()
            )
            assert float(ledger.quantity) == 100.0  # 库存未变

        # 确认：库存 = 实盘 120，写一条 count 流水
        confirmed = inv.inventory_count(
            product_id=product_id,
            warehouse_id=wh_id,
            actual_quantity=120,
            confirmed=True,
            operator="tester",
            remark="年末盘点",
        )
        assert confirmed["success"] is True
        assert confirmed["confirmed"] is True
        assert confirmed["data"]["diff"] == 20.0

        with erp_env["test_db"]() as db:
            ledger = (
                db.query(InventoryLedger)
                .filter_by(product_id=product_id, warehouse_id=wh_id)
                .first()
            )
            assert float(ledger.quantity) == 120.0

            txns = (
                db.query(InventoryTransaction)
                .filter_by(
                    product_id=product_id,
                    warehouse_id=wh_id,
                    transaction_type="count",
                )
                .all()
            )
            assert len(txns) == 1
            assert float(txns[0].quantity) == 20.0
            assert float(txns[0].before_quantity) == 100.0
            assert float(txns[0].after_quantity) == 120.0
            assert txns[0].reference_type == "inventory_count"
            assert txns[0].operator == "tester"


# ---------------------------------------------------------------------------
# 链路 3：按 BOM 生产（领料扣原料 → 完工成品+M → 工单 done）
# ---------------------------------------------------------------------------
class TestMRPProductionChain:
    def test_bom_production_full_chain(self, erp_env):
        with erp_env["test_db"]() as db:
            fg = Product(model_number="FG-E2E", name="成品A", unit="个")
            raw1 = Product(model_number="RM1-E2E", name="原料X", unit="个")
            raw2 = Product(model_number="RM2-E2E", name="原料Y", unit="个")
            db.add_all([fg, raw1, raw2])
            db.flush()
            wh = Warehouse(code="WH-PROD", name="生产仓", status="active")
            db.add(wh)
            db.flush()
            now = datetime.now()
            db.add_all(
                [
                    InventoryLedger(
                        product_id=raw1.id,
                        warehouse_id=wh.id,
                        quantity=100,
                        available_quantity=100,
                        reserved_quantity=0,
                        unit="个",
                        in_date=now.date(),
                        created_at=now,
                        updated_at=now,
                    ),
                    InventoryLedger(
                        product_id=raw2.id,
                        warehouse_id=wh.id,
                        quantity=50,
                        available_quantity=50,
                        reserved_quantity=0,
                        unit="个",
                        in_date=now.date(),
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            fg_id, raw1_id, raw2_id, wh_id = fg.id, raw1.id, raw2.id, wh.id

        svc = ManufacturingService()
        bom = svc.create_bom(
            {
                "code": "BOM-E2E",
                "product_id": fg_id,
                "product_name": "成品A",
                "quantity": 1,
                "status": "active",
                "lines": [
                    {"product_id": raw1_id, "product_name": "原料X", "quantity": 2, "unit": "个"},
                    {"product_id": raw2_id, "product_name": "原料Y", "quantity": 1, "unit": "个"},
                ],
            }
        )
        assert bom["success"] is True
        bom_id = bom["data"]["id"]

        order = svc.create_order(
            {"bom_id": bom_id, "quantity": 10, "warehouse_id": wh_id, "order_no": "MO-E2E-01"}
        )
        assert order["success"] is True
        order_id = order["data"]["id"]

        assert svc.confirm_order(order_id)["success"] is True

        consume = svc.consume(order_id, wh_id, operator="tester")
        assert consume["success"] is True
        assert consume["data"]["status"] == "in_progress"

        finish = svc.finish(order_id, wh_id, operator="tester")
        assert finish["success"] is True
        assert finish["data"]["status"] == "done"
        assert finish["inbound"]["quantity"] == 10

        with erp_env["test_db"]() as db:
            fg_ledger = (
                db.query(InventoryLedger).filter_by(product_id=fg_id, warehouse_id=wh_id).first()
            )
            assert float(fg_ledger.available_quantity) == 10  # 成品 +M

            raw1_ledger = (
                db.query(InventoryLedger).filter_by(product_id=raw1_id, warehouse_id=wh_id).first()
            )
            assert float(raw1_ledger.available_quantity) == 80  # 100 - 20

            raw2_ledger = (
                db.query(InventoryLedger).filter_by(product_id=raw2_id, warehouse_id=wh_id).first()
            )
            assert float(raw2_ledger.available_quantity) == 40  # 50 - 10

            order_row = db.query(ManufacturingOrder).filter_by(id=order_id).first()
            assert order_row.status == "done"


# ---------------------------------------------------------------------------
# 链路 4：客户多地址（add_address delivery → get_addresses 关联且类型正确）
# ---------------------------------------------------------------------------
class TestCRMCustomerAddressChain:
    def test_add_and_query_customer_address(self, erp_env, monkeypatch):
        with erp_env["test_db"]() as db:
            customer = Customer(customer_name="客户乙")
            db.add(customer)
            db.commit()
            db.refresh(customer)
            cid = customer.id

        # 将 CustomerApplicationService 的会话固定到共享内存库
        def _session():
            return erp_env["session_factory"]()

        monkeypatch.setattr(CustomerApplicationService, "_get_session", lambda self: _session())
        svc = CustomerApplicationService()

        result = svc.add_address(
            {
                "customer_id": cid,
                "address_type": "delivery",
                "contact_person": "张三",
                "phone": "13800000000",
                "address": "上海市浦东新区XX路1号",
                "is_default": 1,
            }
        )
        assert result["success"] is True
        assert result["data"]["address_type"] == "delivery"
        assert result["data"]["is_default"] == 1

        got = svc.get_addresses(cid)
        assert got["success"] is True
        assert got["count"] == 1
        address = got["data"][0]
        assert address["customer_id"] == cid
        assert address["address_type"] == "delivery"
        assert address["address"] == "上海市浦东新区XX路1号"

        # 直接校验与客户的关联关系
        with erp_env["test_db"]() as db:
            addr_row = db.query(CustomerAddress).filter_by(customer_id=cid).first()
            assert addr_row is not None
            assert addr_row.address_type == "delivery"


# ---------------------------------------------------------------------------
# 链路 5：凭证冲销（反向分录借贷平衡、原凭证标记、重复冲销被拒）
# ---------------------------------------------------------------------------
class TestJournalReverseChain:
    def test_reverse_marks_original_and_rejects_duplicate(self, erp_env):
        original = create_journal_entry(
            {
                "journal_date": date.today(),
                "status": "posted",
                "description": "销售-E2E",
                "reference_type": "sale",
                "reference_id": 1,
                "lines": [
                    {
                        "account_code": "1122",
                        "partner_id": 100,
                        "partner_name": "客户A",
                        "debit": 800.0,
                        "credit": 0,
                    },
                    {"account_code": "6001", "debit": 0, "credit": 800.0},
                ],
            }
        )
        assert original["success"] is True
        original_id = original["data"]["id"]

        rev = journal_entry_reverse(original_id)
        assert rev["success"] is True
        data = rev["data"]
        assert data["balanced"] is True
        assert data["reference_type"] == "reversal"
        assert data["reversed_of_id"] == original_id
        assert data["entry_no"] != original["data"]["entry_no"]
        # 方向反转：原借应收 800 → 冲销贷应收 800；原贷收入 → 冲销借收入
        rev_lines = {l["account_code"]: l for l in data["lines"]}
        assert rev_lines["1122"]["credit"] == 800.0
        assert rev_lines["1122"]["debit"] == 0
        assert rev_lines["6001"]["debit"] == 800.0
        assert rev_lines["6001"]["credit"] == 0

        # 原凭证已标记冲销
        with erp_env["test_db"]() as db:
            orig = db.query(JournalEntry).filter_by(id=original_id).first()
            assert orig.reversed_at is not None

        # 再次冲销被拒
        again = journal_entry_reverse(original_id)
        assert again["success"] is False
        assert "已冲销" in again["message"]
