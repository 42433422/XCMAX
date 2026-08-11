"""Tests for app.services.uom_service (W1-06 UOM 换算服务).

覆盖 W1-06 后置条件：
  - 同一产品多单位 + 换算率（category 内单位表 + 产品自身 unit 兜底）；
  - Decimal 精确换算："10 箱 × 20 斤/箱 = 200 斤"，数量与金额一致；
  - 未知单位 / 多单位字面量 → 返回澄清要求，而非按默认单位执行。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import Product, UomCategory, UomUnit
from app.services.uom_service import UomConversionError, UomService


@pytest.fixture(scope="function")
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def weight_units(db):
    """weight 类别：斤(基准 factor=1) + 箱(factor=20)。"""
    cat = UomCategory(code="weight", name="重量")
    db.add(cat)
    db.flush()
    jin = UomUnit(category_id=cat.id, code="斤", name="斤", factor=Decimal("1"), is_reference=1)
    box = UomUnit(category_id=cat.id, code="箱", name="箱", factor=Decimal("20"), is_reference=0)
    db.add_all([jin, box])
    db.commit()
    return cat


def _product(db, *, unit="斤", uom_category="weight") -> Product:
    p = Product(
        name="测试产品",
        unit=unit,
        uom_category=uom_category,
        uom_factor=Decimal("1"),
    )
    db.add(p)
    db.commit()
    return p


# ---------------------------------------------------------------------------
# 纯函数换算核心
# ---------------------------------------------------------------------------
class TestConvertCore:
    def test_ten_boxes_equal_two_hundred_jin(self):
        svc = UomService()
        # 10 箱 × 20 斤/箱 = 200 斤
        assert svc.convert(10, 20, 1) == Decimal("200")

    def test_decimal_exact_roundtrip(self):
        svc = UomService()
        boxes_to_jin = svc.convert(Decimal("10"), Decimal("20"), Decimal("1"))
        assert boxes_to_jin == Decimal("200")
        # 反向：200 斤 → 箱 = 10
        assert svc.convert(Decimal("200"), Decimal("1"), Decimal("20")) == Decimal("10")

    def test_non_positive_factor_rejected(self):
        svc = UomService()
        with pytest.raises(UomConversionError):
            svc.convert(10, 0, 1)
        with pytest.raises(UomConversionError):
            svc.convert(10, 1, -2)

    def test_quantity_is_optional_string(self):
        svc = UomService()
        assert svc.convert("7.5", "20", "1") == Decimal("150")


# ---------------------------------------------------------------------------
# 多单位换算（DB-backed product）
# ---------------------------------------------------------------------------
class TestProductMultiUnit:
    def test_loads_category_units(self, db, weight_units):
        product = _product(db)
        units = UomService(db=db).get_product_units(product)
        assert units == {"斤": Decimal("1"), "箱": Decimal("20")}

    def test_convert_via_product(self, db, weight_units):
        product = _product(db)
        svc = UomService(db=db)
        assert svc.convert_quantity(10, "箱", "斤", product=product) == Decimal("200")

    def test_unknown_unit_raises_not_default(self, db, weight_units):
        product = _product(db)
        svc = UomService(db=db)
        with pytest.raises(UomConversionError):
            svc.convert_quantity(10, "吨", "斤", product=product)

    def test_product_without_category_falls_back_to_own_unit(self, db):
        product = _product(db, uom_category=None)
        units = UomService(db=db).get_product_units(product)
        assert units == {"斤": Decimal("1")}

    def test_convert_quantity_accepts_injected_units(self):
        svc = UomService()
        units = {"斤": Decimal("1"), "箱": Decimal("20")}
        assert svc.convert_quantity(3, "箱", "斤", units=units) == Decimal("60")


# ---------------------------------------------------------------------------
# 数量/金额一致性
# ---------------------------------------------------------------------------
class TestAmountConsistency:
    def test_amount_after_conversion(self, db, weight_units):
        product = _product(db)
        svc = UomService(db=db)
        # 10 箱，按 斤 计价 20 元/斤 → 200 斤 × 20 = 4000
        result = svc.convert_amount(10, "箱", "斤", Decimal("20"), product=product)
        assert result["quantity"] == Decimal("200")
        assert result["unit"] == "斤"
        assert result["amount"] == Decimal("4000.00")

    def test_amount_consistency_box_vs_jin(self, db, weight_units):
        """按箱计价与按斤计价金额一致（乘法结合律）：10箱×(20斤/箱×20元/斤)=4000。"""
        product = _product(db)
        svc = UomService(db=db)
        per_jin = svc.convert_amount(10, "箱", "斤", Decimal("20"), product=product)["amount"]
        per_box = svc.convert_amount(10, "箱", "箱", Decimal("400"), product=product)["amount"]
        assert per_jin == per_box == Decimal("4000.00")


# ---------------------------------------------------------------------------
# 自然语言歧义 → 澄清（而非按默认单位执行）
# ---------------------------------------------------------------------------
class TestResolveClarification:
    def test_unknown_unit_requests_clarification(self, db, weight_units):
        product = _product(db)
        result = UomService(db=db).resolve_quantity_unit("出 500 吨", product=product)
        assert result["requires_clarification"] is True
        assert result["reason"] == "unknown_unit"

    def test_multiple_units_requests_clarification(self, db, weight_units):
        product = _product(db)
        result = UomService(db=db).resolve_quantity_unit("出 5 箱 100 斤", product=product)
        assert result["requires_clarification"] is True
        assert result["reason"] == "ambiguous_unit"

    def test_missing_unit_requests_clarification(self, db, weight_units):
        product = _product(db)
        result = UomService(db=db).resolve_quantity_unit("出 500", product=product)
        assert result["requires_clarification"] is True
        assert result["reason"] == "missing_unit"

    def test_empty_requests_clarification(self, db, weight_units):
        product = _product(db)
        result = UomService(db=db).resolve_quantity_unit("", product=product)
        assert result["requires_clarification"] is True
        assert result["reason"] == "missing_quantity"

    def test_known_unit_resolves(self, db, weight_units):
        product = _product(db)
        result = UomService(db=db).resolve_quantity_unit("出 500 斤", product=product)
        assert result["requires_clarification"] is False
        assert result["quantity"] == Decimal("500")
        assert result["unit"] == "斤"
