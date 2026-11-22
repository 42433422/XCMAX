"""Real entrypoints, host compilation, approval, MCP/SQL receipts and DB faults."""

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
from tests.fixtures.codex_http_runtime import compiled_chat_runtime as compiled_chat_runtime
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry
from tests.fixtures.planner_model import goal_review_response


@pytest.mark.parametrize("entrypoint", ["chat", "voice"])
@pytest.mark.parametrize("failure", [OperationalError, RuntimeError])
def test_committed_customer_uncertainty_survives_real_entrypoint(
    trusted_actor, compiled_chat_runtime, local_tools, monkeypatch, entrypoint, failure
):
    from app.application import get_ai_chat_app_service
    from app.fastapi_routes import ai_intent, voice_routes

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["customer.edit"])
    runtime = compiled_chat_runtime
    runtime.client.headers.update(actor.headers)
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
    # Only external model/ASR I/O is scripted. Compiler/review, authenticated
    # child approval, worker, customer store and receipt formatting remain real.
    get_ai_chat_app_service()

    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", actor.factory)
    monkeypatch.setattr(
        "app.application.ai_chat.chat_evidence.prepare_chat_evidence",
        lambda request, ctx, text: ctx,
    )
    monkeypatch.setattr(
        voice_routes, "_platform_transcribe", AsyncMock(return_value={"text": message})
    )

    def respond(**kwargs):
        prompt = json.loads(kwargs["messages"][-1]["content"])
        if prompt.get("task") == "audit_goal_coverage":
            return goal_review_response(
                prompt, source=message, node_ids=["customer"], outcome="execute"
            )
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "mode": "workflow",
                                "intent": "customer_write",
                                "nodes": [
                                    {
                                        "node_id": "customer",
                                        "tool_id": "customers",
                                        "action": "ensure_exists",
                                        "params": {"unit_name": name},
                                        "risk": "medium",
                                        "idempotent": True,
                                    }
                                ],
                            }
                        )
                    }
                }
            ]
        }

    runtime.completion = respond
    state = {"inserts": 0, "committed": False, "postcommit_reads": 0, "faults": 0}

    def approve_while_turn_waits(binding):
        # The external runtime waits while the real owner approves the frozen
        # child through HTTP. Its next MCP poll reuses the same call identity.
        bridge = runtime.servers[-1].state.codex_tool_bridge
        token = runtime.transports[-1].config.mcp_token
        operation = binding.run.metadata["runtime_expected_operations"][0]
        waiting = bridge.invoke(
            token, "execute_plan", {"call_id": "compiled-fixture-plan", **operation["params"]}
        )
        assert waiting["pending_approval"] is True, waiting
        assert state["inserts"] == 0
        child_id = waiting["run_id"]
        approval = runtime.client.get(f"/api/agent/runs/{child_id}")
        assert approval.status_code == 200, approval.text
        approved = runtime.client.post(
            f"/api/agent/runs/{child_id}/continue",
            json={"approval_grant": approval.json()["approval"]["grant"]},
        )
        assert approved.status_code == 202, approved.text
        assert state["inserts"] == 0
        child = runtime.drain(child_id)
        assert child.status == "blocked", (state, [step.output for step in child.steps])
        assert child.steps[0].output["outcome"] == "unknown"
        assert child.steps[0].output["retryable"] is False

    runtime.on_turn = approve_while_turn_waits

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
        assert len(runtime.admissions) == len(runtime.transports) == 1
        assert len(runtime.model_requests) == 2
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
