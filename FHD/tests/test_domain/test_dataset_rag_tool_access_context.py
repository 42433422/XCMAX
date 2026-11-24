from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.shared_services.tools_workflow_memory_rag import _registered_router_dataset_rag
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def record(**kwargs):
        calls.append(kwargs)
        return {"success": True}

    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        lambda: SimpleNamespace(query=record, answer=record),
    )
    return calls


def test_dataset_acl_comes_from_bound_actor_not_params_or_ambient(captured, trusted_actor):
    actor = trusted_actor(user_id=7, permissions=["dataset.read"])
    with tenant_scope(999):
        _registered_router_dataset_rag(
            "query",
            {
                "dataset_id": "ds",
                "query": "q",
                "tenant_id": "999",
                "access_context": {"is_admin": True},
            },
            {
                **actor.context,
                "dataset_access_context": {"is_admin": True, "permissions": ["dataset.admin"]},
            },
            "",
            "",
        )
    context = captured[0]["access_context"]
    assert context.actor_id == "7" and context.tenant_id == "7"
    assert context.is_admin is False
    assert context.permissions == frozenset({"dataset.read"})


def test_missing_bound_actor_never_inherits_ambient_dataset_authority(captured):
    with tenant_scope(7), pytest.raises(AgentModAuthorizationError):
        _registered_router_dataset_rag("query", {"dataset_id": "ds", "query": "q"}, {}, "", "")
    assert captured == []


@pytest.mark.parametrize("requested_tenant", [None, ""])
def test_dataset_admin_import_defaults_to_bound_tenant(
    trusted_actor, monkeypatch, tmp_path, requested_tenant
):
    from app.application.dataset_rag_app_service import DatasetRagApplicationService

    actor = trusted_actor(user_id=7, tenant_id=7, role="admin", permissions=["dataset.admin"])
    storage = tmp_path / "owned-dataset.json"
    service = DatasetRagApplicationService(
        storage_path=storage, embedder=lambda _text: [1.0], vector_index_backend_name="none"
    )
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service", lambda: service
    )
    with tenant_scope(999):
        result = _registered_router_dataset_rag(
            "ingest_document",
            {
                "dataset_id": "owned",
                "text": "Approved knowledge belongs to the original account.",
                "tenant_id": requested_tenant,
                "metadata": {"tenant_id": "999", "user_id": "999"},
            },
            actor.context,
            "",
            "",
        )
    assert result["success"] is True, result
    document = result["document"]
    assert document["tenant_id"] == document["metadata"]["tenant_id"] == "7"
    reopened = DatasetRagApplicationService(
        storage_path=storage, embedder=lambda _text: [1.0], vector_index_backend_name="none"
    )
    snapshot = reopened._repository.read_committed_dataset("owned")
    assert snapshot["documents"][document["document_id"]] == document
    assert snapshot["chunks"]
    assert all(chunk["metadata"]["tenant_id"] == "7" for chunk in snapshot["chunks"])
