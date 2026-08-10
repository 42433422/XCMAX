"""W1-06 补货服务测试：基于 InventoryLedger/Product 阈值 + Decimal 精确运算。

验证（业务后置条件）：
1. 低库存口径与库存报表一致：按 ``InventoryLedger.available_quantity`` 聚合，
   缺失台账记录的产品可用量为 0；``min_stock > 0`` 且 ``available < min_stock`` 视为需补货。
2. ``threshold`` 显式指定"可用量 ≤ threshold"即视为需补货。
3. 建议采购量：max_stock > min_stock 时补到 max_stock，否则至少补到 min_stock。
4. 全程 Decimal 精确运算（available_quantity/min_stock/max_stock/suggest_quantity/
   unit_price/suggest_amount），不落 float 域；金额规整到分。
5. ``per_page`` 分页截断。
6. 多租户隔离（tenant 之间互不可见）。
"""

from __future__ import annotations

import contextlib
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.replenishment_service as replenishment_service
from app.db.base import Base
from app.db.models import InventoryLedger, Product, Warehouse
from app.infrastructure.tenant_scope import tenant_scope
from app.services.replenishment_service import suggest_replenishment


@pytest.fixture(scope="function")
def replen_env():
    """共享内存库 + 将 replenishment_service.get_db 指向同一持久会话。"""
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

    with patch.object(replenishment_service, "get_db", test_db):
        yield {"test_db": test_db, "session_factory": session_factory}
    persistent.close()


def _warehouse(db, *, code="WH-1", name="主仓") -> int:
    w = Warehouse(code=code, name=name)
    db.add(w)
    db.flush()
    return w.id


def _product(
    db,
    *,
    model_number: str,
    name: str,
    min_stock: str = "0",
    max_stock: str = "0",
    price: str = "0",
    unit: str = "个",
) -> int:
    p = Product(
        model_number=model_number,
        name=name,
        min_stock=Decimal(min_stock),
        max_stock=Decimal(max_stock),
        price=Decimal(price),
        unit=unit,
        is_active=1,
    )
    db.add(p)
    db.flush()
    return p.id


def _ledger(db, *, product_id: int, warehouse_id: int, available: str) -> None:
    db.add(
        InventoryLedger(
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=Decimal(available),
            available_quantity=Decimal(available),
            reserved_quantity=Decimal("0"),
            unit="个",
        )
    )
    db.flush()


def _build(**overrides) -> dict:
    """调用 suggest_replenishment 的参数默认值。"""
    return {
        "threshold": None,
        "per_page": 50,
        **overrides,
    }


def _by_code(data) -> dict:
    return {d["product_code"]: d for d in data}


# ---------------------------------------------------------------------------
# 1. 低库存口径与库存报表一致（InventoryLedger.available_quantity）
# ---------------------------------------------------------------------------
class TestLowStockCriteria:
    def test_available_below_min_stock_suggests(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(db, model_number="P-1", name="产品A", min_stock="10", max_stock="50")
            _ledger(db, product_id=pid, warehouse_id=wh, available="5")

        result = suggest_replenishment(**_build())
        assert result["success"] is True
        by_code = _by_code(result["data"])
        assert "P-1" in by_code
        assert by_code["P-1"]["suggest_quantity"] == Decimal("45")  # 50 - 5

    def test_available_at_min_stock_not_flagged(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(db, model_number="P-1", name="产品A", min_stock="10", max_stock="50")
            _ledger(db, product_id=pid, warehouse_id=wh, available="10")

        result = suggest_replenishment(**_build())
        assert result["data"] == []

    def test_zero_min_stock_not_flagged(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(db, model_number="P-1", name="产品A", min_stock="0", max_stock="50")
            _ledger(db, product_id=pid, warehouse_id=wh, available="0")

        result = suggest_replenishment(**_build())
        assert result["data"] == []

    def test_no_ledger_row_counts_as_zero_available(self, replen_env):
        with replen_env["test_db"]() as db:
            # 无任何台账记录，但设置 min_stock > 0 → 可用量视为 0，应被标记
            _product(db, model_number="P-1", name="产品A", min_stock="10", max_stock="50")

        result = suggest_replenishment(**_build())
        by_code = _by_code(result["data"])
        assert "P-1" in by_code
        assert by_code["P-1"]["current_quantity"] == Decimal("0")
        assert by_code["P-1"]["suggest_quantity"] == Decimal("50")

    def test_aggregates_across_warehouses(self, replen_env):
        with replen_env["test_db"]() as db:
            wh1 = _warehouse(db, code="WH-1")
            wh2 = _warehouse(db, code="WH-2", name="分仓")
            pid = _product(db, model_number="P-1", name="产品A", min_stock="10", max_stock="50")
            _ledger(db, product_id=pid, warehouse_id=wh1, available="3")
            _ledger(db, product_id=pid, warehouse_id=wh2, available="5")

        result = suggest_replenishment(**_build())
        by_code = _by_code(result["data"])
        assert by_code["P-1"]["current_quantity"] == Decimal("8")
        assert by_code["P-1"]["suggest_quantity"] == Decimal("42")  # 50 - 8


# ---------------------------------------------------------------------------
# 2. threshold 显式口径
# ---------------------------------------------------------------------------
class TestThreshold:
    def test_below_or_equal_threshold_flagged(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(db, model_number="P-1", name="产品A", min_stock="5", max_stock="50")
            _ledger(db, product_id=pid, warehouse_id=wh, available="20")

        # threshold=20：可用量 ≤ 20 即视为需补货
        result = suggest_replenishment(**_build(threshold=20))
        by_code = _by_code(result["data"])
        assert "P-1" in by_code
        assert by_code["P-1"]["suggest_quantity"] == Decimal("30")

    def test_above_threshold_not_flagged(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(db, model_number="P-1", name="产品A", min_stock="5", max_stock="50")
            _ledger(db, product_id=pid, warehouse_id=wh, available="21")

        result = suggest_replenishment(**_build(threshold=20))
        assert result["data"] == []

    def test_threshold_accepts_decimal(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(db, model_number="P-1", name="产品A", min_stock="5", max_stock="50")
            _ledger(db, product_id=pid, warehouse_id=wh, available="7.5")

        result = suggest_replenishment(**_build(threshold=Decimal("7.5")))
        by_code = _by_code(result["data"])
        assert "P-1" in by_code


# ---------------------------------------------------------------------------
# 3. 建议采购量口径（max_stock vs min_stock）
# ---------------------------------------------------------------------------
class TestSuggestQuantity:
    def test_suggests_up_to_max_when_max_gt_min(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(db, model_number="P-1", name="产品A", min_stock="10", max_stock="50")
            _ledger(db, product_id=pid, warehouse_id=wh, available="5")

        result = suggest_replenishment(**_build())
        assert _by_code(result["data"])["P-1"]["suggest_quantity"] == Decimal("45")

    def test_suggests_to_min_when_max_le_min(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(db, model_number="P-1", name="产品A", min_stock="20", max_stock="20")
            _ledger(db, product_id=pid, warehouse_id=wh, available="5")

        result = suggest_replenishment(**_build())
        assert _by_code(result["data"])["P-1"]["suggest_quantity"] == Decimal("15")

    def test_suggest_quantity_never_negative(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(db, model_number="P-1", name="产品A", min_stock="10", max_stock="50")
            _ledger(db, product_id=pid, warehouse_id=wh, available="50")

        # 可用量等于 max_stock，但 min_stock>0 且可用量 ≥ min_stock → 不标记
        result = suggest_replenishment(**_build())
        assert result["data"] == []


# ---------------------------------------------------------------------------
# 4. Decimal 精确运算（不落 float 域）
# ---------------------------------------------------------------------------
class TestDecimalPrecision:
    def test_all_numeric_fields_are_decimal(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(
                db, model_number="P-1", name="产品A", min_stock="10", max_stock="50", price="3.5"
            )
            _ledger(db, product_id=pid, warehouse_id=wh, available="5")

        result = suggest_replenishment(**_build())
        d = _by_code(result["data"])["P-1"]
        assert isinstance(d["current_quantity"], Decimal)
        assert isinstance(d["min_stock"], Decimal)
        assert isinstance(d["max_stock"], Decimal)
        assert isinstance(d["suggest_quantity"], Decimal)
        assert isinstance(d["unit_price"], Decimal)
        assert isinstance(d["suggest_amount"], Decimal)

    def test_fractional_amount_exact(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            pid = _product(
                db, model_number="P-1", name="产品A", min_stock="10", max_stock="50", price="3.5"
            )
            _ledger(db, product_id=pid, warehouse_id=wh, available="5")

        result = suggest_replenishment(**_build())
        d = _by_code(result["data"])["P-1"]
        # 45 × 3.5 = 157.50（Decimal 精确，无 float 残差）
        assert d["suggest_amount"] == Decimal("157.50")

    def test_summary_total_suggest_amount(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            p1 = _product(
                db, model_number="P-1", name="产品A", min_stock="10", max_stock="50", price="3.5"
            )
            _ledger(db, product_id=p1, warehouse_id=wh, available="5")
            p2 = _product(
                db, model_number="P-2", name="产品B", min_stock="10", max_stock="20", price="10"
            )
            _ledger(db, product_id=p2, warehouse_id=wh, available="5")

        result = suggest_replenishment(**_build())
        # 45×3.5=157.50，15×10=150.00 → 307.50
        assert result["summary"]["total_suggest_amount"] == Decimal("307.50")
        assert result["count"] == 2
        assert result["summary"]["total_low_stock"] == 2


# ---------------------------------------------------------------------------
# 5. per_page 分页
# ---------------------------------------------------------------------------
class TestPerPage:
    def test_per_page_truncates(self, replen_env):
        with replen_env["test_db"]() as db:
            wh = _warehouse(db)
            for i in range(1, 6):
                pid = _product(
                    db,
                    model_number=f"P-{i}",
                    name=f"产品{i}",
                    min_stock="10",
                    max_stock="50",
                )
                _ledger(db, product_id=pid, warehouse_id=wh, available="5")

        full = suggest_replenishment(**_build())
        assert full["count"] == 5

        limited = suggest_replenishment(**_build(per_page=2))
        assert limited["count"] == 2
        assert len(limited["data"]) == 2


# ---------------------------------------------------------------------------
# 6. 多租户隔离
# ---------------------------------------------------------------------------
class TestTenantIsolation:
    def test_tenants_are_isolated(self, replen_env):
        with tenant_scope(1):
            with replen_env["test_db"]() as db:
                wh = _warehouse(db, code="WH-T1")
                pid = _product(
                    db, model_number="P-T1", name="租户1产品", min_stock="10", max_stock="50"
                )
                _ledger(db, product_id=pid, warehouse_id=wh, available="5")

        with tenant_scope(2):
            with replen_env["test_db"]() as db:
                wh = _warehouse(db, code="WH-T2")
                pid = _product(
                    db, model_number="P-T2", name="租户2产品", min_stock="10", max_stock="50"
                )
                _ledger(db, product_id=pid, warehouse_id=wh, available="5")

        with tenant_scope(1):
            r1 = suggest_replenishment(**_build())
            assert any(d["product_code"] == "P-T1" for d in r1["data"])
            assert not any(d["product_code"] == "P-T2" for d in r1["data"])

        with tenant_scope(2):
            r2 = suggest_replenishment(**_build())
            assert any(d["product_code"] == "P-T2" for d in r2["data"])
            assert not any(d["product_code"] == "P-T1" for d in r2["data"])
