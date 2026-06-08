"""rag_service 单测：可见集合解析、权限、prompt 注入。"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest


def _bootstrap(tmp_path: Path, monkeypatch):
    try:
        import chromadb  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("chromadb 未安装；跳过 rag_service 测试")

    monkeypatch.setenv("MODSTORE_VECTOR_BACKEND", "chroma")
    monkeypatch.setenv("MODSTORE_VECTOR_DB_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))

    import modstore_server.models as models
    import modstore_server.rag_service as rag
    import modstore_server.vector_engine as ve

    models._engine = None
    models._SessionFactory = None
    importlib.reload(ve)
    importlib.reload(rag)
    ve.reset_client_for_tests()
    models.init_db()
    return models, ve, rag


def test_visible_collections_owner_and_grantee(tmp_path, monkeypatch):
    models, ve, rag = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.models import (
        KnowledgeCollection,
        KnowledgeMembership,
        get_session_factory,
    )

    sf = get_session_factory()
    with sf() as session:
        a = KnowledgeCollection(owner_kind="user", owner_id="1", name="my-a", visibility="private")
        b = KnowledgeCollection(
            owner_kind="employee",
            owner_id="emp-x",
            name="emp-x-a",
            visibility="private",
        )
        c = KnowledgeCollection(
            owner_kind="user", owner_id="2", name="other-a", visibility="private"
        )
        d = KnowledgeCollection(
            owner_kind="user", owner_id="2", name="other-public", visibility="public"
        )
        session.add_all([a, b, c, d])
        session.commit()
        for x in (a, b, c, d):
            session.refresh(x)
        session.add(
            KnowledgeMembership(
                collection_id=c.id, grantee_kind="user", grantee_id="1", permission="read"
            )
        )
        session.commit()

    sf = get_session_factory()
    with sf() as session:
        rows = rag.visible_collection_ids(session, user_id=1, employee_id="emp-x")
        names = {r.name for r in rows}
        assert "my-a" in names
        assert "emp-x-a" in names
        assert "other-a" in names  # 通过 grant
        assert "other-public" in names  # 通过 visibility=public

        rows_w = rag.visible_collection_ids(
            session, user_id=1, employee_id="emp-x", permission="write"
        )
        names_w = {r.name for r in rows_w}
        assert "my-a" in names_w
        assert "emp-x-a" in names_w
        assert "other-a" not in names_w  # 仅 read 授权
        assert "other-public" not in names_w  # public 不给写


def test_can_access_collection(tmp_path, monkeypatch):
    models, ve, rag = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.models import KnowledgeCollection, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        my = KnowledgeCollection(
            owner_kind="user", owner_id="42", name="kb-1", visibility="private"
        )
        other = KnowledgeCollection(
            owner_kind="user", owner_id="99", name="other", visibility="private"
        )
        session.add_all([my, other])
        session.commit()
        session.refresh(my)
        session.refresh(other)

        assert rag.can_access_collection(session, collection_id=my.id, user_id=42) is True
        assert rag.can_access_collection(session, collection_id=other.id, user_id=42) is False


def test_inject_rag_into_messages_appends_to_existing_system(tmp_path, monkeypatch):
    models, ve, rag = _bootstrap(tmp_path, monkeypatch)
    chunks = [
        rag.RetrievedChunk(
            collection_id=1,
            collection_name="kb-1",
            owner_kind="user",
            owner_id="1",
            doc_id="d",
            chunk_id="d:0",
            filename="manual.md",
            page_no=3,
            content="Important fact about deployment.",
            distance=0.1,
            score=0.9,
        )
    ]
    msgs = [{"role": "system", "content": "你是助手。"}]
    out = rag.inject_rag_into_messages(msgs, chunks)
    assert out is not msgs
    assert len(out) == 1
    assert out[0]["role"] == "system"
    assert "Important fact about deployment" in out[0]["content"]
    assert "[1] manual.md" in out[0]["content"]
    assert "kb-1" in out[0]["content"]


def test_inject_rag_into_messages_inserts_system(tmp_path, monkeypatch):
    models, ve, rag = _bootstrap(tmp_path, monkeypatch)
    chunks = [
        rag.RetrievedChunk(
            collection_id=2,
            collection_name="kb-2",
            owner_kind="user",
            owner_id="1",
            doc_id="d",
            chunk_id="d:0",
            filename="x.txt",
            page_no=None,
            content="hello",
            distance=0.2,
            score=0.8,
        )
    ]
    msgs = [{"role": "user", "content": "hi"}]
    out = rag.inject_rag_into_messages(msgs, chunks)
    assert len(out) == 2
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "user"


def test_inject_rag_no_chunks_returns_copy(tmp_path, monkeypatch):
    models, ve, rag = _bootstrap(tmp_path, monkeypatch)
    msgs = [{"role": "user", "content": "x"}]
    out = rag.inject_rag_into_messages(msgs, [])
    assert out == msgs
    assert out is not msgs


def test_retrieve_filters_by_visibility(tmp_path, monkeypatch):
    models, ve, rag = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.models import KnowledgeCollection, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        my = KnowledgeCollection(
            owner_kind="user", owner_id="1", name="kb-mine", visibility="private"
        )
        other = KnowledgeCollection(
            owner_kind="user", owner_id="999", name="kb-other", visibility="private"
        )
        session.add_all([my, other])
        session.commit()
        session.refresh(my)
        session.refresh(other)

    ve.upsert(
        ve.kb_collection_name(my.id),
        ids=["d:0"],
        embeddings=[[1.0, 0.0, 0.0]],
        documents=["mine"],
        metadatas=[{"doc_id": "d", "filename": "m.txt"}],
    )
    ve.upsert(
        ve.kb_collection_name(other.id),
        ids=["d:0"],
        embeddings=[[1.0, 0.0, 0.0]],
        documents=["other"],
        metadatas=[{"doc_id": "d", "filename": "o.txt"}],
    )

    chunks = asyncio.run(
        rag.retrieve(
            user_id=1,
            query="anything",
            top_k=5,
            query_embedding=[1.0, 0.0, 0.0],
        )
    )
    assert len(chunks) == 1
    assert chunks[0].content == "mine"
    assert chunks[0].owner_id == "1"


def test_retrieve_with_extra_collection_ids_must_be_visible(tmp_path, monkeypatch):
    models, ve, rag = _bootstrap(tmp_path, monkeypatch)
    from modstore_server.models import KnowledgeCollection, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        my = KnowledgeCollection(owner_kind="user", owner_id="1", name="kb-m", visibility="private")
        forbidden = KnowledgeCollection(
            owner_kind="user", owner_id="999", name="kb-f", visibility="private"
        )
        session.add_all([my, forbidden])
        session.commit()
        session.refresh(my)
        session.refresh(forbidden)

    ve.upsert(
        ve.kb_collection_name(forbidden.id),
        ids=["d:0"],
        embeddings=[[1.0, 0.0, 0.0]],
        documents=["forbidden"],
        metadatas=[{"doc_id": "d", "filename": "f.txt"}],
    )

    chunks = asyncio.run(
        rag.retrieve(
            user_id=1,
            query="x",
            extra_collection_ids=[forbidden.id],
            query_embedding=[1.0, 0.0, 0.0],
        )
    )
    assert chunks == []
