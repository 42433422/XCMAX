"""Real SQL fences across compat dispatch, transcript replay and save-only repair."""

from __future__ import annotations

import asyncio
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
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import fixture_goal_review
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


@pytest.fixture
def runtime(dynamic_chat_runtime, monkeypatch, tmp_path):
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.domain.shared_services.conversation_service import ConversationService
    from app.fastapi_routes import xcagi_compat_chat_helpers as facade

    actor = dynamic_chat_runtime.actor
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
    service._inject_excel_vector_context = lambda **kw: kw["context"]
    service._inject_wechat_contact_context = lambda **kw: kw["context"]
    service._persist_recallable_chat_turn = lambda **kw: None
    assert not hasattr(AIChatApplicationService, "_try_handle_dynamic_workflow")
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
        monkeypatch.setattr(module, "planner_workflow_interrupt_reply", lambda message: None)
    monkeypatch.setattr(compat, "assert_p2_elevated_claim_or_raise", lambda request: None)
    monkeypatch.setattr(compat, "resolve_ai_tier", lambda request: "standard")
    yield SimpleNamespace(
        actor=actor, service=service, conversation=conversation, compiled=dynamic_chat_runtime
    )
    for lease in tuple(memory._INFLIGHT.values()):
        lease.release()
    memory._INFLIGHT.clear()


def _script_reply(runtime, message, reply):
    runtime.compiled.actions = []
    runtime.compiled.reply = reply
    runtime.compiled.review = lambda prompt: fixture_goal_review(
        prompt, kind="reply", source=message
    )


async def _dispatch(runtime, body, streaming):
    if not streaming:
        return await compat.execute_compat_chat(runtime.actor.request, body)
    chunks = [chunk async for chunk in compat.compat_chat_stream_async(runtime.actor.request, body)]
    events = (
        json.loads(line[6:]) for line in b"".join(chunks).splitlines() if line.startswith(b"data: ")
    )
    return next(event["result"] for event in events if event.get("type") == "done")


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


@pytest.mark.parametrize("settled_by", ["worker", "ack", "history", "withdrawn"])
def test_queued_turn_preserves_one_durable_assistant_id(runtime, monkeypatch, settled_by):
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_runtime.chat import runtime_chat_payload
    from app.application.ai_chat.chat_evidence import _prepare_history
    from app.application.ai_chat.conversation_history import reconcile_queued_chat_reply
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
    from app.infrastructure.tenant_scope import tenant_scope

    body = compat._prepare_compat_chat_body(runtime.actor.request, _body())
    context = body.context
    turn = context["turn_id"]
    owner = str(runtime.actor.user_id)
    run = AgentRun(user_id=owner, message=body.message, run_id="queued-run")
    receipt = {"state": "queued", "turn_id": turn}
    run.metadata.update(
        runtime_context=context,
        runtime_type="xiaox",
        runtime_requests={canonical_digest({"turn_id": turn, "owner": owner}): receipt},
    )
    run.final_output["xiaox_result"] = {"ok": True, "output": "其他轮次的结果"}
    repository = runtime.compiled.repository
    queued = runtime_chat_payload(
        {"run_id": run.run_id, "execution_state": "queued", "output": "队列确认"}
    )
    finished = {
        "state": "returned",
        "result": {
            "run_id": run.run_id,
            "execution_state": "completed",
            "ok": True,
            "output": "本轮结果",
        },
    }
    if settled_by == "ack":
        receipt.update(finished)
    repository.save(run)
    ack = persist_chat_turn(owner, body.message, context, queued)
    if settled_by != "ack":
        evidence = _prepare_history(store, context, "boundary-session", runtime.actor.user_id)
        assert evidence["_chat_history_ids"] == ack["message_ids"][:1]
        receipt.update(finished)
        repository.save(run)
    if settled_by == "withdrawn":
        assert (
            store.delete_messages_from(
                session_id="boundary-session",
                user_id=runtime.actor.user_id,
                message_id=ack["message_ids"][0],
            )
            == 2
        )
        assert not reconcile_queued_chat_reply(context, turn, run.run_id)
        assert _rows(runtime) == []
        return
    if settled_by == "worker":
        assert not reconcile_queued_chat_reply({**context, "tenant_id": 999}, turn, run.run_id)
        assert not reconcile_queued_chat_reply(
            {**context, "_conversation_revision": 1}, turn, run.run_id
        )
        assert reconcile_queued_chat_reply(context, turn, run.run_id)
    with tenant_scope(runtime.actor.tenant_id):
        history = store.get_history(
            session_id="boundary-session", user_id=runtime.actor.user_id, turn_id=turn
        )
    assert _rows(runtime) == [("user", body.message), ("assistant", "本轮结果")]
    assert history["message_count"] == 2
    assert history["turn_receipt"]["message_id"] == ack["message_ids"][1]
    assert [row["id"] for row in history["messages"]] == ack["message_ids"]
    assert (
        persist_chat_turn(owner, body.message, context, queued)["message_ids"] == ack["message_ids"]
    )
    assert _rows(runtime) == [("user", body.message), ("assistant", "本轮结果")]


def test_same_input_retry_repairs_original_chat_reply(runtime, monkeypatch):
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_runtime.chat import runtime_chat_payload
    from app.application.ai_chat.conversation_history import (
        persist_chat_turn,
        reconcile_queued_chat_reply,
    )
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
    from app.infrastructure.tenant_scope import tenant_scope

    body = compat._prepare_compat_chat_body(runtime.actor.request, _body())
    context = body.context
    turn = context["turn_id"]
    owner = str(runtime.actor.user_id)
    run = AgentRun(user_id=owner, message=body.message, run_id="retry-run")
    original_key = canonical_digest({"turn_id": turn, "owner": owner})
    original = {"state": "queued", "turn_id": turn}
    run.metadata.update(
        runtime_context=context,
        runtime_type="xiaox",
        runtime_requests={original_key: original},
        _xiaox_input_data={"attachment_upload_ids": ["owned-file"]},
    )
    repository = runtime.compiled.repository
    repository.save(run)
    queued = runtime_chat_payload(
        {"run_id": run.run_id, "execution_state": "queued", "output": "已排队"}
    )
    ack = persist_chat_turn(owner, body.message, context, queued)
    original.update(
        state="returned",
        result={
            "run_id": run.run_id,
            "execution_state": "blocked",
            "ok": False,
            "reconciliation_required": True,
            "output": "需核对",
        },
    )
    run.status = "blocked"
    repository.save(run)
    assert reconcile_queued_chat_reply(context, turn, run.run_id)

    latest = {
        "run_id": run.run_id,
        "execution_state": "completed",
        "ok": True,
        "output": "校验后的答复",
    }
    retry_key = canonical_digest({"turn_id": "retry-turn", "owner": owner})
    run.metadata["runtime_requests"][retry_key] = {
        "state": "returned",
        "turn_id": "retry-turn",
        "result": latest,
    }
    run.metadata["_xiaox_queued_request"] = {
        "request_key": retry_key,
        "task": run.message,
        "input_data": run.metadata["_xiaox_input_data"],
        "answer_to_waiting_input": False,
    }
    run.final_output["xiaox_result"] = latest
    run.status = "completed"
    repository.save(run)
    with tenant_scope(runtime.actor.tenant_id):
        history = store.get_history(
            session_id="boundary-session", user_id=runtime.actor.user_id, turn_id=turn
        )
    assert _rows(runtime) == [("user", body.message), ("assistant", "校验后的答复")]
    assert history["message_count"] == 2
    assert history["turn_receipt"]["status"] == "completed"
    assert history["turn_receipt"]["message_id"] == ack["message_ids"][1]
    assert [row["id"] for row in history["messages"]] == ack["message_ids"]
    assert not reconcile_queued_chat_reply(context, turn, run.run_id)


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
        assert message == body.message
        if mode == "offline" and withdraw:
            _withdraw_anchor()
        return {"success": True, "response": "reply", "run_id": "boundary-run"}

    monkeypatch.setattr(
        compat, "_business_action", lambda message, **kw: execute(message, kw["runtime_context"])
    )
    actual_persist = runtime.service._persist_chat_turn

    def persist_turn(*args):
        if mode == "online" and withdraw:
            _withdraw_anchor()
        return actual_persist(*args)

    persist = Mock(wraps=persist_turn)
    runtime.service._persist_chat_turn = persist
    body = _body(mode=mode)
    if mode == "offline":
        body.message = "  查询今天的考勤\n"
    _script_reply(runtime, body.message, "reply")
    runtime.compiled.on_turn = lambda binding: execute(binding.run.message, binding.context)
    payload = await _dispatch(runtime, body, streaming)
    if mode == "online":
        assert payload["execution_state"] == "queued"
        assert runtime.compiled.transports == []
        parent = await asyncio.to_thread(runtime.compiled.drain, payload["run_id"])
        assert parent.metadata["runtime_context"]["_conversation_revision"] == 0
        if withdraw:
            assert parent.final_output["xiaox_result"]["error_code"] == "conversation_changed"
        else:
            assert parent.status == "completed", parent.error
    assert len(contexts) == (0 if mode == "online" and withdraw else 1)
    assert persist.call_count == 1
    assert len(runtime.compiled.transports) == int(mode == "online" and not withdraw)
    assert not hasattr(runtime.service, "_try_handle_dynamic_workflow")
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
    before_transports = len(runtime.compiled.transports)
    rejected = await compat.execute_compat_chat(
        runtime.actor.request, _body(message=message.replace("fixture-alpha", "fixture-beta"))
    )
    assert rejected["success"] is False and len(_rows(runtime)) == 2
    assert len(runtime.compiled.transports) == before_transports
    assert not hasattr(runtime.service, "_try_handle_dynamic_workflow")


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
    payload = await _dispatch(runtime, original, streaming)
    assert payload["history_persistence"]["status"] == "saved"
    assert payload["execution_state"] == "queued" and not observed
    parent = await asyncio.to_thread(runtime.compiled.drain, payload["run_id"])
    assert parent.status == "completed", parent.error
    assert len(observed) == 1 and collect.await_args.kwargs["user_id"] == "1"
    assert len(runtime.compiled.model_requests) == 1
    assert all(
        "FINAL-EVIDENCE-MARKER" in json.dumps(prompt) for prompt in runtime.compiled.model_requests
    )
    assert not hasattr(runtime.service, "_try_handle_dynamic_workflow")
    assert _rows(runtime) == [("user", original.message), ("assistant", "attachment reply")]
    context = observed[0]
    assert context["turn_id"] == "boundary-turn"
    replay = memory.prepare_chat_turn(original.message, context)
    assert replay["data"]["replay"] and replay["run_id"] == parent.run_id
    assert replay["execution_state"] == "queued"
    memory._path(memory.conversation_key(context)).unlink()
    replay = memory.prepare_chat_turn(original.message, context)
    assert replay["data"]["replay"] and replay["response"] == "attachment reply"
    assert len(runtime.compiled.transports) == 1


@pytest.mark.asyncio
async def test_failed_ack_stays_cached_until_explicit_save_only_repair(runtime):
    message = " \npassword=fixture-repair\n" + "long source " * 1000 + "  \n"
    _script_reply(runtime, message, "receipt")
    actual_persist = runtime.service._persist_chat_turn

    def lost_ack(*args):
        actual_persist(*args)
        raise TimeoutError("simulated acknowledgement loss")

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
