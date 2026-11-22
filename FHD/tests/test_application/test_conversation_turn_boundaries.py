"""Real SQL fences across compat dispatch, transcript replay and save-only repair."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.application import planner_compat_service as compat
from app.application.ai_chat import dialogue_memory as memory
from app.application.ai_chat.conversation_history import persist_chat_turn, retry_stored_chat_turn
from app.application.task_conversation_store import task_conversation_store as store
from app.db.models import AIConversation, AIConversationSession
from app.domain.shared_services.conversation_service import ConversationRevisionError
from app.fastapi_routes.xcagi_compat_chat_models import XcagiCompatChatBody
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_http_runtime import compiled_chat_runtime as compiled_chat_runtime
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry
from tests.fixtures.planner_model import goal_review_response


@pytest.fixture
def runtime(compiled_chat_runtime, monkeypatch, tmp_path):
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.domain.shared_services.conversation_service import ConversationService
    from app.fastapi_routes import xcagi_compat_chat_helpers as facade

    actor = compiled_chat_runtime.actor
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setattr(
        "app.application.attachment_artifacts.store._default_root", lambda: tmp_path / "artifacts"
    )

    @contextmanager
    def db():
        with actor.factory() as session:
            yield session

    monkeypatch.setattr("app.application.task_conversation_store.get_db", db)
    monkeypatch.setattr("app.domain.shared_services.conversation_service.get_db", db)
    monkeypatch.setattr(
        "app.domain.shared_services.conversation_service.notify_user", lambda **kw: None
    )
    conversation = ConversationService()
    monkeypatch.setattr("app.services.get_conversation_service", lambda: conversation)
    service = AIChatApplicationService.__new__(AIChatApplicationService)
    service._pending_workflows = {}
    service._inject_excel_vector_context = lambda **kw: kw["context"]
    service._inject_wechat_contact_context = lambda **kw: kw["context"]
    service._persist_recallable_chat_turn = lambda **kw: None
    service._try_handle_dynamic_workflow = Mock(side_effect=AssertionError("retired new-task path"))
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    monkeypatch.setattr("app.application.chat_turn_guard.admit_chat_turn", lambda *args: None)
    monkeypatch.setattr(
        "app.application.ai_chat.chat_evidence.prepare_chat_evidence",
        lambda request, context, message: dict(context),
    )
    for name in ("neuro_notify_chat_received", "neuro_notify_chat_completed"):
        monkeypatch.setattr(f"app.neuro_bus.application_neuro_bridge.{name}", lambda *a: None)
    trace = lambda payload, **kw: {**payload, "run_id": "boundary-run"}
    monkeypatch.setattr(
        "app.application.agent_orchestrator.chat_trace.attach_chat_trace_run", trace
    )
    monkeypatch.setattr(compat, "attach_chat_trace_run", trace)
    monkeypatch.setattr(facade, "attach_chat_trace_run", trace)
    monkeypatch.setattr(compat.PersonaEnricher, "enrich", AsyncMock())
    for module in (compat, facade):
        monkeypatch.setattr(
            module, "_ensure_chat_db_read_authorized", lambda *a, **kw: (True, None)
        )
        monkeypatch.setattr(module, "_message_requires_db_read_token", lambda message: False)
        monkeypatch.setattr(module, "_ensure_vector_index_if_needed", lambda *args: None)
        monkeypatch.setattr(module, "planner_workflow_interrupt_reply", lambda message: None)
    monkeypatch.setattr(compat, "assert_p2_elevated_claim_or_raise", lambda request: None)
    monkeypatch.setattr(compat, "resolve_ai_tier", lambda request: "standard")
    yield SimpleNamespace(
        actor=actor, service=service, conversation=conversation, compiled=compiled_chat_runtime
    )
    for lease in tuple(memory._INFLIGHT.values()):
        lease.release()
    memory._INFLIGHT.clear()


def _script_reply(runtime, message, reply):
    def completion(**kwargs):
        prompt = json.loads(kwargs["messages"][-1]["content"])
        assert prompt["user_message"] == message
        if prompt.get("task") == "audit_goal_coverage":
            return goal_review_response(
                prompt, source=message, node_ids=["model_reply"], outcome="reply"
            )
        return {
            "choices": [{"message": {"content": json.dumps({"mode": "reply", "reply": reply})}}]
        }

    runtime.compiled.completion = completion


def _body(**overrides):
    values = {
        "message": "  完整原文\n",
        "mode": "online",
        "context": {
            "conversation_id": "boundary-session",
            "turn_id": "boundary-turn",
            "memory_capture_enabled": False,
            "_conversation_revision": 999,
            "_conversation_input_fingerprint": "caller-chosen",
        },
    }
    values.update(overrides)
    return XcagiCompatChatBody(**values)


def _rows(runtime):
    with runtime.actor.factory() as db:
        return [
            (row.role, row.content) for row in db.query(AIConversation).order_by(AIConversation.id)
        ]


def _withdraw_anchor():
    message_id = store.save_message(
        session_id="boundary-session", user_id=1, role="user", content="withdraw-anchor"
    )
    assert (
        store.delete_messages_from(session_id="boundary-session", user_id=1, message_id=message_id)
        == 1
    )


def test_personal_plan_basic_chat_uses_authenticated_actor(runtime, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.db.models.user import User
    from app.infrastructure.mods.mod_auth import ModContextMiddleware
    from app.legacy.routes.conversation.compat_routes import router

    with runtime.actor.factory.begin() as db:
        db.get(User, runtime.actor.user_id).account_tier = "personal"
    answer = AsyncMock(return_value={"success": True, "response": "你好，有什么可以帮你？"})
    monkeypatch.setattr(compat, "_execute_ai_chat_mainline", answer)
    application = FastAPI()
    application.add_middleware(ModContextMiddleware)
    application.include_router(router, prefix="/api")
    with TestClient(application) as client:
        response = client.post(
            "/api/ai/chat",
            headers=runtime.actor.headers,
            json={
                "message": "你好",
                "mode": "online",
                "context": {"conversation_id": "personal-chat"},
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["response"] == "你好，有什么可以帮你？"
    assert answer.await_count == 1
    assert answer.call_args.args[1]["local_user_id"] == runtime.actor.user_id


def test_ingress_replaces_client_epoch_but_prepare_never_advances_it(runtime, trusted_actor):
    body = compat._prepare_compat_chat_body(runtime.actor.request, _body())
    assert body.context["_conversation_revision"] == 0
    assert body.context["_conversation_input_fingerprint"] != "caller-chosen"
    _withdraw_anchor()
    with pytest.raises(ConversationRevisionError):
        memory.prepare_chat_turn(body.message, body.context)
    assert body.context["_conversation_revision"] == 0 and _rows(runtime) == []
    other = trusted_actor(user_id=2, tenant_id=runtime.actor.tenant_id)
    with pytest.raises(PermissionError):
        compat._prepare_compat_chat_body(other.request, _body())


@pytest.mark.parametrize("status", ["saved", "failed", "invalidated"])
def test_existing_inner_acknowledgement_is_never_persisted_again(runtime, status):
    body = compat._prepare_compat_chat_body(runtime.actor.request, _body())
    _withdraw_anchor()
    acknowledgement = {"status": status, "revision": 0, "retry": "none"}
    payload = {"success": True, "response": "late", "history_persistence": acknowledgement}
    runtime.service._persist_chat_turn = Mock(side_effect=AssertionError("duplicate persistence"))
    compat._persist_compat_chat_turn(body, payload)
    runtime.service._persist_chat_turn.assert_not_called()
    assert payload["history_persistence"] is acknowledgement and _rows(runtime) == []


def test_missing_epoch_cannot_default_to_unfenced_sql(runtime):
    body = compat._prepare_compat_chat_body(runtime.actor.request, _body())
    body.context.pop("_conversation_revision")
    payload = {"success": True, "response": "late"}
    compat._persist_compat_chat_turn(body, payload)
    assert payload["history_persistence"] == {"status": "invalidated", "retry": "none"}
    assert _rows(runtime) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["offline", "online"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("withdraw", [False, True])
async def test_real_dispatch_captures_epoch_for_json_and_sse(
    runtime, monkeypatch, mode, streaming, withdraw
):
    contexts = []

    def execute(message, context):
        contexts.append(dict(context))
        assert context["_conversation_revision"] == 0
        if withdraw:
            _withdraw_anchor()
        return {"success": True, "response": "reply", "run_id": "boundary-run"}

    monkeypatch.setattr(
        compat, "_business_action", lambda message, **kw: execute(message, kw["runtime_context"])
    )
    persist = Mock(wraps=runtime.service._persist_chat_turn)
    runtime.service._persist_chat_turn = persist
    body = _body(mode=mode)
    _script_reply(runtime, body.message, "reply")
    runtime.compiled.on_turn = lambda binding: execute(binding.run.message, binding.context)
    if streaming:
        chunks = [
            chunk async for chunk in compat.compat_chat_stream_async(runtime.actor.request, body)
        ]
        events = [
            json.loads(line[6:])
            for line in b"".join(chunks).splitlines()
            if line.startswith(b"data: ")
        ]
        payload = next(item["result"] for item in events if item.get("type") == "done")
    else:
        payload = await compat.execute_compat_chat(runtime.actor.request, body)
    assert len(contexts) == 1 and persist.call_count == 1
    assert len(runtime.compiled.transports) == (1 if mode == "online" else 0)
    runtime.service._try_handle_dynamic_workflow.assert_not_called()
    assert payload["history_persistence"]["status"] == ("invalidated" if withdraw else "saved")
    assert _rows(runtime) == ([] if withdraw else [("user", body.message), ("assistant", "reply")])
    with runtime.actor.factory() as db:
        assert db.query(AIConversationSession).one().revision == int(withdraw)


@pytest.mark.parametrize("turn_id", ["", "  normalized-turn\n", "long-turn-" * 20])
def test_harness_turn_normalization_preserves_receipt_identity(runtime, turn_id):
    from app.application.agent_orchestrator.business_harness import ensure_business_harness_context

    original = _body()
    original.context["turn_id"] = turn_id
    body = compat._prepare_compat_chat_body(runtime.actor.request, original)
    assert memory.prepare_chat_turn(body.message, body.context) is None
    context = ensure_business_harness_context(body.context, message=body.message)
    payload = {"success": True, "response": "normalized receipt"}
    payload["history_persistence"] = persist_chat_turn("1", body.message, context, payload)
    memory.settle_chat_turn(body.message, context, payload, "completed")
    memory._path(memory.conversation_key(context)).unlink()
    replay = memory.prepare_chat_turn(body.message, original.context | context)
    assert replay["data"]["replay"] and replay["response"] == "normalized receipt"
    assert len(_rows(runtime)) == 2


@pytest.mark.asyncio
async def test_credential_identity_survives_sql_restore_and_rejects_changed_secret(runtime):
    message = " \npassword=fixture-alpha\n" + "long original " * 1000 + "  \n"
    body = compat._prepare_compat_chat_body(runtime.actor.request, _body(message=message))
    assert memory.prepare_chat_turn(message, body.context) is None
    payload = {"success": True, "response": "receipt"}
    payload["history_persistence"] = persist_chat_turn("1", message, body.context, payload)
    memory.settle_chat_turn(message, body.context, payload, "completed")
    key = memory.conversation_key(body.context)
    raw_projection = json.dumps(memory._read(key, body.context), ensure_ascii=False)
    assert "fixture-alpha" not in raw_projection
    memory._path(key).unlink()
    replay = memory.prepare_chat_turn(message, body.context)
    assert replay["data"]["replay"] and replay["response"] == "receipt"
    mismatch = memory.prepare_chat_turn(
        message.replace("fixture-alpha", "fixture-beta"), body.context
    )
    assert mismatch["success"] is False and mismatch["data"]["replay"]
    before = memory._read(key, body.context)
    memory.settle_chat_turn(
        message.replace("fixture-alpha", "fixture-beta"),
        body.context,
        {"response": "must not overwrite the original receipt"},
        "failed",
    )
    assert memory._read(key, body.context) == before
    assert _rows(runtime)[0][1] == message.replace("fixture-alpha", "[已隐藏]")
    runtime.service._try_handle_dynamic_workflow = Mock(
        side_effect=AssertionError("duplicate execution")
    )
    rejected = await compat.execute_compat_chat(
        runtime.actor.request, _body(message=message.replace("fixture-alpha", "fixture-beta"))
    )
    assert rejected["success"] is False and len(_rows(runtime)) == 2
    runtime.service._try_handle_dynamic_workflow.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_attachment_context_keeps_full_evidence_and_original_turn_identity(
    runtime, monkeypatch, streaming
):
    from app.application.attachment_evidence import evidence_system_block

    evidence = "owned attachment evidence " * 700 + "FINAL-EVIDENCE-MARKER"
    collect = AsyncMock(return_value={"evidence": evidence, "trace": [], "artifacts": []})
    monkeypatch.setattr("app.application.attachment_evidence.collect_evidence", collect)
    original = _body()
    original.context["artifact_ids"] = ["owned-artifact"]
    observed = []

    def execute(**kw):
        assert kw["message"] == original.message
        assert kw["context"]["_conversation_revision"] == 0
        assert kw["context"]["file_context"]["attachment_evidence"] == evidence_system_block(
            evidence
        )
        observed.append(kw["context"])
        return {"success": True, "response": "attachment reply"}

    _script_reply(runtime, original.message, "attachment reply")
    runtime.compiled.on_turn = lambda binding: execute(
        message=binding.run.message, context=binding.context
    )
    if streaming:
        chunks = [
            chunk
            async for chunk in compat.compat_chat_stream_async(runtime.actor.request, original)
        ]
        events = [
            json.loads(line[6:])
            for line in b"".join(chunks).splitlines()
            if line.startswith(b"data: ")
        ]
        payload = next(item["result"] for item in events if item.get("type") == "done")
    else:
        payload = await compat.execute_compat_chat(runtime.actor.request, original)
    assert payload["history_persistence"]["status"] == "saved"
    assert len(observed) == 1 and collect.await_args.kwargs["user_id"] == "1"
    assert len(runtime.compiled.model_requests) == 2
    assert all(
        "FINAL-EVIDENCE-MARKER" in json.dumps(prompt) for prompt in runtime.compiled.model_requests
    )
    runtime.service._try_handle_dynamic_workflow.assert_not_called()
    assert _rows(runtime) == [("user", original.message), ("assistant", "attachment reply")]
    replay = memory.prepare_chat_turn(original.message, observed[0])
    assert replay["data"]["replay"] and replay["response"] == "attachment reply"


@pytest.mark.asyncio
async def test_failed_ack_stays_cached_until_explicit_save_only_repair(runtime):
    message = " \npassword=fixture-repair\n" + "long source " * 1000 + "  \n"
    _script_reply(runtime, message, "receipt")
    actual_persist = runtime.service._persist_chat_turn

    def lost_ack(*args):
        actual_persist(*args)
        raise RuntimeError("simulated acknowledgement loss")

    runtime.service._persist_chat_turn = Mock(side_effect=lost_ack)
    payload = await compat.execute_compat_chat(runtime.actor.request, _body(message=message))
    assert runtime.service._persist_chat_turn.call_count == 1
    assert payload["history_persistence"]["status"] == "failed"
    context = compat._prepare_compat_chat_body(
        runtime.actor.request, _body(message=message)
    ).context
    receipt = memory.stored_turn_receipt(context, "boundary-turn")
    assert receipt["message"] == message.replace("fixture-repair", "[已隐藏]")
    assert receipt["payload"]["history_persistence"]["status"] == "failed"
    acknowledgement = retry_stored_chat_turn(context, "boundary-turn", 0)
    assert acknowledgement["saved"] and len(_rows(runtime)) == 2
    replay = memory.prepare_chat_turn(message, context)
    assert replay["history_persistence"]["status"] == "saved"
    memory._path(memory.conversation_key(context)).unlink()
    assert memory.prepare_chat_turn(message, context)["data"]["replay"]
