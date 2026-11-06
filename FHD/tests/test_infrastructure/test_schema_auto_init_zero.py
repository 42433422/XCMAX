"""Tests for app.infrastructure.db.schema_auto_init."""

from __future__ import annotations

import pytest

from app.infrastructure.db.schema_auto_init import statements_from_init_sql


class TestStatementsFromInitSql:
    """Tests for statements_from_init_sql."""

    def test_empty_string(self) -> None:
        result = statements_from_init_sql("")
        assert result == []

    def test_none_input(self) -> None:
        result = statements_from_init_sql(None)
        assert result == []

    def test_single_statement(self) -> None:
        result = statements_from_init_sql("CREATE TABLE foo (id INT)")
        assert len(result) == 1
        assert result[0] == "CREATE TABLE foo (id INT);"

    def test_multiple_statements(self) -> None:
        sql = "CREATE TABLE a (id INT); CREATE TABLE b (id INT)"
        result = statements_from_init_sql(sql)
        assert len(result) == 2

    def test_skips_comments(self) -> None:
        sql = "-- This is a comment\nCREATE TABLE foo (id INT)"
        result = statements_from_init_sql(sql)
        assert len(result) == 1
        assert "comment" not in result[0]

    def test_skips_empty_chunks(self) -> None:
        sql = ";;;"
        result = statements_from_init_sql(sql)
        assert result == []

    def test_skips_begin_commit(self) -> None:
        sql = "BEGIN; CREATE TABLE foo (id INT); COMMIT;"
        result = statements_from_init_sql(sql)
        assert len(result) == 1
        assert result[0] == "CREATE TABLE foo (id INT);"

    def test_skips_begin_case_insensitive(self) -> None:
        sql = "begin; create table foo (id int); commit;"
        result = statements_from_init_sql(sql)
        assert len(result) == 1

    def test_preserves_whitespace_in_statements(self) -> None:
        sql = "CREATE TABLE foo\n  (id INT,\n   name TEXT)"
        result = statements_from_init_sql(sql)
        assert len(result) == 1
        assert "id INT" in result[0]
        assert "name TEXT" in result[0]

    def test_complex_sql(self) -> None:
        sql = """
        -- Table for users
        CREATE TABLE users (id BIGSERIAL PRIMARY KEY, name TEXT);
        -- Index
        CREATE INDEX idx_users_name ON users(name);
        """
        result = statements_from_init_sql(sql)
        assert len(result) == 2
