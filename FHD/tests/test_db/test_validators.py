"""app/db/validators 单测：ModelValidators 静态校验 + 注册入口。

纯逻辑（正则/类型/边界），无 DB 连接（铁律4）；覆盖 None/空/超长/非法分支（铁律3）。
"""

from __future__ import annotations

import pytest

from app.db.validators import (
    ModelValidators,
    _register_customer_validators,
    _register_material_validators,
    _register_product_validators,
    _register_purchase_unit_validators,
    _register_shipment_validators,
    register_model_validators,
)


class TestPositiveNumber:
    def test_none_returns_none(self):
        assert ModelValidators.validate_positive_number(None, "x") is None

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError, match="有效数字"):
            ModelValidators.validate_positive_number("abc", "金额")

    def test_allow_zero_accepts_zero(self):
        assert ModelValidators.validate_positive_number(0, "金额") == 0

    def test_allow_zero_rejects_negative(self):
        with pytest.raises(ValueError, match="非负数"):
            ModelValidators.validate_positive_number(-1, "金额")

    def test_disallow_zero_rejects_zero(self):
        with pytest.raises(ValueError, match="正数"):
            ModelValidators.validate_positive_number(0, "重量", allow_zero=False)

    def test_disallow_zero_accepts_positive(self):
        assert ModelValidators.validate_positive_number(5, "重量", allow_zero=False) == 5

    def test_returns_original_value_type(self):
        assert ModelValidators.validate_positive_number("3.5", "v") == "3.5"


class TestNonEmptyString:
    def test_none_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            ModelValidators.validate_non_empty_string(None, "名称")

    def test_blank_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            ModelValidators.validate_non_empty_string("   ", "名称")

    def test_strips_value(self):
        assert ModelValidators.validate_non_empty_string("  hi  ", "名称") == "hi"

    def test_max_length_exceeded(self):
        with pytest.raises(ValueError, match="不能超过"):
            ModelValidators.validate_non_empty_string("abcd", "名称", max_length=3)

    def test_within_max_length(self):
        assert ModelValidators.validate_non_empty_string("abc", "名称", max_length=3) == "abc"


class TestPhone:
    def test_empty_passthrough(self):
        assert ModelValidators.validate_phone("") == ""
        assert ModelValidators.validate_phone(None) is None

    def test_valid_phone(self):
        assert ModelValidators.validate_phone("+86 (010)-1234567") == "+86 (010)-1234567"

    def test_invalid_phone(self):
        with pytest.raises(ValueError, match="电话号码"):
            ModelValidators.validate_phone("abc")


class TestEmail:
    def test_empty_passthrough(self):
        assert ModelValidators.validate_email("") == ""

    def test_valid_email(self):
        assert ModelValidators.validate_email("a.b+c@example.co") == "a.b+c@example.co"

    def test_invalid_email(self):
        with pytest.raises(ValueError, match="邮箱"):
            ModelValidators.validate_email("not-an-email")


class TestRegistration:
    def test_register_model_validators_returns_bool(self):
        assert isinstance(register_model_validators(), bool)

    def test_register_helpers_are_callable(self):
        dummy = type("Dummy", (), {})
        for fn in (
            _register_product_validators,
            _register_purchase_unit_validators,
            _register_customer_validators,
            _register_material_validators,
            _register_shipment_validators,
        ):
            assert fn(dummy) is None
