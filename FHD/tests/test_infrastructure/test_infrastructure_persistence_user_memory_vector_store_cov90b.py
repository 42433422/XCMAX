"""Second-wave behavior tests for user_memory_vector_store.

Targets previously-uncovered lines in the Postgres implementation
(``PgUserMemoryVectorStore``) plus the module-level singleton helpers and the
SQLite ``_get_conn`` PRAGMA error branch. All external dependencies (SQLAlchemy
engine, sqlite connection, sibling app-service module) are mocked so the tests
are deterministic and offline.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

import app.infrastructure.persistence.user_memory_vector_store as mod
from app.infrastructure.persistence.user_memory_vector_store import (
    PgUserMemoryVectorStore,
    SQLiteUserMemoryVectorStore,
)

MODPATH = "app.infrastructure.persistence.user_memory_vector_store"


# ---------------------------------------------------------------------------
# Fake SQLAlchemy engine/connection plumbing for the PG implementation.
# ---------------------------------------------------------------------------


class _FakeResult:
    """Mimic a SQLAlchemy CursorResult enough for the store's call sites."""

    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConn:
    """Records executed statements; returns canned results by call order."""

    def __init__(self, results=None):
        # results: list of _FakeResult returned in order from execute()
        self._results = list(results or [])
        self.executed: list[tuple] = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        if self._results:
            return self._results.pop(0)
        return _FakeResult()


class _FakeEngine:
    def __init__(self, conn):
        self._conn = conn
        self.dispose = MagicMock()

    @contextmanager
    def _begin_cm(self):
        yield self._conn

    def begin(self):
        return self._begin_cm()


def _make_pg_store(begin_conn=None):
    """Construct a PgUserMemoryVectorStore with create_engine + _ensure_tables
    patched so no real DB is touched. Returns (store, engine, conn)."""
    conn = _FakeConn()
    engine = _FakeEngine(conn)
    with (
        patch(f"{MODPATH}.create_engine", return_value=engine),
        patch.object(PgUserMemoryVectorStore, "_ensure_tables", return_value=None),
    ):
        store = PgUserMemoryVectorStore("postgresql+psycopg://u:p@localhost/db")
    # Swap in a fresh conn so callers can inject canned results per-test.
    if begin_conn is not None:
        engine._conn = begin_conn
        conn = begin_conn
    return store, engine, conn


# ---------------------------------------------------------------------------
# PgUserMemoryVectorStore._ensure_tables  (lines 37-76)
# ---------------------------------------------------------------------------


class TestPgEnsureTables:
    def test_ensure_tables_runs_all_ddl(self):
        conn = _FakeConn()
        engine = _FakeEngine(conn)
        # Do NOT patch _ensure_tables here: we want it to actually run.
        with patch(f"{MODPATH}.create_engine", return_value=engine):
            PgUserMemoryVectorStore("postgresql+psycopg://u:p@localhost/db")
        sql_blob = "\n".join(stmt for stmt, _ in conn.executed)
        # Extension + both tables + both indexes => 5 statements.
        assert len(conn.executed) == 5
        assert "CREATE EXTENSION IF NOT EXISTS vector" in sql_blob
        assert "user_memory_vector_indexes" in sql_blob
        assert "user_memory_vector_chunks" in sql_blob
        assert "ivfflat" in sql_blob and "vector_cosine_ops" in sql_blob


# ---------------------------------------------------------------------------
# create_or_update_index  (lines 78-92)
# ---------------------------------------------------------------------------


class TestPgCreateOrUpdateIndex:
    def test_passes_index_user_and_timestamps(self):
        store, _engine, conn = _make_pg_store()
        with patch(f"{MODPATH}.time.time", return_value=1234.5):
            store.create_or_update_index("idx-1", "user-7")
        assert len(conn.executed) == 1
        stmt, params = conn.executed[0]
        assert "INSERT INTO user_memory_vector_indexes" in stmt
        assert params["index_id"] == "idx-1"
        assert params["user_id"] == "user-7"
        assert params["created_at"] == 1234.5
        assert params["updated_at"] == 1234.5


# ---------------------------------------------------------------------------
# upsert_chunks  (lines 94-144)
# ---------------------------------------------------------------------------


class TestPgUpsertChunks:
    def test_empty_chunks_short_circuits(self):
        store, _engine, conn = _make_pg_store()
        result = store.upsert_chunks("idx-1", [])
        assert result == 0
        # No DB roundtrip when there is nothing to write.
        assert conn.executed == []

    def test_upserts_each_chunk_then_updates_count(self):
        store, _engine, conn = _make_pg_store()
        chunks = [
            {
                "chunk_id": 11,  # non-str on purpose -> str() coercion path
                "content": "alpha",
                "embedding": [0.1, 0.2],
                "metadata": {"k": "v"},
            },
            {
                "chunk_id": "c2",
                "content": "beta",
                "embedding": [0.3, 0.4],
                # no metadata key -> default {} path (line 125)
            },
        ]
        with patch(f"{MODPATH}.time.time", return_value=999.0):
            count = store.upsert_chunks("idx-9", chunks)
        assert count == 2
        # 2 chunk inserts + 1 count-update statement.
        assert len(conn.executed) == 3
        first_params = conn.executed[0][1]
        assert first_params["chunk_id"] == "11"  # coerced to str
        assert first_params["index_id"] == "idx-9"
        assert first_params["content"] == "alpha"
        assert json.loads(first_params["embedding"]) == [0.1, 0.2]
        assert json.loads(first_params["metadata"]) == {"k": "v"}
        # second chunk had no metadata -> serialized empty dict
        assert json.loads(conn.executed[1][1]["metadata"]) == {}
        # final statement updates chunk_count
        last_stmt, last_params = conn.executed[2]
        assert "UPDATE user_memory_vector_indexes" in last_stmt
        assert last_params["index_id"] == "idx-9"
        assert last_params["updated_at"] == 999.0


# ---------------------------------------------------------------------------
# query  (lines 146-188)
# ---------------------------------------------------------------------------


class TestPgQuery:
    def test_query_maps_rows_and_normalizes(self):
        rows = [
            {"chunk_id": "c1", "content": "hi", "metadata": {"m": 1}, "score": 0.9},
            # metadata None and score None exercise the `or {}` / `or 0.0` branches
            {"chunk_id": "c2", "content": "yo", "metadata": None, "score": None},
        ]
        conn = _FakeConn(results=[_FakeResult(rows=rows)])
        store, _engine, _conn = _make_pg_store(begin_conn=conn)

        out = store.query("idx-1", [0.5, 0.5], top_k=3, filters={"ignored": True})

        assert out == [
            {"chunk_id": "c1", "content": "hi", "metadata": {"m": 1}, "score": 0.9},
            {"chunk_id": "c2", "content": "yo", "metadata": {}, "score": 0.0},
        ]
        # query_vector serialized as JSON; top_k clamped to >= 1.
        _stmt, params = conn.executed[0]
        assert json.loads(params["query_vector"]) == [0.5, 0.5]
        assert params["top_k"] == 3

    def test_query_clamps_nonpositive_top_k(self):
        conn = _FakeConn(results=[_FakeResult(rows=[])])
        store, _engine, _conn = _make_pg_store(begin_conn=conn)
        out = store.query("idx-1", [1.0], top_k=0)
        assert out == []
        assert conn.executed[0][1]["top_k"] == 1


# ---------------------------------------------------------------------------
# list_indexes  (lines 190-205)
# ---------------------------------------------------------------------------


class TestPgListIndexes:
    def test_returns_dicts_from_rows(self):
        rows = [
            {
                "index_id": "i1",
                "user_id": "u1",
                "created_at": 1.0,
                "updated_at": 2.0,
                "chunk_count": 3,
            },
        ]
        conn = _FakeConn(results=[_FakeResult(rows=rows)])
        store, _engine, _conn = _make_pg_store(begin_conn=conn)
        out = store.list_indexes()
        assert out == [dict(rows[0])]
        assert "ORDER BY updated_at DESC" in conn.executed[0][0]

    def test_returns_empty_list(self):
        conn = _FakeConn(results=[_FakeResult(rows=[])])
        store, _engine, _conn = _make_pg_store(begin_conn=conn)
        assert store.list_indexes() == []


# ---------------------------------------------------------------------------
# delete_index  (lines 207-213)
# ---------------------------------------------------------------------------


class TestPgDeleteIndex:
    def test_delete_reports_true_when_rows_removed(self):
        conn = _FakeConn(results=[_FakeResult(rowcount=1)])
        store, _engine, _conn = _make_pg_store(begin_conn=conn)
        assert store.delete_index("idx-1") is True
        stmt, params = conn.executed[0]
        assert "DELETE FROM user_memory_vector_indexes" in stmt
        assert params["index_id"] == "idx-1"

    def test_delete_reports_false_when_nothing_removed(self):
        conn = _FakeConn(results=[_FakeResult(rowcount=0)])
        store, _engine, _conn = _make_pg_store(begin_conn=conn)
        assert store.delete_index("missing") is False

    def test_delete_reports_false_when_rowcount_missing(self):
        # result without rowcount attr -> getattr default 0 -> False
        class _NoRowcount:
            pass

        conn = _FakeConn()
        # First execute returns an object without `rowcount`.
        conn._results = [_NoRowcount()]
        store, _engine, _conn = _make_pg_store(begin_conn=conn)
        assert store.delete_index("x") is False


# ---------------------------------------------------------------------------
# SQLite _get_conn PRAGMA recoverable-error branch  (line 228)
# ---------------------------------------------------------------------------


class TestSqliteGetConnPragmaBranch:
    def test_pragma_failure_is_swallowed(self, tmp_path):
        db_path = str(tmp_path / "v.db")
        store = SQLiteUserMemoryVectorStore(db_path)  # _ensure_tables uses real sqlite

        fake_conn = MagicMock()
        # PRAGMA execute raises a RECOVERABLE error -> except branch taken.
        fake_conn.execute.side_effect = RuntimeError("pragma boom")
        with patch(f"{MODPATH}.connect_sqlite", return_value=fake_conn):
            got = store._get_conn()
        assert got is fake_conn
        # row_factory still reset despite the pragma failure.
        assert fake_conn.row_factory is None


# ---------------------------------------------------------------------------
# _clear_user_memory_vector_app_singletons  (lines 396-402)
# ---------------------------------------------------------------------------


class TestClearAppSingletons:
    def test_resets_sibling_service_singletons(self):
        import app.application.user_memory_vector_app_service as um

        # Seed live singletons, then assert the helper nulls them out.
        with (
            patch.object(um, "_user_memory_vector_ingest_service", object()),
            patch.object(um, "_user_memory_rag_service", object()),
        ):
            mod._clear_user_memory_vector_app_singletons()
            assert um._user_memory_vector_ingest_service is None
            assert um._user_memory_rag_service is None

    def test_import_failure_is_swallowed(self):
        # Force the inner import to raise a RECOVERABLE error -> debug log branch.
        with patch(
            "builtins.__import__",
            side_effect=ImportError("no module"),
        ):
            # Must not raise.
            mod._clear_user_memory_vector_app_singletons()


# ---------------------------------------------------------------------------
# get_user_memory_pg_vector_store rebind / dispose path  (lines 437-444)
# ---------------------------------------------------------------------------


class TestGetPgVectorStoreRebind:
    def setup_method(self):
        self._saved_instance = mod._user_memory_pg_vector_store_instance
        self._saved_url = mod._user_memory_pg_bound_url

    def teardown_method(self):
        mod._user_memory_pg_vector_store_instance = self._saved_instance
        mod._user_memory_pg_bound_url = self._saved_url

    def test_first_construction_binds_url(self):
        mod._user_memory_pg_vector_store_instance = None
        mod._user_memory_pg_bound_url = None
        sentinel = MagicMock(name="pg_store")
        with (
            patch.dict(
                os.environ,
                {"VECTOR_DB_URL": "postgresql+psycopg://u:p@h/db"},
                clear=False,
            ),
            patch(
                "app.db.database_url_for_active_extension",
                return_value="postgresql+psycopg://u:p@h/db_ext",
            ),
            patch(f"{MODPATH}.PgUserMemoryVectorStore", return_value=sentinel) as ctor,
        ):
            got = mod.get_user_memory_pg_vector_store()
        assert got is sentinel
        ctor.assert_called_once_with(database_url="postgresql+psycopg://u:p@h/db_ext")
        assert mod._user_memory_pg_bound_url == "postgresql+psycopg://u:p@h/db_ext"

    def test_rebind_disposes_old_engine_and_clears_singletons(self):
        # Existing instance bound to a different URL -> dispose + clear + rebuild.
        old = MagicMock(name="old_store")
        mod._user_memory_pg_vector_store_instance = old
        mod._user_memory_pg_bound_url = "postgresql+psycopg://u:p@h/old"
        new_store = MagicMock(name="new_store")

        with (
            patch.dict(
                os.environ,
                {"VECTOR_DB_URL": "postgresql+psycopg://u:p@h/base"},
                clear=False,
            ),
            patch(
                "app.db.database_url_for_active_extension",
                return_value="postgresql+psycopg://u:p@h/new",
            ),
            patch(f"{MODPATH}.PgUserMemoryVectorStore", return_value=new_store),
            patch(f"{MODPATH}._clear_user_memory_vector_app_singletons") as clear_fn,
        ):
            got = mod.get_user_memory_pg_vector_store()

        old._engine.dispose.assert_called_once()
        clear_fn.assert_called_once()
        assert got is new_store
        assert mod._user_memory_pg_bound_url == "postgresql+psycopg://u:p@h/new"

    def test_rebind_swallows_dispose_failure(self):
        old = MagicMock(name="old_store")
        old._engine.dispose.side_effect = RuntimeError("dispose boom")
        mod._user_memory_pg_vector_store_instance = old
        mod._user_memory_pg_bound_url = "postgresql+psycopg://u:p@h/old"
        new_store = MagicMock(name="new_store")

        with (
            patch.dict(
                os.environ,
                {"VECTOR_DB_URL": "postgresql+psycopg://u:p@h/base"},
                clear=False,
            ),
            patch(
                "app.db.database_url_for_active_extension",
                return_value="postgresql+psycopg://u:p@h/new",
            ),
            patch(f"{MODPATH}.PgUserMemoryVectorStore", return_value=new_store),
            patch(f"{MODPATH}._clear_user_memory_vector_app_singletons"),
        ):
            got = mod.get_user_memory_pg_vector_store()
        # dispose raised but was swallowed; rebuild still happened.
        assert got is new_store

    def test_reuse_existing_when_url_unchanged(self):
        existing = MagicMock(name="existing")
        mod._user_memory_pg_vector_store_instance = existing
        mod._user_memory_pg_bound_url = "postgresql+psycopg://u:p@h/same"
        with (
            patch.dict(
                os.environ,
                {"VECTOR_DB_URL": "postgresql+psycopg://u:p@h/base"},
                clear=False,
            ),
            patch(
                "app.db.database_url_for_active_extension",
                return_value="postgresql+psycopg://u:p@h/same",
            ),
            patch(f"{MODPATH}.PgUserMemoryVectorStore") as ctor,
        ):
            got = mod.get_user_memory_pg_vector_store()
        assert got is existing
        ctor.assert_not_called()


# ---------------------------------------------------------------------------
# get_user_memory_vector_store fallback selection  (lines 451-458)
# ---------------------------------------------------------------------------


class TestGetVectorStoreSelection:
    def setup_method(self):
        self._saved = mod._user_memory_vector_store_instance

    def teardown_method(self):
        mod._user_memory_vector_store_instance = self._saved

    def test_sqlite_fallback_when_enabled(self):
        mod._user_memory_vector_store_instance = None
        sentinel = object()
        with (
            patch.dict(os.environ, {"ENABLE_SQLITE_VECTOR_FALLBACK": "1"}, clear=False),
            patch(
                f"{MODPATH}.get_user_memory_sqlite_vector_store",
                return_value=sentinel,
            ) as sqlite_fn,
        ):
            got = mod.get_user_memory_vector_store()
        assert got is sentinel
        sqlite_fn.assert_called_once()

    def test_sqlite_fallback_reuses_cached_instance(self):
        cached = object()
        mod._user_memory_vector_store_instance = cached
        with (
            patch.dict(os.environ, {"ENABLE_SQLITE_VECTOR_FALLBACK": "1"}, clear=False),
            patch(f"{MODPATH}.get_user_memory_sqlite_vector_store") as sqlite_fn,
        ):
            got = mod.get_user_memory_vector_store()
        assert got is cached
        sqlite_fn.assert_not_called()

    def test_pg_when_fallback_disabled(self):
        sentinel = object()
        with (
            patch.dict(os.environ, {"ENABLE_SQLITE_VECTOR_FALLBACK": "0"}, clear=False),
            patch(
                f"{MODPATH}.get_user_memory_pg_vector_store",
                return_value=sentinel,
            ) as pg_fn,
        ):
            got = mod.get_user_memory_vector_store()
        assert got is sentinel
        pg_fn.assert_called_once()
