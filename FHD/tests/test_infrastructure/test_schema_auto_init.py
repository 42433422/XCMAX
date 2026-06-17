"""Tests for app.infrastructure.db.schema_auto_init."""
from __future__ import annotations

import pytest

from app.infrastructure.db.schema_auto_init import (
    _load_init_sql_text,
    statements_from_init_sql,
)


class TestStatementsFromInitSql:
    def test_empty_string_returns_empty(self):
        assert statements_from_init_sql("") == []

    def test_none_returns_empty(self):
        assert statements_from_init_sql(None) == []

    def test_single_statement(self):
        result = statements_from_init_sql("SELECT 1;")
        assert result == ["SELECT 1;"]

    def test_multiple_statements(self):
        sql = "CREATE TABLE t1 (id INT); CREATE TABLE t2 (id INT);"
        result = statements_from_init_sql(sql)
        assert len(result) == 2

    def test_comments_stripped(self):
        sql = "-- comment\nCREATE TABLE t1 (id INT);"
        result = statements_from_init_sql(sql)
        assert len(result) == 1
        assert "comment" not in result[0]

    def test_begin_commit_skipped(self):
        sql = "BEGIN; CREATE TABLE t1 (id INT); COMMIT;"
        result = statements_from_init_sql(sql)
        assert len(result) == 1
        assert "CREATE TABLE" in result[0]

    def test_whitespace_only_chunks_skipped(self):
        sql = "   ;   ; CREATE TABLE t1 (id INT);   ;"
        result = statements_from_init_sql(sql)
        assert len(result) == 1

    def test_multiline_statement(self):
        sql = "CREATE TABLE t1 (\n  id INT,\n  name TEXT\n);"
        result = statements_from_init_sql(sql)
        assert len(result) == 1
        assert "id INT" in result[0]
        assert "name TEXT" in result[0]

    def test_semicolon_appended(self):
        result = statements_from_init_sql("SELECT 1")
        assert result == ["SELECT 1;"]


class TestLoadInitSqlText:
    def test_returns_string(self):
        result = _load_init_sql_text()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_create_table(self):
        result = _load_init_sql_text()
        assert "CREATE TABLE" in result.upper() or "purchase_units" in result
