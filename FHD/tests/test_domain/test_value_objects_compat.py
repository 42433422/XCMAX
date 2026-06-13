"""app/domain/value_objects_compat 单测：金额/数量/订单号/联系方式/价格/型号值对象。

不可变值对象的构造校验、运算、工厂与多行业字段映射，纯逻辑（铁律4）；
覆盖负值/货币不一致/空值/大小写等异常与边界分支（铁律3）。
"""

from __future__ import annotations

import pytest

from app.domain.value_objects_compat import (
    ContactInfo,
    ModelNumber,
    Money,
    OrderNumber,
    Price,
    Quantity,
)


class TestMoney:
    def test_create_and_to_yuan(self):
        m = Money(100.0)
        assert m.currency == "CNY"
        assert m.to_yuan() == 100.0

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="负数"):
            Money(-1.0)

    def test_add_same_currency(self):
        assert (Money(10) + Money(5)).amount == 15

    def test_add_mismatched_currency_raises(self):
        with pytest.raises(ValueError, match="货币单位"):
            Money(10, "CNY") + Money(5, "USD")

    def test_multiply(self):
        assert (Money(10) * 3).amount == 30


class TestQuantity:
    def test_defaults(self):
        q = Quantity()
        assert q.primary == 0
        assert q.secondary == 0.0
        assert q.spec == 10.0

    def test_coating_aliases(self):
        q = Quantity(tins=5, kg=50.0, spec_per_tin=10.0)
        assert q.tins == 5
        assert q.kg == 50.0
        assert q.spec_per_tin == 10.0
        assert q.primary_value == 5
        assert q.secondary_value == 50.0

    def test_negative_primary_raises(self):
        with pytest.raises(ValueError, match="桶数"):
            Quantity(primary=-1)

    def test_negative_secondary_raises(self):
        with pytest.raises(ValueError, match="重量"):
            Quantity(primary=1, secondary=-1)

    def test_labels_and_units_present(self):
        q = Quantity(tins=1)
        assert isinstance(q.primary_label, str)
        assert isinstance(q.secondary_label, str)
        assert isinstance(q.spec_label, str)
        assert isinstance(q.primary_unit, str)
        assert isinstance(q.secondary_unit, str)

    def test_repr_contains_values(self):
        assert "Quantity(" in repr(Quantity(tins=3, kg=30.0))

    def test_equality_and_hash(self):
        a = Quantity(tins=2, kg=20.0)
        b = Quantity(tins=2, kg=20.0)
        c = Quantity(tins=3, kg=20.0)
        assert a == b
        assert a != c
        assert a != "not-a-quantity"
        assert hash(a) == hash(b)

    def test_to_dict_keys(self):
        d = Quantity(tins=2, kg=20.0).to_dict()
        assert d  # 至少包含 3 个行业字段
        assert len(d) == 3

    def test_to_industry_dict(self):
        d = Quantity(tins=2, kg=20.0).to_industry_dict()
        assert d["primary"] == 2
        assert "primary_label" in d and "spec_label" in d

    def test_from_tins_and_spec(self):
        q = Quantity.from_tins_and_spec(4, 10.0)
        assert q.primary == 4
        assert q.secondary == 40.0

    def test_from_primary_and_spec(self):
        q = Quantity.from_primary_and_spec(3, 5.0)
        assert q.primary == 3
        assert q.secondary >= 0

    def test_from_dict_with_coating_fields(self):
        q = Quantity.from_dict({"tins": 6, "kg": 60.0, "spec_per_tin": 10.0})
        assert q.primary == 6
        assert q.secondary == 60.0

    def test_from_dict_with_generic_fallback(self):
        q = Quantity.from_dict({"primary": 2, "secondary": 8.0, "spec": 4.0})
        assert q.primary == 2


class TestOrderNumber:
    def test_empty_raises(self):
        with pytest.raises(ValueError, match="订单号"):
            OrderNumber("")

    def test_str(self):
        assert str(OrderNumber("X1")) == "X1"

    def test_generate_is_timestamp_like(self):
        n = OrderNumber.generate()
        assert n.value.isdigit()
        assert len(n.value) == 14


class TestContactInfo:
    def test_create(self):
        c = ContactInfo(person="张三", phone="123", address="A")
        assert c.person == "张三"
        assert c.address == "A"

    def test_empty(self):
        c = ContactInfo.empty()
        assert c.person == ""
        assert c.phone == ""
        assert c.address is None


class TestPrice:
    def test_negative_unit_price_raises(self):
        with pytest.raises(ValueError, match="单价"):
            Price(-1.0)

    def test_discount_rate_out_of_range_raises(self):
        with pytest.raises(ValueError, match="折扣率"):
            Price(10.0, discount_rate=1.5)

    def test_final_price(self):
        assert Price(100.0, 0.8).final_price() == pytest.approx(80.0)

    def test_calculate_amount_uses_kg(self):
        amount = Price(10.0, 1.0).calculate_amount(Quantity(tins=1, kg=5.0))
        assert amount == pytest.approx(50.0)


class TestModelNumber:
    def test_empty_raises(self):
        with pytest.raises(ValueError, match="型号"):
            ModelNumber("")

    def test_str(self):
        assert str(ModelNumber("ABC")) == "ABC"

    def test_matches_case_insensitive(self):
        assert ModelNumber("Abc").matches(ModelNumber("aBC")) is True
        assert ModelNumber("Abc").matches(ModelNumber("xyz")) is False

    def test_contains_case_insensitive(self):
        assert ModelNumber("Hello-World").contains("world") is True
        assert ModelNumber("Hello").contains("zzz") is False
