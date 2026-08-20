from __future__ import annotations

import builtins
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from modstore_server import vector_engine


def test_supported_host_sqlite_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    original = sys.modules["sqlite3"]
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 40, 1))

    vector_engine._prepare_sqlite_for_chroma()

    assert sys.modules["sqlite3"] is original


def test_old_host_sqlite_uses_packaged_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    packaged = SimpleNamespace(sqlite_version="3.51.1", sqlite_version_info=(3, 51, 1))
    monkeypatch.setitem(sys.modules, "sqlite3", sqlite3)
    monkeypatch.setattr(sqlite3, "sqlite_version", "3.26.0")
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 26, 0))
    monkeypatch.setitem(sys.modules, "pysqlite3", packaged)

    vector_engine._prepare_sqlite_for_chroma()

    assert sys.modules["sqlite3"] is packaged


def test_old_host_sqlite_fails_with_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def missing_pysqlite(name, *args, **kwargs):
        if name == "pysqlite3":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "sqlite_version", "3.26.0")
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 26, 0))
    monkeypatch.delitem(sys.modules, "pysqlite3", raising=False)
    monkeypatch.setattr(builtins, "__import__", missing_pysqlite)

    with pytest.raises(vector_engine.VectorEngineError, match="pysqlite3-binary"):
        vector_engine._prepare_sqlite_for_chroma()
