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

from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.store.postgres.base import (
    PostgresStore,
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


def test_postgres_direct_batch_rejects_ambiguous_dotted_namespace() -> None:
    valid = PutOp(("tenant", "orders"), "k1", {"value": 1})
    grouped, total = _group_ops([valid])
    assert total == 1
    assert grouped[PutOp][0][1] == valid

    ambiguous = PutOp(("tenant.orders",), "k2", {"value": 2})
    with pytest.raises(InvalidNamespaceError, match="cannot contain periods"):
        _group_ops([ambiguous])

    # Match upstream op validation: this backport checks ambiguous labels and
    # leaves the pre-existing reserved-root behavior unchanged.
    reserved_root = PutOp(("langgraph",), "legacy", {})
    assert _group_ops([reserved_root])[1] == 1


def test_postgres_direct_batch_rejects_non_string_and_empty_labels() -> None:
    for namespace in (("tenant", ""), ("tenant", 7)):
        operation = PutOp(namespace, "k", {})  # type: ignore[arg-type]
        with pytest.raises(InvalidNamespaceError):
            _group_ops([operation])


@pytest.mark.parametrize(
    "operation",
    (
        GetOp(("tenant.orders",), "key"),
        SearchOp(("tenant.orders",)),
        ListNamespacesOp((MatchCondition("prefix", ("tenant.orders",)),)),
        PutOp(("tenant.orders",), "key", {}),
    ),
)
def test_postgres_direct_batch_validates_every_namespace_operation(operation) -> None:
    with pytest.raises(InvalidNamespaceError, match="cannot contain periods"):
        _group_ops([operation])


def test_sync_batch_accepts_nested_namespaces_and_rejects_aliases(monkeypatch) -> None:
    from contextlib import contextmanager

    seen = []

    @contextmanager
    def cursor(self, *, pipeline):
        assert pipeline is True
        yield object()

    def apply_puts(self, put_ops, cur):
        seen.extend(op.namespace for _, op in put_ops)

    monkeypatch.setattr(PostgresStore, "_cursor", cursor)
    monkeypatch.setattr(PostgresStore, "_batch_put_ops", apply_puts)
    store = PostgresStore(object())

    assert store.batch([PutOp(("tenant", "orders"), "ok", {})]) == [None]
    assert seen == [("tenant", "orders")]
    with pytest.raises(InvalidNamespaceError, match="cannot contain periods"):
        store.batch([PutOp(("tenant.orders",), "alias", {})])
    assert seen == [("tenant", "orders")]


def test_async_batch_accepts_nested_namespaces_and_rejects_aliases(monkeypatch) -> None:
    import asyncio

    async def exercise() -> None:
        seen = []
        store = AsyncPostgresStore(object())

        async def execute_batch(grouped_ops, results):
            seen.extend(op.namespace for _, op in grouped_ops[PutOp])

        monkeypatch.setattr(store, "_execute_batch", execute_batch)

        assert await store.abatch([PutOp(("tenant", "orders"), "ok", {})]) == [None]
        assert seen == [("tenant", "orders")]
        with pytest.raises(InvalidNamespaceError, match="cannot contain periods"):
            await store.abatch([PutOp(("tenant.orders",), "alias", {})])
        assert seen == [("tenant", "orders")]

    asyncio.run(exercise())
