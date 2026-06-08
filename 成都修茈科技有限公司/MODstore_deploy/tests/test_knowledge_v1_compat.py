"""v1 知识库门面（knowledge_vector_store.py）走 Chroma 后端的兼容性测试。

确保 ``upsert_document/list_documents/delete_document/search/status`` 的返回形态
与历史 RediSearch 实现保持一致，让 ``knowledge_vector_api.py`` 与前端无感切换。
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


def _bootstrap(tmp_path: Path, monkeypatch):
    try:
        import chromadb  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("chromadb 未安装；跳过 v1 兼容测试")

    monkeypatch.setenv("MODSTORE_VECTOR_BACKEND", "chroma")
    monkeypatch.setenv("MODSTORE_VECTOR_DB_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))

    import modstore_server.knowledge_vector_store as kv
    import modstore_server.models as models
    import modstore_server.vector_engine as ve

    models._engine = None
    models._SessionFactory = None
    importlib.reload(ve)
    importlib.reload(kv)
    ve.reset_client_for_tests()
    models.init_db()
    return models, ve, kv


def test_upsert_list_search_delete_round_trip(tmp_path, monkeypatch):
    models, ve, kv = _bootstrap(tmp_path, monkeypatch)

    user_id = 1234
    raw = b"hello world"
    doc_id = kv.make_doc_id(user_id, "n.md", raw)

    chunks = ["alpha bravo charlie", "delta echo foxtrot"]
    vectors = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ]
    metas = [{"page_no": 1}, {"page_no": 2}]

    res = kv.upsert_document(
        user_id=user_id,
        doc_id=doc_id,
        filename="n.md",
        size_bytes=len(raw),
        chunks=chunks,
        embeddings=vectors,
        chunk_metas=metas,
    )
    assert res["doc_id"] == doc_id
    assert res["chunk_count"] == 2

    docs = kv.list_documents(user_id)
    assert len(docs) == 1
    assert docs[0]["doc_id"] == doc_id
    assert docs[0]["filename"] == "n.md"
    assert docs[0]["chunk_count"] == 2

    items = kv.search(user_id, vectors[0], limit=2)
    assert items
    top = items[0]
    assert top["doc_id"] == doc_id
    assert top["filename"] == "n.md"
    assert top["page_no"] in (1, 2)
    assert "alpha" in top["content"]

    assert kv.delete_document(user_id, doc_id) is True
    assert kv.list_documents(user_id) == []
    assert kv.search(user_id, vectors[0], limit=2) == []


def test_upsert_replaces_existing_doc(tmp_path, monkeypatch):
    models, ve, kv = _bootstrap(tmp_path, monkeypatch)
    user_id = 7
    raw = b"x"
    doc_id = kv.make_doc_id(user_id, "f.txt", raw)

    kv.upsert_document(
        user_id=user_id,
        doc_id=doc_id,
        filename="f.txt",
        size_bytes=1,
        chunks=["one", "two", "three"],
        embeddings=[[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]],
    )
    assert kv.list_documents(user_id)[0]["chunk_count"] == 3

    kv.upsert_document(
        user_id=user_id,
        doc_id=doc_id,
        filename="f.txt",
        size_bytes=1,
        chunks=["only"],
        embeddings=[[1.0, 0.0]],
    )
    docs = kv.list_documents(user_id)
    assert len(docs) == 1
    assert docs[0]["chunk_count"] == 1


def test_status_reports_chroma_backend(tmp_path, monkeypatch):
    models, ve, kv = _bootstrap(tmp_path, monkeypatch)
    info = kv.status()
    assert info["backend"] == "chroma"
    assert info["ready"] is True
    assert info["chunks"] == 0


def test_make_doc_id_stable(tmp_path, monkeypatch):
    _, _, kv = _bootstrap(tmp_path, monkeypatch)
    a = kv.make_doc_id(1, "n.md", b"x")
    b = kv.make_doc_id(1, "n.md", b"x")
    c = kv.make_doc_id(2, "n.md", b"x")
    assert a == b
    assert a != c
    assert len(a) == 24
