"""统一向量引擎（vector_engine.py）基础行为测试。

测试用 ``MODSTORE_VECTOR_DB_DIR`` 隔离每个测试的持久化目录，
避免污染开发者本机的 modstore_server/data/chroma。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _import_engine_with_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MODSTORE_VECTOR_DB_DIR", str(tmp_path / "chroma"))
    from modstore_server import vector_engine

    importlib.reload(vector_engine)
    vector_engine.reset_client_for_tests()
    return vector_engine


def _skip_if_no_chroma():
    try:
        import chromadb  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("chromadb 未安装；跳过引擎测试")


def test_vector_engine_status_ready(tmp_path, monkeypatch):
    _skip_if_no_chroma()
    ve = _import_engine_with_dir(monkeypatch, tmp_path)
    info = ve.status()
    assert info["backend"] == "chroma"
    assert info["ready"] is True
    assert info["error"] == ""
    assert info["persist_dir"].endswith("chroma")


def test_upsert_query_delete_count(tmp_path, monkeypatch):
    _skip_if_no_chroma()
    ve = _import_engine_with_dir(monkeypatch, tmp_path)
    coll = ve.kb_collection_name(42)

    ids = [f"d:0:{i}" for i in range(3)]
    vectors = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
    ]
    docs = ["alpha bravo", "charlie delta", "echo foxtrot"]
    metas = [{"doc_id": "d", "chunk_index": i, "page_no": i + 1} for i in range(3)]

    n = ve.upsert(coll, ids=ids, embeddings=vectors, documents=docs, metadatas=metas)
    assert n == 3
    assert ve.count(coll) == 3

    res = ve.query(coll, query_embedding=vectors[0], top_k=2)
    assert len(res) == 2
    assert res[0]["id"] == ids[0]
    assert res[0]["document"].startswith("alpha")
    assert res[0]["metadata"]["doc_id"] == "d"

    deleted = ve.delete(coll, where={"page_no": 1})
    assert deleted == 1
    assert ve.count(coll) == 2


def test_query_against_missing_collection_returns_empty(tmp_path, monkeypatch):
    _skip_if_no_chroma()
    ve = _import_engine_with_dir(monkeypatch, tmp_path)
    res = ve.query("kb_999999", query_embedding=[0.0] * 4, top_k=3)
    assert res == []


def test_drop_collection(tmp_path, monkeypatch):
    _skip_if_no_chroma()
    ve = _import_engine_with_dir(monkeypatch, tmp_path)
    name = ve.kb_collection_name(7)
    ve.upsert(
        name,
        ids=["x"],
        embeddings=[[1.0, 0.0, 0.0]],
        documents=["t"],
        metadatas=[{"k": "v"}],
    )
    assert ve.count(name) == 1
    assert ve.drop_collection(name) is True
    assert ve.count(name) == 0
