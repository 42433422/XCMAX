"""Regression tests for namespace-boundary isolation in the vendored store."""

from langgraph.store.postgres.base import (
    _namespace_match_pattern,
    _namespace_prefix_condition,
)


def test_prefix_condition_escapes_like_metacharacters() -> None:
    condition, params = _namespace_prefix_condition(("tenant_1%",))

    assert "ESCAPE" in condition
    assert params == ("tenant_1%", r"tenant\_1\%.%")


def test_match_pattern_respects_namespace_segments() -> None:
    import re

    pattern = _namespace_match_pattern(("tenant", "*", "orders"), "prefix")
    assert re.search(pattern, "tenant.acme.orders")
    assert re.search(pattern, "tenant.acme.orders.archive")
    assert not re.search(pattern, "tenant.acme.eu.orders")
    assert not re.search(pattern, "tenant-acme.orders")
