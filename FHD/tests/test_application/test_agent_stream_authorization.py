"""Streams must revalidate authentication before releasing each snapshot/event."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.infrastructure.auth.agent_principal import AgentPrincipal
from app.infrastructure.auth.agent_stream import require_stream_authorizer


def test_disabled_session_user_cannot_obtain_agent_principal(monkeypatch):
    from app.infrastructure.auth.agent_principal import require_agent_principal

    user = SimpleNamespace(
        id="owner", username="owner", tenant_id="t", role="user", tier="", is_active=False
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_principal.resolve_session_user", lambda request: user
    )
    request = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException):
        require_agent_principal(request, x_user_id=None)


@pytest.mark.parametrize("change", ["expiry", "user", "tenant", "admin", "mod"])
def test_stream_authorizer_rechecks_original_identity(monkeypatch, change):
    original = AgentPrincipal(user_id="owner", tenant_id="t", mod_authorization={"mod_id": "a"})
    changed = {
        "expiry": HTTPException(status_code=401),
        "user": replace(original, user_id="other"),
        "tenant": replace(original, tenant_id="other"),
        "admin": replace(original, is_admin=True),
        "mod": replace(original, mod_authorization={"mod_id": "b"}),
    }[change]
    resolver = Mock(side_effect=[original, changed])
    monkeypatch.setattr("app.infrastructure.auth.agent_stream.require_agent_principal", resolver)
    request = Request({"type": "http", "headers": []})
    check = require_stream_authorizer(request, original)
    assert asyncio.run(check()) is True
    assert asyncio.run(check()) is False
    assert resolver.call_count == 2


@pytest.mark.parametrize("kind", ["tasks", "events"])
@pytest.mark.parametrize("valid_before_read", [False, True])
def test_stream_drops_data_when_authorization_expires(monkeypatch, kind, valid_before_read):
    from app.fastapi_routes.domains.agent import event_routes, task_routes

    principal = AgentPrincipal(user_id="owner")
    authorize = AsyncMock(side_effect=[True, False] if valid_before_read else [False])
    if kind == "tasks":
        fetch = Mock(return_value=[])
        monkeypatch.setattr(task_routes, "scoped_tasks", fetch)
        monkeypatch.setattr(task_routes, "_execution_map", lambda tasks: {})
        monkeypatch.setattr(task_routes, "AgentOrchestrator", lambda: object())
        response = asyncio.run(
            task_routes.stream_agent_tasks(once=True, principal=principal, authorize=authorize)
        )
    else:
        fetch = Mock(return_value=[SimpleNamespace(event_id="id", event_type="secret")])
        monkeypatch.setattr(event_routes, "_owned_run", lambda *args: (object(), None))
        monkeypatch.setattr(
            event_routes, "AgentOrchestrator", lambda: SimpleNamespace(list_events=fetch)
        )
        response = asyncio.run(
            event_routes.stream_agent_run_events(
                "run", after_event_id=None, principal=principal, authorize=authorize
            )
        )

    async def consume():
        return [chunk async for chunk in response.body_iterator]

    assert asyncio.run(consume()) == ["event: stream.closed\ndata: {}\n\n"]
    assert fetch.call_count == int(valid_before_read)
