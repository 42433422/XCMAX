"""Tests for app.services.unified_query_service — _parse_filter pure function."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.unified_query_service import UnifiedQueryService


# ========================= _parse_filter =================================


class TestParseFilter:
    """Test the _parse_filter static method with a real class with specific attrs."""

    @pytest.fixture()
    def model_class(self):
        """Create a mock model class with SQLAlchemy-like column attributes."""
        mc = MagicMock()
        # Create column-like mock attributes
        mc.name = MagicMock()
        mc.age = MagicMock()
        mc.status = MagicMock()
        mc.price = MagicMock()

        # Setup comparison operators
        for attr_name in ("name", "age", "status", "price"):
            attr = getattr(mc, attr_name)
            attr.__ge__ = MagicMock(return_value=f"{attr_name} >= value")
            attr.__gt__ = MagicMock(return_value=f"{attr_name} > value")
            attr.__le__ = MagicMock(return_value=f"{attr_name} <= value")
            attr.__lt__ = MagicMock(return_value=f"{attr_name} < value")
            attr.__ne__ = MagicMock(return_value=f"{attr_name} != value")
            attr.in_ = MagicMock(return_value=f"{attr_name} IN value")
            attr.like = MagicMock(return_value=f"{attr_name} LIKE value")
            attr.ilike = MagicMock(return_value=f"{attr_name} ILIKE value")
            attr.__eq__ = MagicMock(return_value=f"{attr_name} == value")

        # MagicMock has all attributes by default, so we need to explicitly
        # control hasattr behavior for unknown fields
        return mc

    def test_gte(self, model_class):
        result = UnifiedQueryService._parse_filter(model_class, "age__gte", 18)
        model_class.age.__ge__.assert_called_once_with(18)

    def test_gt(self, model_class):
        result = UnifiedQueryService._parse_filter(model_class, "age__gt", 18)
        model_class.age.__gt__.assert_called_once_with(18)

    def test_lte(self, model_class):
        result = UnifiedQueryService._parse_filter(model_class, "age__lte", 65)
        model_class.age.__le__.assert_called_once_with(65)

    def test_lt(self, model_class):
        result = UnifiedQueryService._parse_filter(model_class, "age__lt", 65)
        model_class.age.__lt__.assert_called_once_with(65)

    def test_ne(self, model_class):
        result = UnifiedQueryService._parse_filter(model_class, "status__ne", "deleted")
        model_class.status.__ne__.assert_called_once_with("deleted")

    def test_in(self, model_class):
        result = UnifiedQueryService._parse_filter(model_class, "status__in", ["active", "pending"])
        model_class.status.in_.assert_called_once_with(["active", "pending"])

    def test_like(self, model_class):
        result = UnifiedQueryService._parse_filter(model_class, "name__like", "test")
        model_class.name.like.assert_called_once_with("%test%")

    def test_ilike(self, model_class):
        result = UnifiedQueryService._parse_filter(model_class, "name__ilike", "test")
        model_class.name.ilike.assert_called_once_with("%test%")

    def test_exact_match(self, model_class):
        result = UnifiedQueryService._parse_filter(model_class, "status", "active")
        model_class.status.__eq__.assert_called_once_with("active")

    def test_exact_match_list_value(self, model_class):
        result = UnifiedQueryService._parse_filter(model_class, "status", ["a", "b"])
        model_class.status.in_.assert_called_once_with(["a", "b"])

    def test_unknown_field_returns_none(self):
        """Test that unknown fields return None using a real class."""
        class RealModel:
            name = "column"

        result = UnifiedQueryService._parse_filter(RealModel, "nonexistent", "value")
        assert result is None

    def test_unknown_field_with_suffix_returns_none(self):
        """Test that unknown fields with suffixes return None using a real class."""
        class RealModel:
            name = "column"

        result = UnifiedQueryService._parse_filter(RealModel, "nonexistent__gte", 10)
        assert result is None
