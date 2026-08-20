"""Regression tests for namespace-boundary isolation in the vendored store."""

import sqlite3

from langgraph.store.sqlite.base import (
    NS_MATCH_FUNCTION,
    _namespace_match,
    _namespace_match_pattern,
    _namespace_prefix_condition,
)


def test_prefix_condition_does_not_cross_segment_or_case_boundaries() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE namespaces (prefix TEXT NOT NULL)")
    connection.executemany(
        "INSERT INTO namespaces(prefix) VALUES (?)",
        [("tenant",), ("tenant.orders",), ("tenant2",), ("TENANT.orders",)],
    )
    condition, params = _namespace_prefix_condition(("tenant",))

    rows = connection.execute(
        f"SELECT prefix FROM namespaces WHERE {condition} ORDER BY prefix", params
    ).fetchall()

    assert rows == [("tenant",), ("tenant.orders",)]


def test_wildcard_matches_exactly_one_namespace_segment() -> None:
    connection = sqlite3.connect(":memory:")
    connection.create_function(
        NS_MATCH_FUNCTION, 2, _namespace_match, deterministic=True
    )
    pattern = _namespace_match_pattern(("tenant", "*", "orders"), "prefix")

    matches = [
        value
        for value in (
            "tenant.acme.orders",
            "tenant.acme.orders.archive",
            "tenant.acme.eu.orders",
        )
        if connection.execute(
            f"SELECT {NS_MATCH_FUNCTION}(?, ?)", (value, pattern)
        ).fetchone()[0]
    ]

    assert matches == ["tenant.acme.orders", "tenant.acme.orders.archive"]
