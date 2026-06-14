"""app/domain/services/conversation/chinese_number 单测。"""

from __future__ import annotations

from app.domain.services.conversation.chinese_number import (
    cn_to_number,
    extract_number_from_text,
    parse_quantity_with_unit,
)


class TestCnToNumber:
    def test_single_digits(self) -> None:
        assert cn_to_number("五") == 5
        assert cn_to_number("零") == 0

    def test_teen_pattern(self) -> None:
        assert cn_to_number("一十") == 11

    def test_tens_pattern(self) -> None:
        assert cn_to_number("二十八") == 28

    def test_invalid_returns_none(self) -> None:
        assert cn_to_number("") is None
        assert cn_to_number("一百") is None


class TestExtractNumber:
    def test_arabic_first(self) -> None:
        assert extract_number_from_text("来3桶") == 3

    def test_chinese_fallback(self) -> None:
        assert extract_number_from_text("来五桶") == 5


class TestParseQuantityWithUnit:
    def test_arabic_with_unit(self) -> None:
        assert parse_quantity_with_unit("共10桶", unit="桶") == 10

    def test_chinese_with_unit(self) -> None:
        assert parse_quantity_with_unit("要五桶", unit="桶") == 5

    def test_no_match(self) -> None:
        assert parse_quantity_with_unit("随便说说", unit="桶") is None
