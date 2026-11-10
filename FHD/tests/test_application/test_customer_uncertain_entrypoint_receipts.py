"""Real authenticated entrypoints; only classification/ASR and DB faults are injected."""

import asyncio
import json
from io import BytesIO
from unittest.mock import AsyncMock

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
@pytest.mark.parametrize("failure", [OperationalError, RuntimeError])
def test_committed_customer_uncertainty_survives_real_entrypoint(
    trusted_actor, monkeypatch, entrypoint, failure
):
    from app.application import get_ai_chat_app_service
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.facades.tools_facade import execute_registered_workflow_tool
    from app.application.workflow.workflow_types import PlanGraph
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
    name = f"uncertain-{entrypoint}-{failure.__name__}"
    message = f"新增单位 {name}"
    # Real service composition, authentication, dispatcher, customer store and
    # response formatting remain intact. No model/server request is performed.
    app = get_ai_chat_app_service()

    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", actor.factory)
    monkeypatch.setattr(
        "app.application.ai_chat.chat_evidence.prepare_chat_evidence",
        lambda request, ctx, text: ctx,
    )
    monkeypatch.setattr(
        voice_routes, "_platform_transcribe", AsyncMock(return_value={"text": message})
    )

    def planned(user_id, message, source, context, file_context):
        runtime = app._merge_tool_runtime_context(user_id, message, context)
        output = execute_registered_workflow_tool(
            "customers", "ensure_exists", {"unit_name": name, "_runtime_context": runtime}
        )
        step = AgentStep(
            node_id="customer",
            tool_id="customers",
            action="ensure_exists",
            status="failed",
            output=output,
        )
        run = AgentRun(user_id=user_id, message=message, status="blocked", steps=[step])
        return app._format_agent_run_response(
            PlanGraph(plan_id="customer", intent="customer_write"), run
        )

    monkeypatch.setattr(app, "_try_handle_dynamic_workflow", planned)
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
            state["faults"] += 1
            if failure is OperationalError:
                raise failure("synthetic customer readback", {}, RuntimeError("unavailable"))
            raise failure("synthetic customer readback unavailable")

    event.listen(Engine, "after_cursor_execute", after_sql)
    event.listen(Engine, "before_cursor_execute", before_sql)
    event.listen(Session, "after_commit", committed)
    try:
        if entrypoint == "chat":
            response = ai_intent.ai_chat_unified_alias(
                request, {"message": message, "source": "normal"}
            )
            payload = json.loads(response.body)
            receipt = payload
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
            receipt = payload["data"]["result"]
            text = payload["data"]["result"].get("response", "")
        assert "已创建" not in text
        assert receipt["success"] is False
        assert receipt["execution_state"] == "unknown"
        assert receipt["retryable"] is False and receipt["requires_reconciliation"] is True
        assert state["committed"] and state["faults"] == 1
        assert state["postcommit_reads"] == 1
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
