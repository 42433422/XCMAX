"""Entity context must not turn a caller-selected ID into a knowledge principal."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modstore_server import auth_service, knowledge_v2_api, models, rag_service

_CONTEXTS = [
    ({"employee_id": "private-pack"}, {104, 107}),
    ({"workflow_id": 701}, {105, 108}),
    ({"org_id": "org-private"}, {106, 109}),
]


@pytest.fixture
def knowledge_access(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    tables = [
        models.User,
        models.CatalogItem,
        models.Purchase,
        models.Entitlement,
        models.PlanTemplate,
        models.UserPlan,
        models.Workflow,
        models.KnowledgeCollection,
        models.KnowledgeMembership,
    ]
    models.Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    sf = sessionmaker(bind=engine, expire_on_commit=False)
    with sf() as session:
        session.add_all(
            models.User(
                id=uid,
                username=f"knowledge-user-{uid}",
                password_hash="external-jwt",
                is_admin=uid in (3, 5),
                deleted_at=datetime.now(UTC) if uid == 5 else None,
            )
            for uid in range(1, 7)
        )
        session.flush()
        for cid, pkg, public in [(21, "private-pack", False), (22, "public-pack", True)]:
            session.add(
                models.CatalogItem(
                    id=cid,
                    pkg_id=pkg,
                    version="1.0.0",
                    name=pkg,
                    author_id=1,
                    artifact="employee_pack",
                    is_public=public,
                    price=0 if public else 10,
                )
            )
        session.add(models.Workflow(id=701, user_id=1, name="private-workflow"))
        for cid, kind, owner, public in [
            (101, "user", "1", False),
            (102, "user", "2", False),
            (103, "user", "1", True),
            (104, "employee", "private-pack", False),
            (105, "workflow", "701", False),
            (106, "org", "org-private", False),
            (107, "user", "6", False),
            (108, "user", "6", False),
            (109, "user", "6", False),
            (110, "user", "1", False),
            (111, "employee", "public-pack", False),
        ]:
            session.add(
                models.KnowledgeCollection(
                    id=cid,
                    owner_kind=kind,
                    owner_id=owner,
                    name=f"knowledge-{cid}",
                    visibility="public" if public else "private",
                )
            )
        session.flush()
        for cid, kind, grantee in [
            (107, "employee", "private-pack"),
            (108, "workflow", "701"),
            (109, "org", "org-private"),
            (110, "user", "2"),
        ]:
            session.add(
                models.KnowledgeMembership(
                    collection_id=cid,
                    grantee_kind=kind,
                    grantee_id=grantee,
                    permission="read",
                )
            )
        session.commit()

    async def embed(texts, **kwargs):
        return [[1.0, 0.0, 0.0] for _ in texts]

    queried = []

    def query(name, **kwargs):
        queried.append(name)
        return [
            {
                "id": "chunk-1",
                "document": f"private evidence from {name}",
                "distance": 0.1,
                "metadata": {"doc_id": "doc-1", "filename": "private.txt"},
            }
        ]

    for module in (auth_service, knowledge_v2_api, rag_service):
        monkeypatch.setattr(module, "get_session_factory", lambda: sf)
    monkeypatch.setattr(rag_service, "embed_texts", embed)
    monkeypatch.setattr(rag_service.vector_engine, "query", query)
    monkeypatch.setenv("MODSTORE_RAG_RETRIEVAL_MODE", "vector")
    monkeypatch.setenv("MODSTORE_RAG_RERANK", "")
    app = FastAPI()
    app.include_router(knowledge_v2_api.router)

    def headers(uid):
        token = auth_service.create_access_token(uid, f"knowledge-user-{uid}")
        return {"Authorization": f"Bearer {token}"}

    try:
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, sf=sf, headers=headers, queried=queried)
    finally:
        engine.dispose()


@pytest.mark.parametrize("context, private_ids", _CONTEXTS)
def test_http_retrieve_rejects_foreign_entity_context(knowledge_access, context, private_ids):
    state = knowledge_access
    response = state.client.post(
        "/api/knowledge/v2/retrieve",
        headers=state.headers(2),
        json={"query": "private evidence", "top_k": 20, **context},
    )
    assert response.status_code == 200
    assert {item["collection_id"] for item in response.json()["items"]} == {102, 103, 110}
    assert not {f"kb_{cid}" for cid in private_ids}.intersection(state.queried)


@pytest.mark.parametrize("context, private_ids", _CONTEXTS)
def test_selected_collection_ids_do_not_bypass_context_check(
    knowledge_access, context, private_ids
):
    state = knowledge_access
    response = state.client.post(
        "/api/knowledge/v2/retrieve",
        headers=state.headers(2),
        json={"query": "private evidence", "collection_ids": sorted(private_ids), **context},
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}
    assert state.queried == []


@pytest.mark.parametrize("context, private_ids", _CONTEXTS[:2])
def test_entity_ownership_is_not_a_knowledge_grant(knowledge_access, context, private_ids):
    state = knowledge_access
    response = state.client.post(
        "/api/knowledge/v2/retrieve",
        headers=state.headers(1),
        json={"query": "private evidence", "collection_ids": sorted(private_ids), **context},
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}
    assert state.queried == []


@pytest.mark.parametrize("context, private_ids", _CONTEXTS)
def test_platform_admin_keeps_entity_knowledge_access(knowledge_access, context, private_ids):
    state = knowledge_access
    response = state.client.post(
        "/api/knowledge/v2/retrieve",
        headers=state.headers(3),
        json={"query": "private evidence", "collection_ids": sorted(private_ids), **context},
    )
    assert response.status_code == 200
    assert {item["collection_id"] for item in response.json()["items"]} == private_ids


@pytest.mark.parametrize("context, private_ids", _CONTEXTS[:2])
def test_workflow_node_cannot_assert_another_entity_identity(
    knowledge_access, context, private_ids
):
    from modstore_server.workflow_engine import WorkflowEngine

    result = WorkflowEngine()._execute_knowledge_search_node(
        SimpleNamespace(name="knowledge-node"),
        {},
        {"query": "private evidence", "collection_ids": sorted(private_ids), **context},
        user_id=2,
    )
    assert result["knowledge"]["items"] == []
    assert result["knowledge"]["count"] == 0
    assert "error" not in result["knowledge"]
    assert knowledge_access.queried == []


@pytest.mark.parametrize("context, private_ids", _CONTEXTS)
@pytest.mark.parametrize("permission", ["read", "write", "admin"])
def test_collection_permission_helper_does_not_trust_context(
    knowledge_access, context, private_ids, permission
):
    with knowledge_access.sf() as session:
        for cid in private_ids:
            assert not rag_service.can_access_collection(
                session, collection_id=cid, user_id=2, permission=permission, **context
            )


@pytest.mark.parametrize("uid", [0, 5, 999])
def test_missing_or_deleted_principal_cannot_inherit_entity_knowledge(knowledge_access, uid):
    with knowledge_access.sf() as session:
        # Missing callers cannot be persisted as FK-backed entity owners.
        if session.get(models.User, uid) is not None:
            session.query(models.CatalogItem).filter_by(id=21).update({"author_id": uid})
            session.query(models.Workflow).filter_by(id=701).update({"user_id": uid})
            session.commit()
        for context, private_ids in _CONTEXTS:
            rows = rag_service.visible_collection_ids(session, user_id=uid, **context)
            assert not private_ids.intersection(int(row.id) for row in rows)


def test_employee_purchase_or_execution_permission_is_not_private_knowledge_grant(knowledge_access):
    state = knowledge_access
    with state.sf() as session:
        session.add(models.Purchase(user_id=4, catalog_id=21, amount=10))
        session.add(models.Entitlement(user_id=4, catalog_id=21, entitlement_type="item"))
        session.add(models.PlanTemplate(id="knowledge-test-plan", name="plan", price=10))
        session.flush()
        session.add(models.UserPlan(user_id=4, plan_id="knowledge-test-plan", is_active=True))
        session.commit()
    for employee_id, private_ids in [("private-pack", [104, 107]), ("public-pack", [111])]:
        response = state.client.post(
            "/api/knowledge/v2/retrieve",
            headers=state.headers(4),
            json={
                "query": "private evidence",
                "employee_id": employee_id,
                "collection_ids": private_ids,
            },
        )
        assert response.status_code == 200
        assert response.json() == {"items": [], "count": 0}
    assert state.queried == []


@pytest.mark.parametrize("context, private_ids", _CONTEXTS)
def test_explicit_user_share_allows_entity_collection_without_entity_identity(
    knowledge_access, context, private_ids
):
    state = knowledge_access
    with state.sf() as session:
        session.add_all(
            models.KnowledgeMembership(
                collection_id=cid, grantee_kind="user", grantee_id="2", permission="read"
            )
            for cid in private_ids
        )
        session.commit()
    response = state.client.post(
        "/api/knowledge/v2/retrieve",
        headers=state.headers(2),
        json={"query": "private evidence", "collection_ids": sorted(private_ids), **context},
    )
    assert response.status_code == 200
    assert {item["collection_id"] for item in response.json()["items"]} == private_ids


def test_new_package_authorship_cannot_claim_existing_knowledge_identity(knowledge_access):
    with knowledge_access.sf() as session:
        session.query(models.CatalogItem).filter_by(id=21).delete()
        session.commit()
        assert not rag_service.can_access_collection(
            session, collection_id=104, user_id=2, employee_id="private-pack"
        )
        session.add(
            models.CatalogItem(
                pkg_id="private-pack",
                version="2.0.0",
                name="Recreated pack",
                artifact="employee_pack",
                author_id=2,
            )
        )
        session.commit()
        assert not rag_service.can_access_collection(
            session, collection_id=104, user_id=2, employee_id="private-pack"
        )


@pytest.mark.parametrize(
    "model, row_id, owner_field, context, cid",
    [
        (models.CatalogItem, 21, "author_id", {"employee_id": "private-pack"}, 104),
        (models.Workflow, 701, "user_id", {"workflow_id": 701}, 105),
    ],
)
def test_entity_owner_change_does_not_transfer_knowledge_grants(
    knowledge_access, model, row_id, owner_field, context, cid
):
    with knowledge_access.sf() as session:
        session.add(
            models.KnowledgeMembership(
                collection_id=cid, grantee_kind="user", grantee_id="1", permission="read"
            )
        )
        session.commit()
        assert rag_service.can_access_collection(session, collection_id=cid, user_id=1, **context)
        session.query(model).filter_by(id=row_id).update({owner_field: 2})
        session.commit()
        assert rag_service.can_access_collection(session, collection_id=cid, user_id=1, **context)
        assert not rag_service.can_access_collection(
            session, collection_id=cid, user_id=2, **context
        )


def test_reused_workflow_id_cannot_inherit_deleted_owners_knowledge(knowledge_access):
    with knowledge_access.sf() as session:
        session.query(models.Workflow).delete()
        original = models.Workflow(user_id=1, name="original")
        session.add(original)
        session.commit()
        old_id = original.id
        session.add(
            models.KnowledgeCollection(
                id=115,
                owner_kind="workflow",
                owner_id=str(old_id),
                name="retained-private-knowledge",
                visibility="private",
            )
        )
        session.delete(original)
        session.commit()
        replacement = models.Workflow(user_id=2, name="replacement")
        session.add(replacement)
        session.commit()
        assert replacement.id == old_id
    response = knowledge_access.client.post(
        "/api/knowledge/v2/retrieve",
        headers=knowledge_access.headers(2),
        json={"query": "private evidence", "collection_ids": [115], "workflow_id": old_id},
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}
    assert knowledge_access.queried == []


def test_explicit_user_grant_revocation_is_checked_again(knowledge_access):
    with knowledge_access.sf() as session:
        grant = models.KnowledgeMembership(
            collection_id=104, grantee_kind="user", grantee_id="2", permission="read"
        )
        session.add(grant)
        session.commit()
        assert rag_service.can_access_collection(
            session, collection_id=104, user_id=2, employee_id="private-pack"
        )
        session.delete(grant)
        session.commit()
        assert not rag_service.can_access_collection(
            session, collection_id=104, user_id=2, employee_id="private-pack"
        )


def test_platform_admin_revocation_is_checked_again(knowledge_access):
    with knowledge_access.sf() as session:
        assert rag_service.can_access_collection(
            session, collection_id=106, user_id=3, org_id="org-private"
        )
        session.query(models.User).filter_by(id=3).update({"is_admin": False})
        session.commit()
        assert not rag_service.can_access_collection(
            session, collection_id=106, user_id=3, org_id="org-private"
        )


@pytest.mark.parametrize("employee_id", ["private_pack", "21", "missing-pack"])
def test_unregistered_employee_context_is_not_a_knowledge_identity(knowledge_access, employee_id):
    with knowledge_access.sf() as session:
        session.add(
            models.KnowledgeCollection(
                id=114,
                owner_kind="employee",
                owner_id=employee_id,
                name="unverified-identity",
                visibility="private",
            )
        )
        session.commit()
        assert not rag_service.can_access_collection(
            session, collection_id=114, user_id=1, employee_id=employee_id
        )


@pytest.mark.parametrize("user_id, expected_count", [(1, 1), (2, 0)])
def test_employee_cognition_only_injects_authorized_context(
    knowledge_access, monkeypatch, user_id, expected_count
):
    from modstore_server import employee_executor

    with knowledge_access.sf() as session:
        session.add(
            models.KnowledgeMembership(
                collection_id=104, grantee_kind="user", grantee_id="1", permission="read"
            )
        )
        session.commit()
    captured = {}

    async def chat(session, uid, provider, model, messages, *, max_tokens=None):
        captured["messages"] = messages
        return {"ok": True, "content": "answer", "raw": {}, "usage": {}}

    monkeypatch.setattr(employee_executor, "chat_dispatch_via_session", chat)
    monkeypatch.setattr(
        "modstore_server.llm_key_resolver.resolve_api_key", lambda *args: ("test-key", "test")
    )
    monkeypatch.setattr("modstore_server.llm_key_resolver.resolve_base_url", lambda *args: None)
    result = asyncio.run(
        employee_executor._cognition_real(
            {
                "system_prompt": "Assistant",
                "model": {"provider": "openai", "model_name": "test-model"},
                "knowledge": {"enabled": True, "collection_ids": [104]},
            },
            {"normalized_input": {"task": "lookup"}, "type": "text"},
            {"session": {}, "long_term": None},
            session=None,
            user_id=user_id,
            employee_id="private-pack",
            task="Find the relevant facts",
        )
    )
    assert result["knowledge"]["enabled"] is True
    assert result["knowledge"]["count"] == expected_count
    assert ("private evidence from kb_104" in captured["messages"][0]["content"]) == bool(
        expected_count
    )
