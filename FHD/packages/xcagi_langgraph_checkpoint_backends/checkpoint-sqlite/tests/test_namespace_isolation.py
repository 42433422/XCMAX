"""Regression tests for namespace-boundary isolation in the vendored store."""

import asyncio
import sqlite3

import pytest

from langgraph.store.base import (
    GetOp,
    InvalidNamespaceError,
    ListNamespacesOp,
    MatchCondition,
    PutOp,
    SearchOp,
)
from langgraph.store.base.batch import AsyncBatchedBaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.sqlite import AsyncSqliteStore, SqliteStore

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


INVALID_NAMESPACES = [("tenant.other",), ("tenant", ""), ("tenant", 1)]


class BufferedStore(AsyncBatchedBaseStore):
    def __init__(self):
        self.calls = 0
        self.memory = InMemoryStore()
        super().__init__()

    async def abatch(self, ops):
        self.calls += 1
        return self.memory.batch(ops)


@pytest.mark.parametrize("namespace", INVALID_NAMESPACES)
@pytest.mark.parametrize("method", ["get", "delete", "search", "prefix", "suffix"])
@pytest.mark.parametrize("mode", ["sync", "async", "buffered"])
def test_public_methods_reject_labels_before_dispatch(namespace, method, mode):
    def call(store, asynchronous=False):
        name = "a" if asynchronous else ""
        if method in ("prefix", "suffix"):
            return getattr(store, name + "list_namespaces")(**{method: namespace})
        args = (namespace,) if method == "search" else (namespace, "key")
        return getattr(store, name + method)(*args)

    async def run():
        store = BufferedStore() if mode == "buffered" else InMemoryStore()
        try:
            with pytest.raises(InvalidNamespaceError):
                await call(store, True)
            if mode == "buffered":
                assert store.calls == 0
        finally:
            if mode == "buffered":
                store._task.cancel()
                await asyncio.gather(store._task, return_exceptions=True)

    if mode == "sync":
        with pytest.raises(InvalidNamespaceError):
            call(InMemoryStore())
    else:
        asyncio.run(run())


@pytest.mark.parametrize("namespace", INVALID_NAMESPACES)
@pytest.mark.parametrize("kind", ["get", "put", "delete", "search", "prefix", "suffix"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_direct_batch_rejects_alias_without_partial_writes(
    namespace, kind, asynchronous
):
    op = {
        "get": GetOp(namespace, "key"),
        "put": PutOp(namespace, "key", {"changed": True}),
        "delete": PutOp(namespace, "key", None),
        "search": SearchOp(namespace),
        "prefix": ListNamespacesOp((MatchCondition("prefix", namespace),)),
        "suffix": ListNamespacesOp((MatchCondition("suffix", namespace),)),
    }[kind]
    batch = [PutOp(("valid",), "key", {}), op]

    async def run():
        async with AsyncSqliteStore.from_conn_string(":memory:") as store:
            await store.aput(("tenant", "other"), "key", {"original": True})
            with pytest.raises(InvalidNamespaceError):
                await store.abatch(batch)
            assert (await store.aget(("tenant", "other"), "key")).value == {
                "original": True
            }
            assert await store.aget(("valid",), "key") is None

    if asynchronous:
        asyncio.run(run())
    else:
        with sqlite3.connect(":memory:", isolation_level=None) as connection:
            store = SqliteStore(connection)
            store.put(("tenant", "other"), "key", {"original": True})
            with pytest.raises(InvalidNamespaceError):
                store.batch(batch)
            assert store.get(("tenant", "other"), "key").value == {"original": True}
            assert store.get(("valid",), "key") is None


def test_empty_search_prefix_wildcards_and_write_only_restrictions_stay_compatible():
    with sqlite3.connect(":memory:", isolation_level=None) as connection:
        store = SqliteStore(connection)
        store.put(("tenant", "a_%"), "key", {"v": 1})
        found, listed = store.batch(
            [
                SearchOp(()),
                ListNamespacesOp((MatchCondition("prefix", ("tenant", "*")),)),
                PutOp(("langgraph", "internal"), "key", {}),
            ]
        )[:2]
        assert [item.namespace for item in found] == [("tenant", "a_%")]
        assert listed == [("tenant", "a_%")]
        for namespace in [(), ("langgraph", "internal")]:
            with pytest.raises(InvalidNamespaceError):
                store.put(namespace, "key", {})


def test_invalid_async_neighbor_does_not_poison_shared_batch():
    async def run():
        store = BufferedStore()
        try:
            results = await asyncio.gather(
                store.aput(("tenant", "a_%"), "key", {"v": 1}),
                store.aget(("tenant.other",), "key"),
                return_exceptions=True,
            )
            assert results[0] is None
            assert isinstance(results[1], InvalidNamespaceError)
            assert len(await store.asearch(())) == 1
            assert await store.alist_namespaces(prefix=("tenant", "*")) == [
                ("tenant", "a_%")
            ]
        finally:
            store._task.cancel()
            await asyncio.gather(store._task, return_exceptions=True)

    asyncio.run(run())
