"""Tests for app.db.validators — coverage ramp C3.2-a.

Covers:
* ``ModelValidators.validate_positive_number`` (allow_zero True/False, None, types)
* ``ModelValidators.validate_non_empty_string`` (None, empty, whitespace, max_length)
* ``ModelValidators.validate_phone`` (empty passthrough, valid/invalid formats)
* ``ModelValidators.validate_email`` (empty passthrough, valid/invalid formats)
* ``register_model_validators`` success and exception paths
"""

from __future__ import annotations

import pytest

from app.db.validators import ModelValidators, register_model_validators


class TestValidatePositiveNumber:
    def test_none_returns_none(self) -> None:
        assert ModelValidators.validate_positive_number(None, "x", allow_zero=True) is None

    def test_zero_allowed_when_allow_zero_true(self) -> None:
        assert ModelValidators.validate_positive_number(0, "x", allow_zero=True) == 0

    def test_zero_rejected_when_allow_zero_false(self) -> None:
        with pytest.raises(ValueError, match="x 必须为正数"):
            ModelValidators.validate_positive_number(0, "x", allow_zero=False)

    def test_positive_int_passes(self) -> None:
        assert ModelValidators.validate_positive_number(5, "x") == 5

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="x 必须为非负数"):
            ModelValidators.validate_positive_number(-1, "x", allow_zero=True)

    def test_string_numeric_passes_through(self) -> None:
        assert ModelValidators.validate_positive_number("3.14", "x") == "3.14"

    def test_non_numeric_string_raises_validation_error(self) -> None:
        with pytest.raises(ValueError, match="x 必须是有效数字"):
            ModelValidators.validate_positive_number("abc", "x", allow_zero=True)


class TestValidateNonEmptyString:
    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="x 不能为空"):
            ModelValidators.validate_non_empty_string(None, "x")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="x 不能为空"):
            ModelValidators.validate_non_empty_string("", "x")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="x 不能为空"):
            ModelValidators.validate_non_empty_string("   ", "x")

    def test_simple_string_passes(self) -> None:
        assert ModelValidators.validate_non_empty_string("hello", "x") == "hello"

    def test_string_is_stripped(self) -> None:
        assert ModelValidators.validate_non_empty_string("  hello  ", "x") == "hello"

    def test_exceeds_max_length_raises(self) -> None:
        with pytest.raises(ValueError, match="x 不能超过 5 个字符"):
            ModelValidators.validate_non_empty_string("abcdef", "x", max_length=5)

    def test_at_max_length_passes(self) -> None:
        assert ModelValidators.validate_non_empty_string("abcde", "x", max_length=5) == "abcde"

    def test_non_string_input_is_coerced(self) -> None:
        assert ModelValidators.validate_non_empty_string(123, "x") == "123"


class TestValidatePhone:
    def test_empty_returns_value(self) -> None:
        assert ModelValidators.validate_phone("") == ""
        assert ModelValidators.validate_phone(None) is None

    def test_valid_chinese_mobile(self) -> None:
        assert ModelValidators.validate_phone("13800138000") == "13800138000"

    def test_valid_with_country_code(self) -> None:
        assert ModelValidators.validate_phone("+86 138 0013 8000") == "+86 138 0013 8000"

    def test_valid_with_dashes(self) -> None:
        assert ModelValidators.validate_phone("+1-555-123-4567") == "+1-555-123-4567"

    def test_valid_with_parens(self) -> None:
        assert ModelValidators.validate_phone("(021) 1234-5678") == "(021) 1234-5678"

    def test_too_short_raises(self) -> None:
        with pytest.raises(ValueError, match="电话号码格式不正确"):
            ModelValidators.validate_phone("12345")

    def test_too_long_raises(self) -> None:
        with pytest.raises(ValueError, match="电话号码格式不正确"):
            ModelValidators.validate_phone("1" * 25)

    def test_letters_raise(self) -> None:
        with pytest.raises(ValueError, match="电话号码格式不正确"):
            ModelValidators.validate_phone("abc1234567")


class TestValidateEmail:
    def test_empty_returns_value(self) -> None:
        assert ModelValidators.validate_email("") == ""
        assert ModelValidators.validate_email(None) is None

    def test_valid_simple_email(self) -> None:
        assert ModelValidators.validate_email("user@example.com") == "user@example.com"

    def test_valid_with_dots_and_plus(self) -> None:
        assert ModelValidators.validate_email("user.name+tag@sub.example.co") == (
            "user.name+tag@sub.example.co"
        )

    def test_missing_at_raises(self) -> None:
        with pytest.raises(ValueError, match="邮箱格式不正确"):
            ModelValidators.validate_email("userexample.com")

    def test_missing_tld_raises(self) -> None:
        with pytest.raises(ValueError, match="邮箱格式不正确"):
            ModelValidators.validate_email("user@example")

    def test_multiple_at_raises(self) -> None:
        with pytest.raises(ValueError, match="邮箱格式不正确"):
            ModelValidators.validate_email("user@@example.com")

    def test_spaces_raises(self) -> None:
        with pytest.raises(ValueError, match="邮箱格式不正确"):
            ModelValidators.validate_email("user @example.com")


class TestRegisterModelValidators:
    def test_returns_true_on_success(self) -> None:
        assert register_model_validators() is True

    def test_returns_false_on_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force the inner imports to fail by patching one model to raise ImportError.
        def boom(_name: str) -> None:
            raise ImportError("forced failure for test")

        # Patch the importlib in the validators module by injecting a bad __import__
        original_import = __builtins__["__import__"]  # type: ignore[index]

        def fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if "product" in name:
                raise ImportError("forced")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        assert register_model_validators() is False

    def test_returns_false_on_unexpected_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(_name: str) -> None:
            raise RuntimeError("unexpected")

        original_import = __builtins__["__import__"]  # type: ignore[index]

        def fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if "customer" in name:
                raise RuntimeError("unexpected")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        assert register_model_validators() is False
