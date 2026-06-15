"""Safe SQLite identifier quoting for raw SQL (external DB reads)."""

from __future__ import annotations

import re

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MSG_TABLE_RE = re.compile(r"^Msg_[0-9a-fA-F]+$")

KNOWN_WECHAT_MSG_TABLES = frozenset({"MSG", "Message"})


def quote_sqlite_identifier(name: str) -> str:
    """Return double-quoted identifier; reject invalid names."""
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"invalid SQLite identifier: {name!r}")
    return f'"{name}"'


def resolve_wechat_message_table(table_names: list[str]) -> str | None:
    """Pick wechat message table from sqlite_master names (whitelist)."""
    names = {t for t in table_names if t}
    if "MSG" in names:
        return "MSG"
    if "Message" in names:
        return "Message"
    for t in names:
        if _MSG_TABLE_RE.match(t):
            return t
    return None


def resolve_products_table(table_names: list[str]) -> str | None:
    """Only exact `products` table (case-insensitive match, canonical name)."""
    for t in table_names:
        if t and t.lower() == "products":
            return "products"
    return None
