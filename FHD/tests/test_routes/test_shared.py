"""Tests for app.fastapi_routes._shared."""
from __future__ import annotations

import pytest

from app.fastapi_routes._shared import sql_ident, validate_order_clause, _ALLOWED_SQL_COLUMNS


class TestSqlIdent:
    def test_simple_name(self):
        assert sql_ident("name") == '"name"'

    def test_name_with_quotes(self):
        assert sql_ident('na"me') == '"na""me"'

    def test_empty_string(self):
        assert sql_ident("") == '""'


class TestValidateOrderClause:
    def test_simple_column_asc(self):
        result = validate_order_clause("name ASC")
        assert '"name"' in result
        assert "ASC" in result

    def test_simple_column_desc(self):
        result = validate_order_clause("name DESC")
        assert '"name"' in result
        assert "DESC" in result

    def test_allowed_column_only(self):
        result = validate_order_clause("name")
        assert '"name"' in result

    def test_disallowed_column_raises(self):
        with pytest.raises(ValueError, match="ORDER BY column not allowed"):
            validate_order_clause("evil_column ASC")

    def test_multiple_columns(self):
        result = validate_order_clause("name ASC, created_at DESC")
        assert '"name"' in result
        assert '"created_at"' in result

    def test_nulls_first(self):
        result = validate_order_clause("name ASC NULLS FIRST")
        assert "NULLS FIRST" in result

    def test_nulls_last(self):
        result = validate_order_clause("name DESC NULLS LAST")
        assert "NULLS LAST" in result

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            validate_order_clause("")

    def test_id_column_allowed(self):
        result = validate_order_clause("id ASC")
        assert '"id"' in result

    def test_quoted_column(self):
        result = validate_order_clause('"name" ASC')
        assert '"name"' in result
