"""Tests for app.infrastructure.documents.price_list_export — pure helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ========================= _format_price_cell ============================


class TestFormatPriceCell:
    def test_none(self):
        from app.infrastructure.documents.price_list_export import _format_price_cell

        assert _format_price_cell(None) == ""

    def test_empty_string(self):
        from app.infrastructure.documents.price_list_export import _format_price_cell

        assert _format_price_cell("") == ""

    def test_integer(self):
        from app.infrastructure.documents.price_list_export import _format_price_cell

        assert _format_price_cell(100) == "100"

    def test_integer_float(self):
        from app.infrastructure.documents.price_list_export import _format_price_cell

        assert _format_price_cell(100.0) == "100"

    def test_decimal(self):
        from app.infrastructure.documents.price_list_export import _format_price_cell

        assert _format_price_cell(99.5) == "99.50"

    def test_string_number(self):
        from app.infrastructure.documents.price_list_export import _format_price_cell

        assert _format_price_cell("123.45") == "123.45"

    def test_string_integer(self):
        from app.infrastructure.documents.price_list_export import _format_price_cell

        assert _format_price_cell("200") == "200"

    def test_non_numeric_string(self):
        from app.infrastructure.documents.price_list_export import _format_price_cell

        assert _format_price_cell("N/A") == "N/A"

    def test_zero(self):
        from app.infrastructure.documents.price_list_export import _format_price_cell

        assert _format_price_cell(0) == "0"

    def test_negative(self):
        from app.infrastructure.documents.price_list_export import _format_price_cell

        assert _format_price_cell(-5.5) == "-5.50"
