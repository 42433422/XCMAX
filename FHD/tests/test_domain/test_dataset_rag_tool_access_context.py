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
