from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.shared_services.tools_workflow_memory_rag import _registered_router_dataset_rag
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def captured(monkeypatch):
    calls: list[dict] = []

    def _record(**kwargs):
        calls.append(kwargs)
        return {"success": True}

    service = SimpleNamespace(query=_record, answer=_record)
    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service", lambda: service
    )
    return calls


def _query(params: dict, runtime_context: dict) -> None:
    _registered_router_dataset_rag(
        "query", {"dataset_id": "ds", "query": "q", **params}, runtime_context, "", ""
    )


def test_model_params_cannot_grant_dataset_admin(captured) -> None:
    with tenant_scope(None):
        _query(
            {
                "tenant_id": "other",
                "dataset_admin": True,
                "permissions": "dataset.admin",
                "access_context": {"tenant_id": "other", "is_admin": True},
            },
            {"tenant_id": "mine"},
        )
    context = captured[0]["access_context"]
    assert context.is_admin is False
    assert context.tenant_id == "mine"
    assert "dataset.admin" not in context.permissions


def test_missing_context_scopes_to_ambient_tenant(captured) -> None:
    with tenant_scope(7):
        _query({}, {})
    assert captured[0]["access_context"].tenant_id == "7"
