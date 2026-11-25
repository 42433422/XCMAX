from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application import dataset_rag_app_service as dataset_rag_module
from app.application.dataset_rag_app_service import (
    DatasetAccessContext,
    DatasetRagApplicationService,
)
from app.application.persy_memory_app_service import PersyMemoryApplicationService
from app.domain.shared_services.user_memory_service import UserMemoryService, UserMemoryStore
from app.fastapi_routes.knowledge_v1 import router as knowledge_router
from app.middleware.csrf import CSRFMiddleware
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client(actor) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_router)
    app.add_middleware(CSRFMiddleware)
    client = TestClient(app, raise_server_exceptions=False, headers=actor.headers)
    client.get("/api/knowledge/v1/health")
    client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
    return client


def _access(*, actor: str = "7", tenant: str = "2") -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id=actor,
        tenant_id=tenant,
        permissions=frozenset({"dataset.read", "dataset.write"}),
    )


def _memory_service() -> PersyMemoryApplicationService:
    UserMemoryStore._instance = None
    UserMemoryService._instance = None
    return PersyMemoryApplicationService(UserMemoryService(storage_type="memory"))


def test_persy_memory_routes_cover_review_query_graph_and_delete(tmp_path, trusted_actor) -> None:
    client = _client(
        trusted_actor(user_id=7, tenant_id=2, permissions=["dataset.read", "dataset.write"])
    )
    reader = _client(
        trusted_actor(user_id=8, tenant_id=2, role="reader", permissions=["dataset.read"])
    )
    memories = _memory_service()
    datasets = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "datasets.json",
    )
    captured = memories.capture_conversation_turn(
        access_context=_access(),
        user_message="客户北辰科技的负责人是李明",
        session_id="route-chat",
    )
    memory_id = captured["candidates"][0]["memory_id"]
    datasets.ingest_document(
        dataset_id="persy-knowledge",
        source="续约制度.md",
        text="北辰科技续约需要财务审批。",
        chunk_strategy="fixed",
        access_context=_access(),
    )

    with (
        patch(
            "app.fastapi_routes.knowledge_v1._persy_memory_service",
            return_value=memories,
        ),
        patch.dict(
            "os.environ",
            DATASET_RAG_STORE_PATH=str(tmp_path / "datasets.json"),
            XCAGI_KB_ANSWER_LLM="0",
        ),
        patch.object(dataset_rag_module, "_dataset_rag_app_service", None),
    ):
        pending = client.get(
            "/api/knowledge/v1/datasets/persy-knowledge/memories?status=pending",
        )
        denied = reader.post(
            f"/api/knowledge/v1/datasets/persy-knowledge/memories/{memory_id}/confirm",
            json={},
        )
        confirmed = client.post(
            f"/api/knowledge/v1/datasets/persy-knowledge/memories/{memory_id}/confirm",
            json={},
        )
        query = client.post(
            "/api/knowledge/v1/datasets/persy-knowledge/memories/query",
            json={"query": "北辰科技负责人", "top_k": 3},
        )
        unified_query = client.post(
            "/api/knowledge/v1/datasets/persy-knowledge/query",
            json={"query": "北辰科技负责人和续约要求", "top_k": 3},
        )
        graph = client.get(
            "/api/knowledge/v1/datasets/persy-knowledge/graph?limit=80",
        )
        deleted = client.delete(
            f"/api/knowledge/v1/datasets/persy-knowledge/memories/{memory_id}?reason=obsolete",
        )

    assert pending.status_code == 200
    assert pending.json()["summary"]["pending"] == 1
    assert denied.status_code == 403
    assert denied.json()["required_permission"] == "dataset.write"
    assert confirmed.status_code == 200
    assert confirmed.json()["memory"]["status"] == "active"
    assert query.status_code == 200
    assert query.json()["chunks"][0]["metadata"]["memory_id"] == memory_id
    assert unified_query.status_code == 200, unified_query.text
    assert unified_query.json()["persy_memory"]["count"] == 1
    assert any(
        chunk["metadata"].get("memory_id") == memory_id for chunk in unified_query.json()["chunks"]
    )
    assert any(chunk["metadata"].get("document_id") for chunk in unified_query.json()["chunks"])
    assert "已确认的长期记忆" in unified_query.json()["answer"]
    assert graph.status_code == 200
    assert graph.json()["stats"]["memory_count"] == 1
    assert any(node["id"] == f"memory:{memory_id}" for node in graph.json()["nodes"])
    assert deleted.status_code == 200
    assert deleted.json()["memory"]["status"] == "deleted"


def test_persy_memory_routes_fail_closed_across_users_and_datasets(trusted_actor) -> None:
    alice, bob = (
        _client(
            trusted_actor(
                user_id=user_id, tenant_id=2, permissions=["dataset.read", "dataset.write"]
            )
        )
        for user_id in (7, 8)
    )
    memories = _memory_service()
    captured = memories.capture_conversation_turn(
        access_context=_access(),
        user_message="我偏好下午沟通",
    )
    memory_id = captured["candidates"][0]["memory_id"]

    with patch("app.fastapi_routes.knowledge_v1._persy_memory_service", return_value=memories):
        other_user = bob.post(
            f"/api/knowledge/v1/datasets/persy-knowledge/memories/{memory_id}/confirm", json={}
        )
        unsupported = alice.get("/api/knowledge/v1/datasets/not-persy/memories")

    assert other_user.status_code == 404
    assert other_user.json()["error_code"] == "persy_memory_not_found"
    assert unsupported.status_code == 404
    assert unsupported.json()["error_code"] == "persy_dataset_required"


def test_admin_header_defaults_to_its_tenant_for_query(tmp_path, trusted_actor) -> None:
    client, other_tenant = (
        _client(
            trusted_actor(
                tenant_id=tenant_id,
                role="dataset-admin",
                permissions=["dataset.read", "dataset.admin"],
            )
        )
        for tenant_id in (2, 3)
    )
    datasets = DatasetRagApplicationService(
        embedder=None,
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "datasets.json",
    )
    admin = DatasetAccessContext(
        actor_id="admin",
        permissions=frozenset({"dataset.admin"}),
        is_admin=True,
    )
    datasets.ingest_document(
        dataset_id="secure-admin",
        source="a.md",
        text="Tenant A only.",
        tenant_id="2",
        chunk_strategy="fixed",
        access_context=admin,
    )
    datasets.ingest_document(
        dataset_id="secure-admin",
        source="b.md",
        text="Tenant B only.",
        tenant_id="3",
        chunk_strategy="fixed",
        access_context=admin,
    )
    # The real spawned query worker must reopen the same persisted data as GET.
    # An in-process getter mock is not inherited across a spawn boundary.
    with (
        patch.dict(
            "os.environ",
            DATASET_RAG_STORE_PATH=str(tmp_path / "datasets.json"),
            XCAGI_KB_ANSWER_LLM="0",
        ),
        patch.object(dataset_rag_module, "_dataset_rag_app_service", None),
    ):
        status = client.get(
            "/api/knowledge/v1/datasets/secure-admin/status",
        )
        query = client.post(
            "/api/knowledge/v1/datasets/secure-admin/query",
            json={"query": "Tenant", "top_k": 5},
        )
        scoped_query = client.post(
            "/api/knowledge/v1/datasets/secure-admin/query",
            json={"query": "Tenant", "top_k": 5, "tenant_id": "3"},
        )
        other_query = other_tenant.post(
            "/api/knowledge/v1/datasets/secure-admin/query", json={"query": "Tenant", "top_k": 5}
        )

    assert status.status_code == query.status_code == scoped_query.status_code == 200, query.text
    assert other_query.status_code == 200, other_query.text
    assert status.json()["document_count"] == 2
    assert status.json()["tenant_ids"] == ["2", "3"]
    # Catalog status spans tenants, but the query's tenant comes from the session.
    assert {row["metadata"]["tenant_id"] for row in query.json()["chunks"]} == {"2"}
    assert {row["metadata"]["tenant_id"] for row in scoped_query.json()["chunks"]} == {"2"}
    assert {row["metadata"]["tenant_id"] for row in other_query.json()["chunks"]} == {"3"}
