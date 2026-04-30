"""领域值对象测试（与当前 app.domain.value_objects 实现一致）。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.value_objects import (
    Address,
    ContactInfo,
    Currency,
    ModelNumber,
    Money,
    OrderNumber,
    Price,
    Quantity,
    UnitOfMeasure,
)


class TestMoney:
    def test_create_money_with_positive_amount(self):
        money = Money.from_float(100.0, Currency.CNY)
        assert money.amount == Decimal("100.00")
        assert money.currency == Currency.CNY

    def test_create_money_with_zero(self):
        money = Money.zero(Currency.CNY)
        assert money.amount == Decimal("0")

    def test_create_money_with_negative_raises_error(self):
        with pytest.raises(ValueError, match="金额不能为负数"):
            Money(Decimal("-50"), Currency.CNY)

    def test_money_addition(self):
        m1 = Money.from_float(100.0, Currency.CNY)
        m2 = Money.from_float(50.0, Currency.CNY)
        result = m1 + m2
        assert result.amount == Decimal("150.00")
        assert result.currency == Currency.CNY

    def test_money_addition_different_currency_raises_error(self):
        m1 = Money.from_float(100.0, Currency.CNY)
        m2 = Money.from_float(50.0, Currency.USD)
        with pytest.raises(ValueError):
            m1 + m2

    def test_money_multiplication(self):
        money = Money.from_float(100.0, Currency.CNY)
        result = money * 2
        assert result.amount == Decimal("200.00")

    def test_money_to_yuan_not_applicable_use_float(self):
        money = Money.from_float(100.5, Currency.CNY)
        assert float(money.amount) == 100.5

    def test_money_immutability(self):
        m1 = Money.from_float(100.0, Currency.CNY)
        m2 = m1 + Money.from_float(50.0, Currency.CNY)
        assert m1.amount == Decimal("100.00")
        assert m2.amount == Decimal("150.00")


class TestQuantity:
    def test_create_quantity(self):
        q = Quantity.from_float(50.0, UnitOfMeasure.KG)
        assert q.value == Decimal("50.000")
        assert q.unit == UnitOfMeasure.KG

    def test_quantity_add_same_unit(self):
        q1 = Quantity.from_float(3.0, UnitOfMeasure.KG)
        q2 = Quantity.from_float(2.0, UnitOfMeasure.KG)
        assert (q1 + q2).value == Decimal("5.000")

    def test_quantity_subtract_would_go_negative_raises(self):
        q1 = Quantity.from_float(1.0, UnitOfMeasure.KG)
        q2 = Quantity.from_float(5.0, UnitOfMeasure.KG)
        with pytest.raises(ValueError, match="negative"):
            q1 - q2


class TestOrderNumber:
    def test_create_order_number(self):
        order_num = OrderNumber(value="ORD20260321001")
        assert order_num.value == "ORD20260321001"

    def test_generate_order_number(self):
        order_num = OrderNumber.generate()
        assert order_num.value.startswith("SO-")
        assert len(order_num.value) == 15

    def test_empty_order_number_raises_error(self):
        with pytest.raises(ValueError, match="订单号不能为空"):
            OrderNumber(value="")

    def test_order_number_str(self):
        order_num = OrderNumber(value="ORD001")
        assert str(order_num) == "ORD001"


class TestContactInfo:
    def test_create_contact_info(self):
        contact = ContactInfo(name="张三", phone="13800138000", address=None, company=None)
        assert contact.name == "张三"
        assert contact.phone == "13800138000"

    def test_contact_info_minimal(self):
        contact = ContactInfo(name="")
        assert contact.name == ""
        assert contact.phone is None

    def test_contact_info_immutability(self):
        contact = ContactInfo(name="张三", phone="13800138000")
        with pytest.raises(Exception):
            contact.name = "李四"  # type: ignore[misc]


class TestPrice:
    def test_create_price(self):
        price = Price(unit_price=100.0)
        assert price.unit_price == 100.0
        assert price.discount_rate == 1.0

    def test_create_price_with_discount(self):
        price = Price(unit_price=100.0, discount_rate=0.8)
        assert price.unit_price == 100.0
        assert price.discount_rate == 0.8

    def test_negative_price_raises_error(self):
        with pytest.raises(ValueError, match="单价不能为负数"):
            Price(unit_price=-10.0)

    def test_invalid_discount_rate_raises_error(self):
        with pytest.raises(ValueError, match="折扣率必须在 0-1 之间"):
            Price(unit_price=100.0, discount_rate=1.5)

    def test_final_price(self):
        price = Price(unit_price=100.0, discount_rate=0.9)
        assert price.final_price() == 90.0

    def test_calculate_amount(self):
        price = Price(unit_price=10.0, discount_rate=1.0)
        quantity = Quantity.from_float(50.0, UnitOfMeasure.KG)
        assert price.calculate_amount(quantity) == 500.0


class TestModelNumber:
    def test_create_model_number(self):
        model = ModelNumber(value="9803")
        assert model.value == "9803"

    def test_empty_model_number_raises_error(self):
        with pytest.raises(ValueError, match="型号不能为空"):
            ModelNumber(value="")

    def test_model_number_matches_case_insensitive(self):
        m1 = ModelNumber(value="ABC123")
        m2 = ModelNumber(value="abc123")
        assert m1.matches(m2) is True

    def test_model_number_not_matches(self):
        m1 = ModelNumber(value="ABC123")
        m2 = ModelNumber(value="DEF456")
        assert m1.matches(m2) is False

    def test_model_number_contains(self):
        model = ModelNumber(value="ABC-9803-XYZ")
        assert model.contains("9803") is True
        assert model.contains("abc") is True
        assert model.contains("1234") is False

    def test_model_number_str(self):
        model = ModelNumber(value="9803")
        assert str(model) == "9803"


class TestAddress:
    def test_address_round_trip(self):
        a = Address(province="粤", city="深圳", district="南山")
        assert "深圳" in a.to_short_string()
