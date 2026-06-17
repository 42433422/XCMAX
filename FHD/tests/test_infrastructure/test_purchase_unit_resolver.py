"""Tests for app.infrastructure.lookups.purchase_unit_resolver — purchase unit fuzzy matching."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.lookups.purchase_unit_resolver import (
    ResolvedPurchaseUnit,
    _first_letter_match,
    _get_pinyin_parts,
    _pinyin_similarity,
    _to_first_letters,
    _to_pinyin,
    resolve_purchase_unit,
)


# ---------------------------------------------------------------------------
# _to_pinyin
# ---------------------------------------------------------------------------

class TestToPinyin:
    def test_empty_string(self):
        assert _to_pinyin("") == ""

    def test_ascii_lowercase(self):
        result = _to_pinyin("abc")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_chinese_characters(self):
        result = _to_pinyin("北京")
        assert isinstance(result, str)
        # Should produce pinyin or lowercase fallback

    def test_none_returns_empty(self):
        assert _to_pinyin(None) == ""


# ---------------------------------------------------------------------------
# _to_first_letters
# ---------------------------------------------------------------------------

class TestToFirstLetters:
    def test_empty_string(self):
        assert _to_first_letters("") == ""

    def test_ascii_letters(self):
        result = _to_first_letters("abc")
        assert isinstance(result, str)

    def test_chinese_characters(self):
        result = _to_first_letters("北京")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _get_pinyin_parts
# ---------------------------------------------------------------------------

class TestGetPinyinParts:
    def test_empty_string(self):
        assert _get_pinyin_parts("") == []

    def test_returns_list(self):
        result = _get_pinyin_parts("北京")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _pinyin_similarity
# ---------------------------------------------------------------------------

class TestPinyinSimilarity:
    def test_same_string_high_similarity(self):
        sim = _pinyin_similarity("北京", "北京")
        assert sim > 0.9

    def test_different_strings_lower_similarity(self):
        sim = _pinyin_similarity("北京", "上海")
        assert sim < 1.0

    def test_empty_returns_zero(self):
        assert _pinyin_similarity("", "test") == 0.0
        assert _pinyin_similarity("test", "") == 0.0


# ---------------------------------------------------------------------------
# _first_letter_match
# ---------------------------------------------------------------------------

class TestFirstLetterMatch:
    def test_exact_match(self):
        assert _first_letter_match("bj", "bj") is True

    def test_prefix_match(self):
        assert _first_letter_match("bj", "bjx") is True

    def test_no_match(self):
        assert _first_letter_match("ab", "cd") is False

    def test_empty_returns_false(self):
        assert _first_letter_match("", "bj") is False
        assert _first_letter_match("bj", "") is False

    def test_short_strings_no_match(self):
        assert _first_letter_match("a", "b") is False

    def test_two_char_prefix_match(self):
        assert _first_letter_match("bjxx", "bjyy") is True


# ---------------------------------------------------------------------------
# resolve_purchase_unit
# ---------------------------------------------------------------------------

class TestResolvePurchaseUnit:
    def test_empty_input_returns_none(self):
        assert resolve_purchase_unit("") is None

    def test_none_input_returns_none(self):
        assert resolve_purchase_unit(None) is None

    def test_exact_match(self):
        mock_customer = MagicMock()
        mock_customer.id = 1
        mock_customer.unit_name = "测试客户"
        mock_customer.contact_person = "张三"
        mock_customer.contact_phone = "13800138000"
        mock_customer.address = "北京市"

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [mock_customer]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        # get_db is lazily imported inside the function from app.db.session
        with patch(
            "app.db.session.get_db",
            return_value=mock_db,
        ):
            result = resolve_purchase_unit("测试客户")
        assert result is not None
        assert result.unit_name == "测试客户"
        assert result.id == 1

    def test_no_match_returns_none(self):
        mock_customer = MagicMock()
        mock_customer.id = 1
        mock_customer.unit_name = "其他客户"
        mock_customer.contact_person = ""
        mock_customer.contact_phone = ""
        mock_customer.address = ""

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [mock_customer]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch(
            "app.db.session.get_db",
            return_value=mock_db,
        ):
            result = resolve_purchase_unit("完全不匹配的客户名")
        assert result is None

    def test_substring_match(self):
        mock_customer = MagicMock()
        mock_customer.id = 2
        mock_customer.unit_name = "北京测试有限公司"
        mock_customer.contact_person = "李四"
        mock_customer.contact_phone = ""
        mock_customer.address = ""

        mock_db = MagicMock()
        mock_db.query.return_value.all.return_value = [mock_customer]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch(
            "app.db.session.get_db",
            return_value=mock_db,
        ):
            result = resolve_purchase_unit("测试")
        assert result is not None
        assert "测试" in result.unit_name


# ---------------------------------------------------------------------------
# ResolvedPurchaseUnit dataclass
# ---------------------------------------------------------------------------

class TestResolvedPurchaseUnit:
    def test_creation(self):
        rpu = ResolvedPurchaseUnit(
            id=1,
            unit_name="Test",
            contact_person="John",
            contact_phone="123",
            address="Street",
        )
        assert rpu.id == 1
        assert rpu.unit_name == "Test"

    def test_frozen(self):
        rpu = ResolvedPurchaseUnit(
            id=1, unit_name="T", contact_person="", contact_phone="", address=""
        )
        with pytest.raises(AttributeError):
            rpu.unit_name = "changed"
