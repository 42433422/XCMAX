"""Regression tests for namespace-boundary isolation in the vendored store."""

import pytest

from langgraph.store.base import (
    GetOp,
    InvalidNamespaceError,
    ListNamespacesOp,
    MatchCondition,
    PutOp,
    SearchOp,
)
from langgraph.store.postgres.base import (
    _group_ops,
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


@pytest.mark.parametrize(
    "namespace", [("tenant.other",), ("tenant", ""), ("tenant", 1)]
)
@pytest.mark.parametrize("kind", ["get", "put", "delete", "search", "prefix", "suffix"])
def test_sync_and_async_batch_grouping_rejects_invalid_labels(namespace, kind):
    op = {
        "get": GetOp(namespace, "key"),
        "put": PutOp(namespace, "key", {}),
        "delete": PutOp(namespace, "key", None),
        "search": SearchOp(namespace),
        "prefix": ListNamespacesOp((MatchCondition("prefix", namespace),)),
        "suffix": ListNamespacesOp((MatchCondition("suffix", namespace),)),
    }[kind]
    with pytest.raises(InvalidNamespaceError):
        _group_ops([PutOp(("valid",), "key", {}), op])
