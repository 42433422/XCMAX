"""Tests for safe SQLite identifier helpers."""

from __future__ import annotations

import pytest

from app.infrastructure.db.sql_identifiers import (
    quote_sqlite_identifier,
    resolve_products_table,
    resolve_wechat_message_table,
)


def test_resolve_wechat_message_table_whitelist() -> None:
    assert resolve_wechat_message_table(["MSG", "other"]) == "MSG"
    assert resolve_wechat_message_table(["Msg_abc123"]) == "Msg_abc123"
    assert resolve_wechat_message_table(["evil;drop"]) is None


def test_resolve_products_table_canonical() -> None:
    assert resolve_products_table(["Products", "x"]) == "products"
    assert resolve_products_table(["evil"]) is None


def test_quote_sqlite_identifier_rejects_invalid() -> None:
    assert quote_sqlite_identifier("products") == '"products"'
    with pytest.raises(ValueError):
        quote_sqlite_identifier("bad-name")
