"""Bounded ensure_exists admission, not global tool or durable receipt acceptance."""

import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import event

from tests.test_application.test_authenticated_principal_propagation import request
from tests.test_application.test_authenticated_principal_propagation import (
    sessions as _sessions_fixture,
)

sessions = _sessions_fixture


@pytest.fixture
def customer_store(sessions, monkeypatch):
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.customer_app_service import CustomerApplicationService
    from app.db.models.user import Session, User
    from app.domain.shared_services.auth_service import AuthService
    from app.utils.time import utc_now_naive

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    with sessions() as db:
        db.add(
            User(id=91, username="synthetic-admin", password="unused", role="admin", tier="admin")
        )
        db.add(
            User(id=92, username="synthetic-local", password="unused", role="user", tier="personal")
        )
        db.flush()
        for sid, uid in [("admin", 91), ("local", 92)]:
            db.add(
                Session(
                    session_id=sid,
                    user_id=uid,
                    expires_at=utc_now_naive() + timedelta(hours=1),
                    entitled_mod_ids_json='["synthetic-mod"]',
                )
            )
        db.commit()
    svc = CustomerApplicationService()
    monkeypatch.setattr(svc, "_get_session", sessions)
    monkeypatch.setattr("app.application.get_customer_app_service", lambda: svc)
    monkeypatch.setattr("app.application.facades.session_facade.get_auth_service", AuthService)
    app = object.__new__(AIChatApplicationService)
    writes, calls = [], []
    original = svc.create

    def create(data):
        calls.append(dict(data))
        return original(data)

    monkeypatch.setattr(svc, "create", create)
    engine = sessions.kw["bind"]

    def record(conn, cursor, statement, params, context, many):
        if (
            statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            and "purchase_units" in statement
        ):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    yield app, calls, writes
    event.remove(engine, "before_cursor_execute", record)


def context(sid="admin", mod=None):
    from app.fastapi_routes.domains.agent.route_support import request_runtime_context

    return request_runtime_context(request(sid, mod))


def instant(app, ctx):
    return app._build_response(
        {
            "action": "tool_call",
            "data": {
                "tool_key": "customers",
                "params": {"unit_name": "synthetic-admission-unit"},
                "slots": {},
            },
        },
        "pro",
        "新增单位 synthetic-admission-unit",
        runtime_context=ctx,
    )


@pytest.mark.parametrize(
    "kind", ["anonymous", "conversation", "tenant", "forged", "mod", "revoked"]
)
def test_customer_denied_before_business_call_or_write(customer_store, sessions, kind):
    from app.db.models.user import Session
    from app.utils.time import utc_now_naive

    app, calls, writes = customer_store
    ctx = context()
    if kind == "anonymous":
        ctx = {}
    elif kind == "conversation":
        ctx = {"user_id": "91", "actor_id": "91"}
    elif kind == "tenant":
        ctx = context("valid")
    elif kind == "forged":
        ctx["_actor_authorization"]["proof"] = "forged"
    elif kind == "mod":
        ctx["mod_id"] = "not-entitled"
    elif kind == "revoked":
        with sessions() as db:
            db.query(Session).filter_by(session_id="admin").one().expires_at = (
                utc_now_naive() - timedelta(seconds=1)
            )
            db.commit()
    result = instant(app, ctx)
    assert "无权" in result["response"]
    assert calls == [] and writes == []


def assert_customer_denied(result):
    assert result["success"] is False
    assert result["error_code"] == "customer_action_not_authorized"


def test_tenantless_admin_denied_before_create(customer_store):
    """Stronger than the retained original TenantScopeError repro: no create attempt."""
    app, calls, writes = customer_store
    result = instant(app, context())
    assert_customer_denied(result["data"]["data"])
    assert calls == []
    assert writes == []
    assert "已创建" not in result["response"]


def test_chat_http_preserves_tenantless_customer_denial(customer_store, monkeypatch):
    """Replace only model dispatch/run attachment; real HTTP/auth/tool formatting remains."""
    from app.domain.app_pure import ai_chat_helpers
    from app.fastapi_routes import ai_intent

    app, calls, writes = customer_store
    monkeypatch.setattr(
        ai_chat_helpers,
        "unified_chat_single_payload",
        lambda message, user_id, host, source, mode, ctx: instant(app, ctx),
    )
    monkeypatch.setattr(ai_intent, "_attach_unified_chat_run", lambda payload, **kwargs: payload)
    response = ai_intent.ai_chat_unified_alias(
        request("admin"),
        {"message": "新增单位 synthetic-admission-unit", "source": "pro"},
    )
    assert response.status_code == 200
    assert_customer_denied(json.loads(response.body)["data"]["data"])
    assert calls == [] and writes == []


@pytest.mark.parametrize(
    "sku,sid,allowed",
    [
        ("enterprise", "admin", True),
        ("enterprise", "local", False),
        ("enterprise", "valid", False),
        ("personal", "local", True),
        ("personal", "valid", False),
    ],
)
def test_http_and_tool_share_authenticated_store_policy(
    customer_store, monkeypatch, sku, sid, allowed
):
    from app.infrastructure.auth.agent_mod_scope import _bound_actor
    from app.infrastructure.auth.business_scope_gate import (
        check_legacy_business_user_permission,
        require_scoped_business_permission,
    )

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", sku)
    actor = _bound_actor(context(sid))
    guard = require_scoped_business_permission("customer.view", "customer.edit")
    if allowed:
        http_result = guard(request(sid))
        tool_result = check_legacy_business_user_permission(actor, "customer.edit")
        if sku == "enterprise":
            assert http_result.id == tool_result.id == actor.id
        else:
            assert http_result is tool_result is None
    else:
        for invoke in [
            lambda: guard(request(sid)),
            lambda: check_legacy_business_user_permission(actor, "customer.edit"),
        ]:
            with pytest.raises(HTTPException) as error:
                invoke()
            assert error.value.status_code == 403


def test_nonenterprise_http_anonymous_unchanged_but_tool_denies(customer_store, monkeypatch):
    from app.infrastructure.auth.business_scope_gate import require_scoped_business_permission

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "personal")
    assert require_scoped_business_permission("customer.view", "customer.edit")(request()) is None
    app, calls, writes = customer_store
    assert "无权" in instant(app, {})["response"]
    assert calls == [] and writes == []


@pytest.mark.parametrize("sid", ["admin", None, "expired"])
def test_voice_request_identity_not_trace_id(customer_store, monkeypatch, sid):
    """ASR and classifier are mocked; real Request/auth/instant/router/service are not."""
    from app.fastapi_routes import voice_routes

    app, calls, writes = customer_store
    monkeypatch.setattr("app.application.ai_chat_app_service.get_ai_chat_app_service", lambda: app)
    monkeypatch.setattr(
        voice_routes, "_transcribe_audio", lambda *a: "新增单位 synthetic-admission-unit"
    )
    monkeypatch.setattr(
        voice_routes,
        "_recognize_intent",
        lambda text: {
            "tool_key": "customers",
            "confidence": 1.0,
            "slots": {"unit_name": "synthetic-admission-unit"},
        },
    )

    async def invoke():
        return await voice_routes.voice_command(
            request(sid),
            file=UploadFile(BytesIO(b"synthetic-no-audio"), filename="test.wav"),
            auto_execute=True,
            session_id="admin",
            language=None,
        )

    if sid == "expired":
        with pytest.raises(HTTPException):
            asyncio.run(invoke())
    else:
        response = asyncio.run(invoke())
        if sid == "admin":
            assert_customer_denied(response["data"]["result"]["data"])
    assert calls == []
    assert writes == []  # scope-unavailable lookup cannot authorize even an attempted create
