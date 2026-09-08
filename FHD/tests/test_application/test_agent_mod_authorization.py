from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.runtime_context import (
    RuntimeContextOwnershipError,
    merge_runtime_context,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.db.base import Base
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
from app.infrastructure.auth.agent_mod_scope import (
    AgentModAuthorizationError,
    bind_agent_mod_scope,
)
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal
from app.request_active_mod_ctx import get_request_active_mod_id
from app.utils.time import utc_now_naive


@pytest.fixture
def mod_session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'host.db'}")
    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.db.HostSessionLocal", factory)
    with factory.begin() as db:
        db.add(User(id=1, username="mod-owner", password="unused", is_active=True))
        db.flush()
        db.add(UserSession(session_id="secret-session", user_id=1,
                           expires_at=utc_now_naive() + timedelta(hours=1),
                           entitled_mod_ids_json='["test-private-mod"]'))
    yield factory
    engine.dispose()


def test_background_mod_scope_revalidates_revocation_and_restores_thread(mod_session, monkeypatch):
    binding = bind_agent_mod_scope(session_id="secret-session", user_id="1", mod_id="test-private-mod")
    assert "secret-session" not in str(binding)
    seen = []

    def execute(tool, action, params):
        seen.append(get_request_active_mod_id())
        return {"success": True, "data": []}

    monkeypatch.setattr("app.application.facades.tools_facade.execute_registered_workflow_tool", execute)
    step = AgentStep(node_id="query", tool_id="products", action="query", params={"keyword": "5003"})

    def run():
        assert get_request_active_mod_id() == ""
        result = AgentToolExecutor().execute(step, runtime_context={"_mod_authorization": binding})
        assert get_request_active_mod_id() == ""
        return result

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(run).result(timeout=10)["success"]
        with mod_session.begin() as db:
            db.query(UserSession).filter_by(session_id="secret-session").one().entitled_mod_ids_json = "[]"
        assert pool.submit(run).result(timeout=10)["error_code"] == "mod_authorization_invalid"
    assert seen == ["test-private-mod"]


@pytest.mark.parametrize("user_id,mod_id", [("2", "test-private-mod"), ("1", "other-private-mod")])
def test_binding_rejects_wrong_owner_or_unentitled_mod(mod_session, user_id, mod_id):
    with pytest.raises(AgentModAuthorizationError):
        bind_agent_mod_scope(session_id="secret-session", user_id=user_id, mod_id=mod_id)


def test_client_cannot_supply_or_replace_mod_authorization():
    forged = {"session_row_id": 5, "user_id": "other", "mod_id": "private"}
    assert "_mod_authorization" not in authenticated_runtime_context(
        {"_mod_authorization": forged}, AgentPrincipal(user_id="1")
    )
    run = AgentRun(user_id="1", message="protected")
    run.metadata["runtime_context"] = {"_mod_authorization": forged}
    with pytest.raises(RuntimeContextOwnershipError):
        merge_runtime_context(run, {"_mod_authorization": None})
    assert merge_runtime_context(run, {"source": "resume"})["_mod_authorization"] == forged


def test_authenticated_request_binds_server_session_without_persisting_token(mod_session, monkeypatch):
    monkeypatch.setattr("app.infrastructure.auth.agent_principal.resolve_session_user",
                        lambda request: SimpleNamespace(id=1, username="mod-owner", tenant_id=7))
    request = Request({"type": "http", "headers": [
        (b"x-session-id", b"secret-session"),
        (b"x-xcagi-active-mod-id", b"test-private-mod"),
    ]})
    principal = require_agent_principal(request)
    context = authenticated_runtime_context({"_mod_authorization": {"forged": True}}, principal)
    assert context["tenant_id"] == "7"
    assert context["_mod_authorization"]["mod_id"] == "test-private-mod"
    assert context["_mod_authorization"]["user_id"] == "1"
    assert "secret-session" not in str(context)


@pytest.mark.parametrize("invalidity", ["expired", "disabled", "deleted"])
def test_background_mod_binding_rejects_invalidated_session(mod_session, invalidity):
    from app.infrastructure.auth.agent_mod_scope import agent_mod_execution_scope

    binding = bind_agent_mod_scope(session_id="secret-session", user_id="1", mod_id="test-private-mod")
    with mod_session.begin() as db:
        row = db.query(UserSession).filter_by(session_id="secret-session").one()
        if invalidity == "expired":
            row.expires_at = utc_now_naive() - timedelta(seconds=1)
        elif invalidity == "disabled":
            row.user.is_active = False
        else:
            db.delete(row)
    with pytest.raises(AgentModAuthorizationError):
        with agent_mod_execution_scope(binding):
            pytest.fail("revoked scope entered")
