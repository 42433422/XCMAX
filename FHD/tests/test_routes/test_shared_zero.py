"""Tests for app.fastapi_routes._shared."""

from __future__ import annotations

import pytest

from app.fastapi_routes._shared import (
    _ALLOWED_SQL_COLUMNS,
    _ALLOWED_SQL_TABLES,
    sql_ident,
    validate_order_clause,
)


class TestSqlIdent:
    """Tests for sql_ident."""

    def test_simple_name(self) -> None:
        assert sql_ident("name") == '"name"'

    def test_name_with_quotes(self) -> None:
        assert sql_ident('na"me') == '"na""me"'

    def test_empty_string(self) -> None:
        assert sql_ident("") == '""'


class TestValidateOrderClause:
    """Tests for validate_order_clause."""

    def test_single_column_asc(self) -> None:
        result = validate_order_clause("name ASC")
        assert result == '"name" ASC'

    def test_single_column_desc(self) -> None:
        result = validate_order_clause("name DESC")
        assert result == '"name" DESC'

    def test_single_column_implicit_asc(self) -> None:
        result = validate_order_clause("name")
        assert result == '"name"'

    def test_multiple_columns(self) -> None:
        result = validate_order_clause("name ASC, id DESC")
        assert '"name" ASC' in result
        assert '"id" DESC' in result

    def test_id_column_allowed(self) -> None:
        result = validate_order_clause("id ASC")
        assert result == '"id" ASC'

    def test_invalid_column_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid ORDER BY token"):
            validate_order_clause("DROP TABLE users")

    def test_disallowed_column_raises(self) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            validate_order_clause("secret_col ASC")

    def test_quoted_column(self) -> None:
        result = validate_order_clause('"name" ASC')
        assert result == '"name" ASC'

    def test_nulls_first_suffix(self) -> None:
        result = validate_order_clause("name ASC NULLS FIRST")
        assert "NULLS FIRST" in result

    def test_nulls_last_suffix(self) -> None:
        result = validate_order_clause("name DESC NULLS LAST")
        assert "NULLS LAST" in result

    def test_allowed_sql_tables_not_empty(self) -> None:
        assert len(_ALLOWED_SQL_TABLES) > 0
        assert "customers" in _ALLOWED_SQL_TABLES
        assert "products" in _ALLOWED_SQL_TABLES

    def test_allowed_sql_columns_not_empty(self) -> None:
        assert len(_ALLOWED_SQL_COLUMNS) > 0
        assert "id" in _ALLOWED_SQL_COLUMNS
        assert "name" in _ALLOWED_SQL_COLUMNS
