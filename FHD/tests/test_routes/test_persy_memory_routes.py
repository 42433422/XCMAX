from __future__ import annotations

from unittest.mock import patch

import pytest
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


@pytest.fixture(autouse=True)
def _explicit_gateway_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_TRUST_DATASET_ACCESS_HEADERS", "1")


def _headers(*, actor: str = "7", tenant: str = "2", write: bool = True) -> dict[str, str]:
    permissions = "dataset.read,dataset.write" if write else "dataset.read"
    return {
        "X-Dataset-Actor-ID": actor,
        "X-Dataset-Tenant-ID": tenant,
        "X-Dataset-Permissions": permissions,
    }


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


def test_persy_memory_routes_cover_review_query_graph_and_delete(tmp_path) -> None:
    app = FastAPI()
    app.include_router(knowledge_router)
    client = TestClient(app, raise_server_exceptions=False)
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
        patch.dict("os.environ", {"DATASET_RAG_STORE_PATH": str(tmp_path / "datasets.json")}),
        patch.object(dataset_rag_module, "_dataset_rag_app_service", None),
    ):
        pending = client.get(
            "/api/knowledge/v1/datasets/persy-knowledge/memories?status=pending",
            headers=_headers(),
        )
        denied = client.post(
            f"/api/knowledge/v1/datasets/persy-knowledge/memories/{memory_id}/confirm",
            headers=_headers(write=False),
            json={},
        )
        confirmed = client.post(
            f"/api/knowledge/v1/datasets/persy-knowledge/memories/{memory_id}/confirm",
            headers=_headers(),
            json={},
        )
        query = client.post(
            "/api/knowledge/v1/datasets/persy-knowledge/memories/query",
            headers=_headers(),
            json={"query": "北辰科技负责人", "top_k": 3},
        )
        unified_query = client.post(
            "/api/knowledge/v1/datasets/persy-knowledge/query",
            headers=_headers(),
            json={"query": "北辰科技负责人和续约要求", "top_k": 3},
        )
        graph = client.get(
            "/api/knowledge/v1/datasets/persy-knowledge/graph?limit=80",
            headers=_headers(),
        )
        deleted = client.delete(
            f"/api/knowledge/v1/datasets/persy-knowledge/memories/{memory_id}?reason=obsolete",
            headers=_headers(),
        )

    assert pending.status_code == 200
    assert pending.json()["summary"]["pending"] == 1
    assert denied.status_code == 403
    assert denied.json()["required_permission"] == "dataset.write"
    assert confirmed.status_code == 200
    assert confirmed.json()["memory"]["status"] == "active"
    assert query.status_code == 200
    assert query.json()["chunks"][0]["metadata"]["memory_id"] == memory_id
    assert unified_query.status_code == 200
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


def test_persy_memory_routes_fail_closed_across_users_and_datasets() -> None:
    app = FastAPI()
    app.include_router(knowledge_router)
    client = TestClient(app, raise_server_exceptions=False)
    memories = _memory_service()
    captured = memories.capture_conversation_turn(
        access_context=_access(actor="alice"),
        user_message="我偏好下午沟通",
    )
    memory_id = captured["candidates"][0]["memory_id"]

    with patch("app.fastapi_routes.knowledge_v1._persy_memory_service", return_value=memories):
        other_user = client.post(
            f"/api/knowledge/v1/datasets/persy-knowledge/memories/{memory_id}/confirm",
            headers=_headers(actor="bob"),
            json={},
        )
        unsupported = client.get(
            "/api/knowledge/v1/datasets/not-persy/memories",
            headers=_headers(actor="alice"),
        )

    assert other_user.status_code == 404
    assert other_user.json()["error_code"] == "persy_memory_not_found"
    assert unsupported.status_code == 404
    assert unsupported.json()["error_code"] == "persy_dataset_required"


def test_admin_header_defaults_to_its_tenant_for_query(tmp_path) -> None:
    app = FastAPI()
    app.include_router(knowledge_router)
    client = TestClient(app, raise_server_exceptions=False)
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
        tenant_id="tenant-a",
        chunk_strategy="fixed",
        access_context=admin,
    )
    datasets.ingest_document(
        dataset_id="secure-admin",
        source="b.md",
        text="Tenant B only.",
        tenant_id="tenant-b",
        chunk_strategy="fixed",
        access_context=admin,
    )
    headers = {
        "X-Dataset-Actor-ID": "admin",
        "X-Dataset-Tenant-ID": "tenant-a",
        "X-Dataset-Admin": "true",
    }

    # The real spawned query worker must reopen the same persisted data as GET.
    # An in-process getter mock is not inherited across a spawn boundary.
    with (
        patch.dict("os.environ", DATASET_RAG_STORE_PATH=str(tmp_path / "datasets.json")),
        patch.object(dataset_rag_module, "_dataset_rag_app_service", None),
    ):
        status = client.get(
            "/api/knowledge/v1/datasets/secure-admin/status",
            headers=headers,
        )
        query = client.post(
            "/api/knowledge/v1/datasets/secure-admin/query",
            headers=headers,
            json={"query": "Tenant", "top_k": 5},
        )
        scoped_query = client.post(
            "/api/knowledge/v1/datasets/secure-admin/query",
            headers=headers,
            json={"query": "Tenant", "top_k": 5, "tenant_id": "tenant-b"},
        )

    assert status.status_code == query.status_code == scoped_query.status_code == 200
    assert status.json()["document_count"] == 2
    assert status.json()["tenant_ids"] == ["tenant-a", "tenant-b"]
    # Catalog status spans the admin's tenants; the actual agent query defaults
    # to its bound tenant. An explicit admin target may select another tenant.
    assert {row["metadata"]["tenant_id"] for row in query.json()["chunks"]} == {"tenant-a"}
    assert {row["metadata"]["tenant_id"] for row in scoped_query.json()["chunks"]} == {"tenant-b"}
