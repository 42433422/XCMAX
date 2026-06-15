"""app/domain/value_objects 包单测：Money/Percentage/Email/Phone/Address/DateRange 等。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.domain.value_objects import (
    Address,
    ContactInfo,
    Currency,
    DateRange,
    Email,
    Money,
    Percentage,
    PhoneNumber,
)


class TestMoney:
    def test_from_float_and_arithmetic(self):
        a = Money.from_float(10.5)
        b = Money.from_float(2.5)
        assert (a + b).amount == Decimal("13.00")
        assert (a * 2).amount == Decimal("21.00")
        assert a.divide(2).amount == Decimal("5.25")

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="负数"):
            Money(Decimal("-1"), Currency.CNY)

    def test_currency_mismatch(self):
        with pytest.raises(ValueError, match="Cannot add"):
            Money.zero(Currency.CNY) + Money.zero(Currency.USD)

    def test_divide_by_zero(self):
        with pytest.raises(ValueError, match="zero"):
            Money.zero().divide(0)

    def test_compare_and_dict_roundtrip(self):
        m = Money.from_string("12.34", "CNY")
        other = Money.from_string("12.34", "CNY")
        assert m.compare_to(other) == 0
        assert m.greater_than_or_equal(other)
        assert Money.from_dict(m.to_dict()).amount == m.amount


class TestPercentage:
    def test_fraction_and_apply(self):
        p = Percentage.from_float(10)
        assert p.as_fraction == Decimal("0.1")
        assert p.apply_to(Decimal("200")) == Decimal("20")

    def test_subtract_negative_raises(self):
        with pytest.raises(ValueError, match="negative"):
            Percentage(5).subtract(Percentage(10))

    def test_display_and_dict(self):
        p = Percentage(25)
        assert p.as_display_string == "25%"
        assert Percentage.from_dict(p.to_dict()).value == p.value


class TestEmail:
    def test_valid_email(self):
        e = Email("User@Example.COM")
        assert e.address == "user@example.com"
        assert e.domain == "example.com"
        assert e.local_part == "user"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid email"):
            Email("not-email")

    def test_is_valid(self):
        assert Email.is_valid("a@b.co") is True
        assert Email.is_valid("") is False


class TestPhoneNumber:
    def test_mobile_format_and_mask(self):
        p = PhoneNumber("138-1234-5678")
        assert p.is_mobile is True
        assert p.formatted == "138-1234-5678"
        assert "****" in p.masked

    def test_invalid_length_raises(self):
        with pytest.raises(ValueError, match="Invalid phone"):
            PhoneNumber("123")

    def test_is_valid(self):
        assert PhoneNumber.is_valid("13812345678") is True
        assert PhoneNumber.is_valid("") is False


class TestAddress:
    def test_from_string_and_full(self):
        a = Address.from_string("四川 成都")
        assert a.province == "四川"
        assert "成都" in a.to_full_string()

    def test_dict_roundtrip(self):
        a = Address(province="浙", city="杭", district="西")
        assert Address.from_dict(a.to_dict()) == a


class TestContactInfoPackage:
    def test_to_dict_with_address(self):
        c = ContactInfo(
            name="张三",
            phone="13812345678",
            address=Address(province="沪", city="上海"),
        )
        d = c.to_dict()
        assert d["name"] == "张三"
        assert ContactInfo.from_dict(d).name == "张三"


class TestDateRange:
    def test_invalid_range_raises(self):
        with pytest.raises(ValueError, match="cannot be before"):
            DateRange(date(2026, 6, 10), date(2026, 6, 1))

    def test_from_datetime_and_contains(self):
        dr = DateRange.from_datetime(datetime(2026, 6, 1), datetime(2026, 6, 5))
        assert dr.contains(date(2026, 6, 3))
        assert dr.days == 5

    def test_overlap_intersection_union(self):
        a = DateRange(date(2026, 6, 1), date(2026, 6, 10))
        b = DateRange(date(2026, 6, 5), date(2026, 6, 15))
        assert a.overlaps(b)
        inter = a.intersection(b)
        assert inter and inter.start == date(2026, 6, 5)
        assert a.union(b).start == date(2026, 6, 1)

    def test_no_overlap_intersection_none(self):
        a = DateRange(date(2026, 6, 1), date(2026, 6, 3))
        b = DateRange(date(2026, 6, 10), date(2026, 6, 12))
        assert not a.overlaps(b)
        assert a.intersection(b) is None

    def test_extend_shift_split(self):
        dr = DateRange(date(2026, 6, 1), date(2026, 6, 3))
        assert dr.extend(2).end == date(2026, 6, 5)
        assert dr.shift(1).start == date(2026, 6, 2)
        parts = DateRange(date(2026, 5, 28), date(2026, 6, 2)).split_by_month()
        assert len(parts) >= 1

    def test_factory_methods(self):
        assert DateRange.today().is_single_day
        assert DateRange.last_n_days(3).days == 3
        assert len(DateRange.this_week()) >= 1
