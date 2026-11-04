"""Real SQLite sessions through public entrypoints; downstream effects are spies only."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request


def request(sid=None, mod=None, cookie=False):
    headers = [(b"x-user-id", b"999")]
    if sid:
        headers.append(
            (
                b"cookie" if cookie else b"x-session-id",
                f"session_id={sid}".encode() if cookie else sid.encode(),
            )
        )
    if mod:
        headers.append((b"x-xcagi-active-mod-id", mod.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tools/execute",
            "headers": headers,
            "client": ("test", 0),
            "query_string": b"",
        }
    )


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    import app.db as db_module
    from app.db.db_base import Base
    from app.db.models.user import Session, User
    from app.domain.shared_services.session_service import SessionService
    from app.utils.time import utc_now_naive

    monkeypatch.setenv("SECRET_KEY", "synthetic-principal-contract-test-only")
    monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "0")
    monkeypatch.setenv("FHD_ALLOW_X_USER_ID_HEADER", "1")
    engine = create_engine(f"sqlite:///{tmp_path / 'sessions.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "HostSessionLocal", factory)
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service", SessionService
    )
    with factory() as db:
        db.add_all(
            [
                User(
                    id=71,
                    username="synthetic-one",
                    password="unused",
                    tenant_id=7,
                    role="user",
                    tier="enterprise",
                ),
                User(
                    id=81,
                    username="synthetic-two",
                    password="unused",
                    tenant_id=8,
                    role="user",
                    tier="enterprise",
                ),
            ]
        )
        db.flush()
        for sid, uid, hours in [("valid", 71, 1), ("other", 81, 1), ("expired", 71, -1)]:
            db.add(
                Session(
                    session_id=sid,
                    user_id=uid,
                    expires_at=utc_now_naive() + timedelta(hours=hours),
                    entitled_mod_ids_json='["synthetic-mod"]',
                )
            )
        db.commit()
    yield factory
    engine.dispose()


@pytest.mark.parametrize("cookie", [False, True])
def test_tools_real_session_overrides_payload_identity(sessions, monkeypatch, cookie):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.fastapi_routes.tools_execute import tools_execute_route
    from app.infrastructure.auth.agent_mod_scope import validate_actor_context

    captured = []

    def start(self, **kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            status="completed", run_id="synthetic-run", final_output={}, steps=[]
        )

    monkeypatch.setattr(AgentOrchestrator, "start_run_from_plan", start)
    response = tools_execute_route(
        request("valid", cookie=cookie),
        {
            "tool_id": "products",
            "action": "exists",
            "user_id": "999",
            "params": {
                "name": "synthetic",
                "tenant_id": "999",
                "mod_id": "forged",
                "_runtime_context": {"user_id": "999", "_actor_authorization": {"proof": "fake"}},
            },
        },
    )
    assert response.status_code == 200
    call = captured.pop()
    assert call["user_id"] == "71"
    ctx = call["runtime_context"]
    assert ctx["tenant_id"] == "7" and validate_actor_context(ctx) is None
    assert "tenant_id" not in call["plan"].nodes[0].params
    assert "mod_id" not in call["plan"].nodes[0].params


@pytest.mark.parametrize(
    "sid,mod,status",
    [
        (None, None, 401),
        ("expired", None, 401),
        ("unknown", None, 401),
        ("valid", "not-entitled", 403),
    ],
)
def test_tools_reject_before_effects(sessions, monkeypatch, sid, mod, status):
    from app.fastapi_routes import tools_execute

    calls = []
    monkeypatch.setattr(tools_execute, "run_tools_execute_agent", lambda **kw: calls.append(kw))
    with pytest.raises(HTTPException) as error:
        tools_execute.tools_execute_route(
            request(sid, mod), {"user_id": "71", "tool_id": "products"}
        )
    assert error.value.status_code == status
    assert calls == []


def test_mod_and_tenant_revalidation_and_continuation(sessions):
    from app.application.agent_orchestrator.runtime_context import (
        RuntimeContextOwnershipError,
        merge_runtime_context,
    )
    from app.fastapi_routes.domains.agent.route_support import request_runtime_context
    from app.infrastructure.auth.agent_mod_scope import validate_actor_context

    ctx = request_runtime_context(request("valid", "synthetic-mod"))
    assert validate_actor_context(ctx) is None
    run = SimpleNamespace(metadata={"runtime_context": ctx})
    for key, value in [
        ("tenant_id", "8"),
        ("user_id", "81"),
        ("mod_id", "other-mod"),
        ("active_mod_id", "other-mod"),
        ("_actor_authorization", {"proof": "fake"}),
    ]:
        with pytest.raises(RuntimeContextOwnershipError):
            merge_runtime_context(run, {key: value})
    for key, value in [("tenant_id", "8"), ("user_id", "81"), ("mod_id", "other-mod")]:
        assert validate_actor_context({**ctx, key: value}) is not None
    other = request_runtime_context(request("other"))
    assert validate_actor_context({**ctx, "_actor_authorization": other["_actor_authorization"]})
    assert (
        merge_runtime_context(run, {"message": "continue"})["_actor_authorization"]
        == ctx["_actor_authorization"]
    )


@pytest.mark.parametrize("batch", [False, True])
def test_unified_entrypoint_preserves_server_actor(sessions, monkeypatch, batch):
    from app.domain.app_pure import ai_chat_helpers
    from app.fastapi_routes import ai_intent
    from app.infrastructure.auth.agent_mod_scope import validate_actor_context

    captured = []

    def reply(message, user_id, host, source, mode, context):
        captured.append((user_id, context))
        return {"success": True, "reply": "synthetic"}

    monkeypatch.setattr(ai_chat_helpers, "unified_chat_single_payload", reply)
    monkeypatch.setattr(ai_intent, "_attach_unified_chat_run", lambda payload, **kw: payload)
    endpoint = ai_intent.ai_chat_unified_batch_alias if batch else ai_intent.ai_chat_unified_alias
    result = endpoint(
        request("valid"),
        {
            "message": "hello",
            "messages": ["hello"],
            "user_id": "999",
            "context": {"tenant_id": "999", "actor_id": "999"},
        },
    )
    assert result["success"] if batch else result.status_code == 200
    assert captured and captured[0][0] == "71"
    assert validate_actor_context(captured[0][1]) is None


def test_chat_invalid_credentials_do_not_downgrade(sessions, monkeypatch):
    from app.domain.app_pure import ai_chat_helpers
    from app.fastapi_routes import ai_intent

    calls = []
    monkeypatch.setattr(ai_chat_helpers, "unified_chat_single_payload", lambda *a: calls.append(a))
    with pytest.raises(HTTPException) as error:
        ai_intent.ai_chat_unified_alias(request("expired"), {"message": "write", "user_id": "71"})
    assert error.value.status_code == 401 and not calls


def test_delegate_keeps_original_actor_and_rejects_revocation(sessions):
    from app.application.agent_orchestrator.runtime_context import RuntimeContextOwnershipError
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.db.models.user import Session
    from app.fastapi_routes.xcagi_compat_chat_helpers import (
        _runtime_context_with_authenticated_actor,
    )
    from app.utils.time import utc_now_naive

    ctx = _runtime_context_with_authenticated_actor(request("valid"), {"tenant_id": "999"})
    before = deepcopy(ctx["_actor_authorization"])
    merged = AIChatApplicationService._merge_tool_runtime_context("conversation-999", "hello", ctx)
    assert merged["user_id"] == "71" and merged["_actor_authorization"] == before
    forged = deepcopy(ctx)
    forged["_actor_authorization"]["proof"] = "not-a-server-proof"
    with pytest.raises(RuntimeContextOwnershipError):
        AIChatApplicationService._merge_tool_runtime_context("71", "write", forged)
    with sessions() as db:
        row = db.query(Session).filter_by(session_id="valid").one()
        row.expires_at = utc_now_naive() - timedelta(seconds=1)
        db.commit()
    with pytest.raises(RuntimeContextOwnershipError):
        AIChatApplicationService._merge_tool_runtime_context("71", "write", ctx)


def test_anonymous_conversation_never_supplies_executor_identity(sessions):
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.fastapi_routes.xcagi_compat_chat_helpers import (
        _runtime_context_with_authenticated_actor,
    )

    context = _runtime_context_with_authenticated_actor(
        request(),
        {
            "user_id": "71",
            "actor_id": "71",
            "tenant_id": "7",
            "mod_id": "synthetic-mod",
            "_actor_authorization": {"proof": "forged"},
            "_mod_authorization": {"user_id": "71"},
        },
    )
    assert context == {}
    merged = AIChatApplicationService._merge_tool_runtime_context("71", "hello", context)
    assert merged["conversation_id"] == "71"
    assert "user_id" not in merged and "_actor_authorization" not in merged


@pytest.mark.parametrize("kind", ["mobile", "web"])
def test_signed_bearer_requires_matching_live_server_session(sessions, monkeypatch, kind):
    from app.fastapi_routes.tools_execute import _authenticated_tool_body
    from app.infrastructure.auth.agent_mod_scope import validate_actor_context
    from app.security.mobile_jwt import issue_mobile_tokens
    from app.security.web_jwt import issue_web_tokens

    issue = issue_mobile_tokens if kind == "mobile" else issue_web_tokens
    monkeypatch.setenv("XCAGI_WEB_JWT_AUTH", "1" if kind == "web" else "0")

    def bearer(uid, sid):
        token = issue(user_id=uid, session_id=sid)["access_token"]
        scope = dict(request().scope)
        scope["headers"] = [(b"authorization", f"Bearer {token}".encode())]
        return Request(scope)

    body = _authenticated_tool_body(bearer(71, "valid"), {"user_id": "999"})
    assert body["user_id"] == "71"
    assert validate_actor_context(body["params"]["_runtime_context"]) is None
    for uid, sid in [(81, "valid"), (71, "expired"), (71, "absent")]:
        with pytest.raises(HTTPException) as error:
            _authenticated_tool_body(bearer(uid, sid), {})
        assert error.value.status_code == 401
