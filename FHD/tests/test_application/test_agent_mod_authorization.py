from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
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


@pytest.mark.parametrize("token_kind", ["access_token", "refresh_token"])
def test_mobile_token_binds_only_verified_access_session(mod_session, monkeypatch, token_kind):
    from app.infrastructure.auth.agent_principal import require_agent_principal
    from app.security.mobile_jwt import issue_mobile_tokens

    monkeypatch.setenv("SECRET_KEY", "isolated-mobile-agent-test-secret-" * 2)
    monkeypatch.setattr("app.infrastructure.auth.agent_principal.resolve_session_user", lambda request: None)
    tokens = issue_mobile_tokens(user_id=1, session_id="secret-session", username="mod-owner")
    request = Request({"type": "http", "headers": [
        (b"authorization", f"Bearer {tokens[token_kind]}".encode()),
        (b"x-xcagi-active-mod-id", b"test-private-mod"),
    ]})
    if token_kind == "refresh_token":
        with pytest.raises(HTTPException) as error:
            require_agent_principal(request, x_user_id=None)
        assert error.value.status_code == 401
    else:
        principal = require_agent_principal(request, x_user_id=None)
        assert principal.mod_authorization["user_id"] == "1"
        assert principal.mod_authorization["mod_id"] == "test-private-mod"
        assert tokens[token_kind] not in str(principal.mod_authorization)


@pytest.mark.parametrize("invalidity,expected_status", [("wrong_owner", 401), ("signature", 401), ("expired_session", 401)])
def test_mobile_mod_scope_rejects_invalid_proof(mod_session, monkeypatch, invalidity, expected_status):
    from app.security.mobile_jwt import issue_mobile_tokens

    monkeypatch.setenv("SECRET_KEY", "isolated-mobile-agent-test-secret-" * 2)
    monkeypatch.setattr("app.infrastructure.auth.agent_principal.resolve_session_user", lambda request: None)
    token = issue_mobile_tokens(
        user_id=2 if invalidity == "wrong_owner" else 1, session_id="secret-session"
    )["access_token"]
    if invalidity == "signature":
        parts = token.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        token = ".".join(parts)
    if invalidity == "expired_session":
        with mod_session.begin() as db:
            db.query(UserSession).filter_by(session_id="secret-session").one().expires_at = utc_now_naive() - timedelta(seconds=1)
    request = Request({"type": "http", "headers": [
        (b"authorization", f"Bearer {token}".encode()),
        (b"x-xcagi-active-mod-id", b"test-private-mod"),
    ]})
    with pytest.raises(HTTPException) as error:
        require_agent_principal(request, x_user_id=None)
    assert error.value.status_code == expected_status


def test_mobile_principal_uses_current_account_tenant_and_role(mod_session, monkeypatch):
    from app.security.mobile_jwt import issue_mobile_tokens

    monkeypatch.setenv("SECRET_KEY", "isolated-mobile-agent-test-secret-" * 2)
    monkeypatch.setattr("app.infrastructure.auth.agent_principal.resolve_session_user", lambda request: None)
    token = issue_mobile_tokens(user_id=1, session_id="secret-session", account_kind="admin")["access_token"]
    request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})
    with mod_session.begin() as db:
        user = db.get(User, 1)
        user.tenant_id = 7
        user.role = "user"
    principal = require_agent_principal(request, x_user_id=None)
    assert principal.tenant_id == "7"
    assert principal.is_admin is False
    with mod_session.begin() as db:
        db.get(User, 1).is_active = False
    with pytest.raises(HTTPException) as error:
        require_agent_principal(request, x_user_id=None)
    assert error.value.status_code == 401


@pytest.mark.parametrize("invalidity", ["expired", "deleted"])
def test_mobile_host_task_also_requires_current_session(mod_session, monkeypatch, invalidity):
    from app.security.mobile_jwt import issue_mobile_tokens

    monkeypatch.setenv("SECRET_KEY", "isolated-mobile-agent-test-secret-" * 2)
    monkeypatch.setattr("app.infrastructure.auth.agent_principal.resolve_session_user", lambda request: None)
    token = issue_mobile_tokens(user_id=1, session_id="secret-session")["access_token"]
    with mod_session.begin() as db:
        row = db.query(UserSession).filter_by(session_id="secret-session").one()
        if invalidity == "expired":
            row.expires_at = utc_now_naive() - timedelta(seconds=1)
        else:
            db.delete(row)
    request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})
    with pytest.raises(HTTPException) as error:
        require_agent_principal(request, x_user_id=None)
    assert error.value.status_code == 401


def test_web_token_and_refresh_bind_persisted_mod_session(mod_session, monkeypatch):
    from app.security.web_jwt import (
        issue_web_tokens,
        refresh_web_access_token,
        resolve_user_from_web_jwt,
    )

    monkeypatch.setenv("SECRET_KEY", "isolated-web-agent-test-secret-" * 2)
    monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "1")
    monkeypatch.setattr("app.infrastructure.auth.agent_principal.resolve_session_user",
                        lambda request: resolve_user_from_web_jwt(request.headers["authorization"][7:]))
    tokens = issue_web_tokens(user_id=1, session_id="secret-session")
    refreshed = refresh_web_access_token(tokens["refresh_token"])
    assert refreshed is not None
    for token in (tokens["access_token"], refreshed["access_token"]):
        request = Request({"type": "http", "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"x-xcagi-active-mod-id", b"test-private-mod"),
        ]})
        principal = require_agent_principal(request, x_user_id=None)
        assert principal.mod_authorization["mod_id"] == "test-private-mod"
        assert "secret-session" not in str(principal.mod_authorization)
    with mod_session.begin() as db:
        db.query(UserSession).filter_by(session_id="secret-session").one().entitled_mod_ids_json = "[]"
    with pytest.raises(HTTPException) as error:
        require_agent_principal(request, x_user_id=None)
    assert error.value.status_code == 403
