"""Real authenticated entrypoints; only classification/ASR and DB faults are injected."""

import asyncio
import json
from io import BytesIO

import pytest
from fastapi import UploadFile
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db.models import PurchaseUnit
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.parametrize("entrypoint", ["chat", "voice"])
@pytest.mark.parametrize("fault", ["refresh", "readback"])
def test_committed_customer_uncertainty_survives_real_entrypoint(
    trusted_actor, monkeypatch, entrypoint, fault
):
    from app.application import get_ai_chat_app_service
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.fastapi_routes import ai_intent, voice_routes

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["customer.edit"])
    engine = actor.factory.kw["bind"]
    request = Request(
        {
            **actor.request.scope,
            "path": "/api/ai/chat-unified" if entrypoint == "chat" else "/api/voice/command",
            "client": ("synthetic", 0),
        }
    )
    name = f"uncertain-{entrypoint}-{fault}"
    message = f"新增单位 {name}"
    # Real service composition, authentication, dispatcher, customer store and
    # response formatting remain intact. No model/server request is performed.
    app = get_ai_chat_app_service()

    async def classified(*args, **kwargs):
        return {
            "action": "tool_call",
            "data": {
                "tool_key": "customers",
                "params": {"unit_name": name},
                "slots": {},
            },
        }

    monkeypatch.setattr(app.ai_service, "chat", classified)
    monkeypatch.setattr(LLMWorkflowPlanner, "plan", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.application.normal_chat_dispatch.route_normal_mode_message",
        lambda text: {"intent": "chat"},
    )
    monkeypatch.setattr(voice_routes, "_transcribe_audio", lambda *a: message)
    monkeypatch.setattr(
        voice_routes,
        "_recognize_intent",
        lambda text: {
            "tool_key": "customers",
            "confidence": 1.0,
            "slots": {"unit_name": name},
        },
    )
    state = {"inserts": 0, "committed": False, "postcommit_reads": 0, "faults": 0}

    def business_db(connection):
        return connection.engine.url.database == engine.url.database

    def after_sql(connection, cursor, statement, params, context, many):
        if business_db(connection) and statement.lstrip().upper().startswith(
            "INSERT INTO PURCHASE_UNITS"
        ):
            state["inserts"] += 1

    def committed(session):
        if state["inserts"]:
            state["committed"] = True

    def before_sql(connection, cursor, statement, params, context, many):
        if (
            business_db(connection)
            and state["committed"]
            and statement.lstrip().upper().startswith("SELECT")
            and "purchase_units" in statement
        ):
            state["postcommit_reads"] += 1
            if fault == "readback" and state["postcommit_reads"] >= 2:
                state["faults"] += 1
                raise OperationalError(
                    "synthetic customer readback", {}, RuntimeError("unavailable")
                )

    original_refresh = Session.refresh

    def refresh(session, instance, *args, **kwargs):
        if fault == "refresh" and isinstance(instance, PurchaseUnit) and state["committed"]:
            state["faults"] += 1
            raise OperationalError("synthetic customer refresh", {}, RuntimeError("unavailable"))
        return original_refresh(session, instance, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", refresh)
    event.listen(Engine, "after_cursor_execute", after_sql)
    event.listen(Engine, "before_cursor_execute", before_sql)
    event.listen(Session, "after_commit", committed)
    try:
        if entrypoint == "chat":
            response = ai_intent.ai_chat_unified_alias(
                request, {"message": message, "source": "normal"}
            )
            payload = json.loads(response.body)
            receipt = payload["data"]["data"]
            text = payload.get("response", "")
        else:

            async def invoke():
                return await voice_routes.voice_command(
                    request,
                    file=UploadFile(BytesIO(b"synthetic-no-audio"), filename="test.wav"),
                    auto_execute=True,
                    session_id="trace-not-authority",
                    language=None,
                )

            payload = asyncio.run(invoke())
            receipt = payload["data"]["result"]["data"]
            text = payload["data"]["result"].get("response", "")
        assert "已创建" not in text
        assert receipt["success"] is False
        assert receipt["outcome"] == "unknown"
        assert receipt["retryable"] is False and receipt["reconciliation_required"] is True
        assert state["committed"] and state["faults"] == 1
        assert state["inserts"] == 1  # No automatic duplicate within this request.
    finally:
        event.remove(Engine, "after_cursor_execute", after_sql)
        event.remove(Engine, "before_cursor_execute", before_sql)
        event.remove(Session, "after_commit", committed)
    # Independent physical-row read after removing fault injection. This is
    # evidence of one committed effect, not an at-most-once/replay guarantee.
    with engine.connect() as db:
        saved = (
            db.execute(select(PurchaseUnit.__table__).where(PurchaseUnit.unit_name == name))
            .mappings()
            .all()
        )
    assert len(saved) == 1 and saved[0]["tenant_id"] == 7 and saved[0]["id"] > 0
