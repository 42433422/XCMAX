"""knowledge_v2_api 集合/文档/共享/检索 路由测试。"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def kb_v2_client(tmp_path: Path, monkeypatch):
    try:
        import chromadb  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("chromadb 未安装；跳过 knowledge_v2_api 测试")

    monkeypatch.setenv("MODSTORE_VECTOR_BACKEND", "chroma")
    monkeypatch.setenv("MODSTORE_VECTOR_DB_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))
    monkeypatch.setenv("MODSTORE_EMBEDDING_API_KEY", "test-key")

    import modstore_server.knowledge_v2_api as kv2
    import modstore_server.models as models
    import modstore_server.rag_service as rag
    import modstore_server.vector_engine as ve

    models._engine = None
    models._SessionFactory = None
    importlib.reload(ve)
    importlib.reload(rag)
    importlib.reload(kv2)
    ve.reset_client_for_tests()
    models.init_db()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(kv2.router)

    from modstore_server.api.deps import _get_current_user

    user_holder: dict = {"user": None}

    def _fake_user():
        u = user_holder["user"]
        if u is None:
            raise AssertionError("no user set")
        return u

    app.dependency_overrides[_get_current_user] = _fake_user

    class FakeUser:
        def __init__(self, uid: int, is_admin: bool = False):
            self.id = uid
            self.is_admin = is_admin

    return {
        "client": TestClient(app),
        "user_holder": user_holder,
        "FakeUser": FakeUser,
        "models": models,
        "ve": ve,
    }


def test_status_and_create_collection(kb_v2_client):
    cli = kb_v2_client["client"]
    user_holder = kb_v2_client["user_holder"]
    FakeUser = kb_v2_client["FakeUser"]

    user_holder["user"] = FakeUser(uid=1)
    r = cli.get("/api/knowledge/v2/status")
    assert r.status_code == 200, r.text
    assert r.json()["engine"]["backend"] == "chroma"

    r = cli.post(
        "/api/knowledge/v2/collections",
        json={"name": "我的资料库", "description": "test"},
    )
    assert r.status_code == 200, r.text
    coll = r.json()["collection"]
    assert coll["owner_kind"] == "user"
    assert coll["owner_id"] == "1"
    assert coll["name"] == "我的资料库"

    r = cli.get("/api/knowledge/v2/collections")
    assert r.status_code == 200
    rows = r.json()["collections"]
    assert any(c["id"] == coll["id"] for c in rows)


def test_collection_isolation_between_users(kb_v2_client):
    cli = kb_v2_client["client"]
    user_holder = kb_v2_client["user_holder"]
    FakeUser = kb_v2_client["FakeUser"]

    user_holder["user"] = FakeUser(uid=1)
    r = cli.post("/api/knowledge/v2/collections", json={"name": "u1-kb"})
    coll_u1 = r.json()["collection"]

    user_holder["user"] = FakeUser(uid=2)
    r = cli.get("/api/knowledge/v2/collections")
    rows = r.json()["collections"]
    assert all(c["id"] != coll_u1["id"] for c in rows)

    r = cli.get(f"/api/knowledge/v2/collections/{coll_u1['id']}/documents")
    assert r.status_code == 403


def test_share_then_visible_to_grantee(kb_v2_client):
    cli = kb_v2_client["client"]
    user_holder = kb_v2_client["user_holder"]
    FakeUser = kb_v2_client["FakeUser"]

    user_holder["user"] = FakeUser(uid=1)
    coll = cli.post("/api/knowledge/v2/collections", json={"name": "shared-kb"}).json()[
        "collection"
    ]

    r = cli.post(
        f"/api/knowledge/v2/collections/{coll['id']}/share",
        json={"grantee_kind": "user", "grantee_id": "2", "permission": "read"},
    )
    assert r.status_code == 200, r.text

    user_holder["user"] = FakeUser(uid=2)
    rows = cli.get("/api/knowledge/v2/collections").json()["collections"]
    assert any(c["id"] == coll["id"] for c in rows)

    r = cli.get(f"/api/knowledge/v2/collections/{coll['id']}/documents")
    assert r.status_code == 200

    r = cli.delete(f"/api/knowledge/v2/collections/{coll['id']}")
    assert r.status_code == 403


def test_delete_collection_drops_engine_collection(kb_v2_client):
    cli = kb_v2_client["client"]
    user_holder = kb_v2_client["user_holder"]
    FakeUser = kb_v2_client["FakeUser"]
    ve = kb_v2_client["ve"]

    user_holder["user"] = FakeUser(uid=1)
    coll = cli.post("/api/knowledge/v2/collections", json={"name": "tmp"}).json()["collection"]

    ve.upsert(
        ve.kb_collection_name(int(coll["id"])),
        ids=["a:0"],
        embeddings=[[1.0, 0.0, 0.0]],
        documents=["hello"],
        metadatas=[{"doc_id": "a", "filename": "t.txt"}],
    )
    assert ve.count(ve.kb_collection_name(int(coll["id"]))) == 1

    r = cli.delete(f"/api/knowledge/v2/collections/{coll['id']}")
    assert r.status_code == 200

    assert ve.count(ve.kb_collection_name(int(coll["id"]))) == 0


def test_retrieve_returns_only_authorized(kb_v2_client):
    cli = kb_v2_client["client"]
    user_holder = kb_v2_client["user_holder"]
    FakeUser = kb_v2_client["FakeUser"]
    ve = kb_v2_client["ve"]

    user_holder["user"] = FakeUser(uid=1)
    mine = cli.post("/api/knowledge/v2/collections", json={"name": "mine"}).json()["collection"]

    user_holder["user"] = FakeUser(uid=2)
    other = cli.post("/api/knowledge/v2/collections", json={"name": "other"}).json()["collection"]

    ve.upsert(
        ve.kb_collection_name(int(mine["id"])),
        ids=["m:0"],
        embeddings=[[1.0, 0.0, 0.0]],
        documents=["mine-content"],
        metadatas=[{"doc_id": "m", "filename": "m.txt"}],
    )
    ve.upsert(
        ve.kb_collection_name(int(other["id"])),
        ids=["o:0"],
        embeddings=[[1.0, 0.0, 0.0]],
        documents=["other-content"],
        metadatas=[{"doc_id": "o", "filename": "o.txt"}],
    )

    user_holder["user"] = FakeUser(uid=1)

    async def _fake_embed(texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    import modstore_server.rag_service as rag

    rag.embed_texts = _fake_embed  # type: ignore[assignment]

    r = cli.post(
        "/api/knowledge/v2/retrieve",
        json={"query": "anything", "top_k": 5},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    contents = [it["content"] for it in items]
    assert "mine-content" in contents
    assert "other-content" not in contents
