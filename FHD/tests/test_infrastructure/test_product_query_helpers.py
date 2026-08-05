"""Tests for app.infrastructure.repositories.product_query_helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.infrastructure.repositories.product_query_helpers import (
    TRIVIAL_MEASURE_UNITS,
    apply_product_filters,
)


def _mock_query() -> MagicMock:
    return MagicMock()


class TestApplyProductFilters:
    def test_no_filters_returns_same_query(self) -> None:
        q = _mock_query()
        result = apply_product_filters(q)
        assert result is q
        q.filter.assert_not_called()

    def test_unit_name_filters(self) -> None:
        q = _mock_query()
        apply_product_filters(q, unit_name="蓝天单位")
        q.filter.assert_called_once()

    def test_model_number_filters(self) -> None:
        q = _mock_query()
        apply_product_filters(q, model_number="M1")
        q.filter.assert_called_once()

    def test_model_number_blank_skips(self) -> None:
        q = _mock_query()
        apply_product_filters(q, model_number="   ")
        q.filter.assert_not_called()

    def test_keyword_single_segment_filters(self) -> None:
        q = _mock_query()
        apply_product_filters(q, keyword="油漆")
        q.filter.assert_called()

    def test_keyword_multi_segment_filters(self) -> None:
        q = _mock_query()
        # 中英文+数字混合 → regex 拆成多段 → 每段独立 filter
        apply_product_filters(q, keyword="蓝色 油漆 100")
        assert q.filter.call_count >= 1

    def test_keyword_blank_skips(self) -> None:
        q = _mock_query()
        apply_product_filters(q, keyword="   ")
        q.filter.assert_not_called()

    def test_all_filters_combined(self) -> None:
        q = _mock_query()
        apply_product_filters(q, unit_name="u1", model_number="M1", keyword="k")
        assert q.filter.call_count >= 1


class TestTrivialMeasureUnits:
    def test_has_common_units(self) -> None:
        assert "桶" in TRIVIAL_MEASURE_UNITS
        assert "千克" in TRIVIAL_MEASURE_UNITS
        assert "件" in TRIVIAL_MEASURE_UNITS

    def test_is_frozen_set(self) -> None:
        with pytest.raises(AttributeError):
            TRIVIAL_MEASURE_UNITS.add("新增")  # type: ignore[attr-defined]
