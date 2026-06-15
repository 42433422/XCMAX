"""测试 quantity 值对象 - 数量和计量单位。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.value_objects.quantity import Quantity, UnitOfMeasure


class TestUnitOfMeasure:
    """测试计量单位枚举。"""

    def test_weight_units(self):
        assert UnitOfMeasure.KG.value == "kg"
        assert UnitOfMeasure.G.value == "g"
        assert UnitOfMeasure.TON.value == "ton"

    def test_volume_units(self):
        assert UnitOfMeasure.LITER.value == "L"
        assert UnitOfMeasure.ML.value == "ml"

    def test_count_units(self):
        assert UnitOfMeasure.PIECE.value == "pcs"
        assert UnitOfMeasure.BOX.value == "box"
        assert UnitOfMeasure.BUCKET.value == "bucket"

    def test_length_units(self):
        assert UnitOfMeasure.METER.value == "m"
        assert UnitOfMeasure.CENTIMETER.value == "cm"


class TestQuantityInit:
    """测试 Quantity 初始化。"""

    def test_create_with_decimal(self):
        q = Quantity(Decimal("100"), UnitOfMeasure.KG)
        assert q.value == Decimal("100.000")
        assert q.unit == UnitOfMeasure.KG

    def test_create_with_float(self):
        q = Quantity(1.5, UnitOfMeasure.KG)
        assert q.value == Decimal("1.500")

    def test_create_with_int(self):
        q = Quantity(10, UnitOfMeasure.PIECE)
        assert q.value == Decimal("10.000")

    def test_create_with_string(self):
        q = Quantity(Decimal("3.14"), UnitOfMeasure.LITER)
        assert q.value == Decimal("3.140")

    def test_precision_rounding(self):
        q = Quantity(Decimal("1.2345"), UnitOfMeasure.KG)
        assert q.value == Decimal("1.235")  # ROUND_HALF_UP


class TestQuantityFactoryMethods:
    """测试工厂方法。"""

    def test_from_float(self):
        q = Quantity.from_float(2.5, UnitOfMeasure.KG)
        assert q.value == Decimal("2.500")
        assert q.unit == UnitOfMeasure.KG

    def test_from_int(self):
        q = Quantity.from_int(5, UnitOfMeasure.PIECE)
        assert q.value == Decimal("5.000")

    def test_zero(self):
        q = Quantity.zero()
        assert q.is_zero()
        assert q.unit == UnitOfMeasure.PIECE

    def test_zero_with_unit(self):
        q = Quantity.zero(UnitOfMeasure.KG)
        assert q.is_zero()
        assert q.unit == UnitOfMeasure.KG


class TestQuantityArithmetic:
    """测试算术运算。"""

    def test_add_same_unit(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("5"), UnitOfMeasure.KG)
        result = a.add(b)
        assert result.value == Decimal("15.000")

    def test_add_different_unit_raises(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("5"), UnitOfMeasure.PIECE)
        with pytest.raises(ValueError, match="Cannot add"):
            a.add(b)

    def test_subtract_same_unit(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("3"), UnitOfMeasure.KG)
        result = a.subtract(b)
        assert result.value == Decimal("7.000")

    def test_subtract_negative_result_raises(self):
        a = Quantity(Decimal("3"), UnitOfMeasure.KG)
        b = Quantity(Decimal("10"), UnitOfMeasure.KG)
        with pytest.raises(ValueError, match="negative"):
            a.subtract(b)

    def test_subtract_different_unit_raises(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("3"), UnitOfMeasure.LITER)
        with pytest.raises(ValueError, match="Cannot subtract"):
            a.subtract(b)

    def test_multiply(self):
        q = Quantity(Decimal("10"), UnitOfMeasure.KG)
        result = q.multiply(3)
        assert result.value == Decimal("30.000")

    def test_multiply_float(self):
        q = Quantity(Decimal("10"), UnitOfMeasure.KG)
        result = q.multiply(2.5)
        assert result.value == Decimal("25.000")

    def test_divide(self):
        q = Quantity(Decimal("10"), UnitOfMeasure.KG)
        result = q.divide(2)
        assert result.value == Decimal("5.000")

    def test_divide_by_zero_raises(self):
        q = Quantity(Decimal("10"), UnitOfMeasure.KG)
        with pytest.raises(ValueError, match="divide by zero"):
            q.divide(0)


class TestQuantityUnitConversion:
    """测试单位转换。"""

    def test_same_unit_returns_self(self):
        q = Quantity(Decimal("10"), UnitOfMeasure.KG)
        result = q.to_unit(UnitOfMeasure.KG)
        assert result is q

    def test_kg_to_g(self):
        q = Quantity(Decimal("1"), UnitOfMeasure.KG)
        result = q.to_unit(UnitOfMeasure.G)
        assert result.value == Decimal("1000.000")
        assert result.unit == UnitOfMeasure.G

    def test_g_to_kg(self):
        q = Quantity(Decimal("500"), UnitOfMeasure.G)
        result = q.to_unit(UnitOfMeasure.KG)
        assert result.value == Decimal("0.500")

    def test_kg_to_ton(self):
        q = Quantity(Decimal("1000"), UnitOfMeasure.KG)
        result = q.to_unit(UnitOfMeasure.TON)
        assert result.value == Decimal("1.000")

    def test_ton_to_kg(self):
        q = Quantity(Decimal("1"), UnitOfMeasure.TON)
        result = q.to_unit(UnitOfMeasure.KG)
        assert result.value == Decimal("1000.000")

    def test_ml_to_liter(self):
        q = Quantity(Decimal("500"), UnitOfMeasure.ML)
        result = q.to_unit(UnitOfMeasure.LITER)
        assert result.value == Decimal("0.500")

    def test_liter_to_ml(self):
        q = Quantity(Decimal("1"), UnitOfMeasure.LITER)
        result = q.to_unit(UnitOfMeasure.ML)
        assert result.value == Decimal("1000.000")

    def test_cm_to_m(self):
        q = Quantity(Decimal("100"), UnitOfMeasure.CENTIMETER)
        result = q.to_unit(UnitOfMeasure.METER)
        assert result.value == Decimal("1.000")

    def test_m_to_cm(self):
        q = Quantity(Decimal("1"), UnitOfMeasure.METER)
        result = q.to_unit(UnitOfMeasure.CENTIMETER)
        assert result.value == Decimal("100.000")

    def test_unsupported_conversion_raises(self):
        q = Quantity(Decimal("10"), UnitOfMeasure.KG)
        with pytest.raises(ValueError, match="Cannot convert"):
            q.to_unit(UnitOfMeasure.PIECE)


class TestQuantityComparison:
    """测试比较操作。"""

    def test_is_zero(self):
        assert Quantity.zero().is_zero() is True
        assert Quantity(Decimal("1"), UnitOfMeasure.KG).is_zero() is False

    def test_is_positive(self):
        assert Quantity(Decimal("1"), UnitOfMeasure.KG).is_positive() is True
        assert Quantity.zero().is_positive() is False

    def test_greater_than(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("5"), UnitOfMeasure.KG)
        assert a.greater_than(b) is True
        assert b.greater_than(a) is False

    def test_greater_than_different_unit_raises(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("5"), UnitOfMeasure.LITER)
        with pytest.raises(ValueError, match="Cannot compare"):
            a.greater_than(b)

    def test_less_than(self):
        a = Quantity(Decimal("5"), UnitOfMeasure.KG)
        b = Quantity(Decimal("10"), UnitOfMeasure.KG)
        assert a.less_than(b) is True

    def test_greater_than_or_equal(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("10"), UnitOfMeasure.KG)
        assert a.greater_than_or_equal(b) is True

    def test_less_than_or_equal(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("10"), UnitOfMeasure.KG)
        assert a.less_than_or_equal(b) is True


class TestQuantitySerialization:
    """测试序列化。"""

    def test_to_dict(self):
        q = Quantity(Decimal("10.5"), UnitOfMeasure.KG)
        d = q.to_dict()
        assert d["value"] == 10.5
        assert d["unit"] == "kg"

    def test_from_dict(self):
        d = {"value": 10.5, "unit": "kg"}
        q = Quantity.from_dict(d)
        assert q.value == Decimal("10.500")
        assert q.unit == UnitOfMeasure.KG

    def test_roundtrip(self):
        q = Quantity(Decimal("42.5"), UnitOfMeasure.LITER)
        d = q.to_dict()
        restored = Quantity.from_dict(d)
        assert restored.value == q.value
        assert restored.unit == q.unit

    def test_from_dict_default_unit(self):
        d = {"value": 5}
        q = Quantity.from_dict(d)
        assert q.unit == UnitOfMeasure.PIECE


class TestQuantityOperators:
    """测试运算符重载。"""

    def test_add_operator(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("5"), UnitOfMeasure.KG)
        result = a + b
        assert result.value == Decimal("15.000")

    def test_sub_operator(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("3"), UnitOfMeasure.KG)
        result = a - b
        assert result.value == Decimal("7.000")

    def test_mul_operator(self):
        q = Quantity(Decimal("10"), UnitOfMeasure.KG)
        result = q * 3
        assert result.value == Decimal("30.000")

    def test_div_operator(self):
        q = Quantity(Decimal("10"), UnitOfMeasure.KG)
        result = q / 2
        assert result.value == Decimal("5.000")

    def test_eq_operator(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("10"), UnitOfMeasure.KG)
        assert a == b

    def test_eq_different_unit(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("10"), UnitOfMeasure.LITER)
        assert a != b

    def test_eq_non_quantity(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        assert a != "not a quantity"

    def test_hash(self):
        a = Quantity(Decimal("10"), UnitOfMeasure.KG)
        b = Quantity(Decimal("10"), UnitOfMeasure.KG)
        assert hash(a) == hash(b)

    def test_str(self):
        q = Quantity(Decimal("10.5"), UnitOfMeasure.KG)
        assert "10.5" in str(q)
        assert "kg" in str(q)

    def test_repr(self):
        q = Quantity(Decimal("10"), UnitOfMeasure.KG)
        assert "Quantity" in repr(q)
