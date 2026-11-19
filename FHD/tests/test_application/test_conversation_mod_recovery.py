"""History APIs and recovery use the same authorized Mod lifecycle database."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.application.agent_orchestrator.run_lifecycle import continuation_conversation_error
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.task_conversation_store import task_conversation_store as store
from app.db.db_base import Base
from app.db.models.user import Session as UserSession
from app.fastapi_app.middleware_extra import register_extra_middleware
from app.fastapi_routes.domains.conversation.conversation_routes import router
from app.infrastructure.auth.agent_mod_scope import agent_mod_execution_scope
from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture(params=["native", "compat"])
def mod_histories(trusted_actor, tmp_path, monkeypatch, request):
    from app import db as db_module
    from app.db.models.user import User
    from app.legacy.routes.conversation.compat_extra import router as compat_router

    owner = trusted_actor(role="admin")
    actors = {"": owner}
    engines = []
    urls = {}
    for name in ("private-a", "private-b"):
        actors[name] = trusted_actor(user_id=owner.user_id, role="admin", mod_id=name)
        engine = create_engine(f"sqlite:///{tmp_path / (name + '.sqlite')}")
        engines.append(engine)
        urls[name] = str(engine.url)
        Base.metadata.create_all(engine)
        with engine.begin() as db:
            db.execute(
                User.__table__.insert(),
                {
                    "id": owner.user_id,
                    "username": "owner",
                    "password": "unused",
                    "tenant_id": 7,
                    "role": "admin",
                    "is_active": True,
                },
            )
    monkeypatch.setenv("XCAGI_MOD_DATABASE_URLS", json.dumps(urls))
    monkeypatch.setattr(db_module, "_get_test_db_manager", lambda: None)
    # trusted_actor deliberately replaces routing for ordinary unit tests;
    # restore the production router to exercise separate physical databases.
    monkeypatch.setattr("app.db.session.SessionLocal", db_module.SessionLocal)
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.notify_user", lambda *a, **kw: None
    )
    for name, actor in actors.items():
        with agent_mod_execution_scope(actor.principal.mod_authorization):
            store.save_message(
                session_id="shared", user_id=owner.user_id, role="user", content=name or "host"
            )
    app = FastAPI()
    if request.param == "compat":
        app.include_router(compat_router, prefix="/api")
        app.include_router(router)
    else:
        app.include_router(router)
        app.include_router(compat_router, prefix="/api")
    register_extra_middleware(app)
    try:
        with TestClient(app) as client:
            yield actors, client
    finally:
        for engine in engines:
            engine.dispose()


def _recovery(actor, session="shared"):
    run = AgentRun(user_id=str(actor.user_id), message="resume")
    context = {
        **actor.context,
        "local_user_id": actor.user_id,
        "conversation_id": session,
        "session_id": session,
        "_conversation_revision": 0,
    }
    return continuation_conversation_error(run, context)


def test_host_and_two_mod_histories_share_only_their_own_read_delete_and_recovery(mod_histories):
    actors, client = mod_histories
    for name, actor in actors.items():
        response = client.get("/api/conversations/shared", headers=actor.headers)
        assert response.status_code == 200, response.text
        assert [row["content"] for row in response.json()["messages"]] == [name or "host"]
        assert not _recovery(actor)
    actor = actors["private-a"]
    with agent_mod_execution_scope(actor.principal.mod_authorization):
        store.save_message(
            session_id="mod-only", user_id=actor.user_id, role="user", content="private"
        )
    assert not _recovery(actor, "mod-only")
    deleted = client.delete("/api/conversations/shared", headers=actors["private-a"].headers)
    assert deleted.status_code == 200 and deleted.json()["success"]
    assert "拒绝恢复" in _recovery(actors["private-a"])
    # A coincident live host row cannot revive the deleted Mod conversation.
    assert not _recovery(actors[""]) and not _recovery(actors["private-b"])
    for name in ("", "private-b"):
        rows = client.get("/api/conversations/shared", headers=actors[name].headers).json()[
            "messages"
        ]
        assert [row["content"] for row in rows] == [name or "host"]
    late = client.post(
        "/api/ai/message/save",
        headers=actors["private-a"].headers,
        json={
            "session_id": "shared",
            "role": "assistant",
            "content": "late",
            "expected_revision": 0,
        },
    )
    assert late.status_code == 409
    assert (
        client.get("/api/conversations/shared", headers=actors["private-a"].headers).json()[
            "messages"
        ]
        == []
    )


@pytest.mark.parametrize("revoked", [False, True])
def test_forged_or_revoked_mod_cannot_read_delete_or_repair_history(mod_histories, revoked):
    actors, client = mod_histories
    selected = actors["private-a"] if revoked else actors[""]
    if revoked:
        with selected.factory.begin() as db:
            db.get(UserSession, selected.session_row_id).entitled_mod_ids_json = "[]"
    headers = {**selected.headers, "X-XCAGI-Active-Mod-Id": "private-a"}
    for method, path, body in (
        ("get", "/api/conversations/shared", None),
        ("delete", "/api/conversations/shared", None),
        ("post", "/api/conversations/shared/turns/first/persist", {"expected_revision": 0}),
        ("put", "/api/conversations/shared/title", {"title": "forged"}),
        ("get", "/api/conversations/sessions", None),
        ("post", "/api/conversations/sessions/clear", {}),
        (
            "post",
            "/api/conversations/message",
            {"session_id": "shared", "role": "user", "content": "forged"},
        ),
        ("delete", "/api/conversations/shared/messages/1", None),
    ):
        response = client.request(method, path, headers=headers, json=body)
        assert response.status_code == 403, response.text
        assert "private-a" not in response.text
    if revoked:
        assert "授权失效" in _recovery(selected)
    assert (
        client.get("/api/conversations/shared", headers=actors[""].headers).json()["messages"][0][
            "content"
        ]
        == "host"
    )


def test_host_recovery_does_not_inherit_another_mods_ambient_context(mod_histories):
    from starlette.requests import Request

    from app.http.request_context import reset_current_http_request, set_current_http_request

    actors, client = mod_histories
    assert client.delete("/api/conversations/shared", headers=actors["private-a"].headers).json()[
        "success"
    ]
    token = set_request_active_mod_id("private-a")
    request_token = set_current_http_request(
        Request({"type": "http", "path": "/api/approval/review", "headers": []})
    )
    try:
        assert not _recovery(actors[""])
        assert not _recovery(actors["private-b"])
        assert "拒绝恢复" in _recovery(actors["private-a"])
    finally:
        reset_current_http_request(request_token)
        reset_request_active_mod_id(token)


def test_compat_durable_mod_selector_cannot_replace_authenticated_database(mod_histories):
    actors, client = mod_histories
    headers = actors["private-a"].headers
    for path, body in (
        ("/api/conversations/message", {"session_id": "shared", "content": "wrong scope"}),
        ("/api/conversations/sessions/clear", {}),
    ):
        response = client.post(path, headers=headers, json={**body, "mod_id": "private-b"})
        assert response.status_code == 403
    assert (
        client.get("/api/conversations/shared", headers=actors["private-b"].headers).json()[
            "messages"
        ][0]["content"]
        == "private-b"
    )
