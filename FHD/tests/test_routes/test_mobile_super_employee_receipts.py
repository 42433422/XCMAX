"""Original mobile super-employee intents survive lost HTTP delivery."""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pytest
from fastapi import HTTPException

from app.application.task_conversation_store import task_conversation_store
from app.fastapi_routes.mobile_extensions.models import (
    CodexSuperEmployeeMobileMessageBody,
)
from app.fastapi_routes.mobile_extensions.routes_super_employee import (
    SuperEmployeeRoutes,
    SuperEmployeeRoutesPorts,
)
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def bound_super(trusted_actor, monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path / "dialogue"))
    actor = trusted_actor(user_id=71, role="admin")
    service = SimpleNamespace(
        invoke=MagicMock(),
        invoke_stream=MagicMock(),
        read_dispatch_receipt=MagicMock(return_value=None),
        list_messages=MagicMock(side_effect=AssertionError("not a pure read")),
    )

    async def get_user():
        return SimpleNamespace(id=actor.user_id)

    component = SuperEmployeeRoutes(
        SuperEmployeeRoutesPorts(
            mobile_request_user_id=lambda request, user: actor.user_id,
            require_mobile_admin=lambda request, user: ({}, None),
            codex_super_employee_service=lambda: service,
            claude_super_employee_service=lambda: service,
            cursor_super_employee_service=lambda: service,
            trae_super_employee_service=lambda: service,
            mobile_session_meta=lambda request: {},
            factory_context=lambda **kwargs: kwargs["base"],
            stream_super_employee_invoke=lambda *args: component._stream_super_employee_invoke(
                *args
            ),
            sse_line=lambda payload: ("data: " + json.dumps(payload) + "\n\n").encode(),
        ),
        get_user,
    )
    return component, actor, service


def _body():
    return {
        "message": "execute once",
        "context": {
            "conversation_id": "pinned:codex",
            "turn_id": "original-turn",
            "idempotency_key": "original-turn",
            "tenant_id": "forged",
            "local_user_id": 900,
        },
    }


def _history(actor):
    with tenant_scope(actor.tenant_id):
        history = task_conversation_store.get_history(
            session_id="pinned:codex", user_id=actor.user_id, turn_id="original-turn"
        )
    return history.get("turn_receipt") or history.get("active_turn")


async def _events(response):
    raw = b"".join([chunk async for chunk in response.body_iterator]).decode()
    return [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["completed", "accepted", "waiting_approval", "unknown"])
async def test_json_original_turn_is_replayed_without_execution(bound_super, state):
    component, actor, service = bound_super
    service.invoke.return_value = {
        "dispatch": {
            "request_id": "original-dispatch",
            "status": state,
            "task_id": "original-task",
        },
        "assistant_message": {"body": "original reply"},
    }
    responses = [
        await component._invoke(
            actor.request,
            "codex",
            CodexSuperEmployeeMobileMessageBody(**_body()),
            SimpleNamespace(id=actor.user_id),
        )
        for _ in range(2)
    ]
    service.invoke.assert_called_once()
    expected = "queued" if state == "accepted" else state
    for response in responses:
        assert response["data"]["execution_state"] == expected
        assert response["data"]["task_id"] == "original-task"
        assert response["data"]["turn_id"] == "original-turn"
    context = service.invoke.call_args.kwargs["context"]
    assert context["local_user_id"] == actor.user_id
    assert context["tenant_id"] == actor.context["tenant_id"]
    assert _history(actor)["status"] == expected


@pytest.mark.asyncio
async def test_mobile_active_pointer_does_not_store_execution_credentials(bound_super, tmp_path):
    from app.application.ai_chat.active_conversation import active_conversation_for

    component, actor, service = bound_super
    service.invoke.return_value = {"response": "finished original turn"}
    body = _body()
    canaries = ["pointer-secret-canary", "pointer-token-canary", "forged-proof-canary"]
    body["context"].update(
        secret=canaries[0],
        access_token=canaries[1],
        session_id=actor.session_id,
        _actor_authorization={"proof": canaries[2]},
    )
    response = await component._invoke(
        actor.request, "codex", CodexSuperEmployeeMobileMessageBody(**body), None
    )
    assert response["data"]["history_persistence"]["status"] == "saved"
    service.invoke.assert_called_once()
    execution_context = service.invoke.call_args.kwargs["context"]
    assert execution_context["_actor_authorization"] == actor.context["_actor_authorization"]
    assert execution_context["conversation_id"] == execution_context["session_id"] == "pinned:codex"
    pointers = list((tmp_path / "dialogue").glob("*-active.json"))
    assert len(pointers) == 1
    stored = pointers[0].read_text(encoding="utf-8")
    for value in [
        *canaries,
        actor.session_id,
        actor.context["_actor_authorization"]["proof"],
    ]:
        assert value not in stored
    with tenant_scope(actor.tenant_id):
        assert (
            active_conversation_for(actor.user_id, tenant_id=str(actor.tenant_id)) == "pinned:codex"
        )
        assert active_conversation_for(actor.user_id + 1, tenant_id=str(actor.tenant_id)) == ""
        assert active_conversation_for(actor.user_id, tenant_id="other") == ""


@pytest.mark.asyncio
async def test_json_lost_delivery_and_concurrent_duplicate_keep_one_intent(bound_super):
    component, actor, service = bound_super
    started, finish = threading.Event(), threading.Event()

    def invoke(**kwargs):
        started.set()
        assert finish.wait(5)
        return {"response": "persisted after lost delivery"}

    service.invoke.side_effect = invoke
    body = CodexSuperEmployeeMobileMessageBody(**_body())
    original = asyncio.create_task(component._invoke(actor.request, "codex", body, None))
    assert await asyncio.to_thread(started.wait, 5)
    duplicate = await component._invoke(actor.request, "codex", body, None)
    assert duplicate["data"]["execution_state"] == "running"
    original.cancel()
    with pytest.raises(asyncio.CancelledError):
        await original
    finish.set()
    for _ in range(100):
        if _history(actor)["status"] == "completed":
            break
        await asyncio.sleep(0.01)
    assert _history(actor)["message"] == "persisted after lost delivery"
    service.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_stream_disconnect_drains_original_iterator_and_persists_result(
    bound_super,
):
    component, actor, service = bound_super
    finish, closed = asyncio.Event(), asyncio.Event()

    async def source(**kwargs):
        try:
            yield {"type": "token", "text": "partial"}
            await finish.wait()
            yield {"type": "done", "result": {"response": "original stream completed"}}
        finally:
            closed.set()

    service.invoke_stream.side_effect = source
    response = await component._stream_super_employee_invoke(actor.request, "codex", _body(), None)
    assert b"partial" in await anext(response.body_iterator)
    await response.body_iterator.aclose()
    assert _history(actor)["status"] == "running"
    duplicate = await component._stream_super_employee_invoke(actor.request, "codex", _body(), None)
    assert (await _events(duplicate))[-1]["result"]["execution_state"] == "running"
    finish.set()
    await asyncio.wait_for(asyncio.gather(*component._turn_workers), 5)
    assert closed.is_set()
    assert _history(actor)["message"] == "original stream completed"
    assert _history(actor)["durable"] is True
    service.invoke_stream.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [ConnectionError, RuntimeError, TypeError])
async def test_stream_exception_stays_unknown_and_is_never_redispatched(
    bound_super, error_type, caplog
):
    component, actor, service = bound_super
    error = error_type("lost execution acknowledgement")

    async def source(**kwargs):
        yield {"type": "token", "text": "partial"}
        raise error

    service.invoke_stream.side_effect = source
    response = await component._stream_super_employee_invoke(actor.request, "codex", _body(), None)
    assert (await _events(response))[-1]["type"] == "error"
    assert any(record.exc_info and record.exc_info[1] is error for record in caplog.records)
    assert _history(actor)["status"] == "unknown"
    again = await component._stream_super_employee_invoke(actor.request, "codex", _body(), None)
    assert (await _events(again))[-1]["result"]["execution_state"] == "unknown"
    service.invoke_stream.assert_called_once()


@pytest.mark.asyncio
async def test_conflicting_identity_is_rejected_before_execution(bound_super):
    component, actor, service = bound_super
    body = _body()
    body["context"]["idempotency_key"] = "another-turn"
    with pytest.raises(HTTPException) as error:
        await component._stream_super_employee_invoke(actor.request, "codex", body, None)
    assert error.value.status_code == 400
    service.invoke_stream.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["tool", "workspace", "mode", "target_devices", "branch"])
async def test_same_turn_cannot_change_execution_binding(bound_super, change):
    component, actor, service = bound_super
    service.invoke.return_value = {"response": "first result"}
    body = _body()
    await component._invoke(
        actor.request, "codex", CodexSuperEmployeeMobileMessageBody(**body), None
    )
    tool = "claude" if change == "tool" else "codex"
    if change != "tool":
        body["context"]["workspace_id" if change == "workspace" else change] = "changed"
    reply = await component._invoke(
        actor.request, tool, CodexSuperEmployeeMobileMessageBody(**body), None
    )
    assert reply.status_code == 409
    assert json.loads(reply.body)["execution_state"] == "blocked"
    assert _history(actor)["status"] == "completed"
    service.invoke.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("close_body", [False, True])
async def test_admitted_stream_completes_even_when_response_is_never_iterated(
    bound_super, close_body
):
    from app.application.ai_chat import dialogue_memory
    from app.infrastructure.tenant_scope import current_tenant_id

    component, actor, service = bound_super
    seen = []

    async def source(**kwargs):
        seen.append(str(current_tenant_id()))
        for _ in range(50):
            yield {"type": "token", "text": "partial"}
        yield {
            "type": "done",
            "result": {"response": "original result without HTTP consumer"},
        }

    service.invoke_stream.side_effect = source
    response = await component._stream_super_employee_invoke(actor.request, "codex", _body(), None)
    if close_body:
        await response.body_iterator.aclose()
    await asyncio.wait_for(asyncio.gather(*component._turn_workers), 5)
    assert _history(actor)["status"] == "completed"
    context = service.invoke_stream.call_args.kwargs["context"]
    assert not dialogue_memory._turn_is_live(
        dialogue_memory.conversation_key(context), "original-turn"
    )
    assert seen == [str(actor.tenant_id)]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["tool", "workspace"])
async def test_conflict_does_not_fail_or_release_the_running_original_turn(bound_super, change):
    component, actor, service = bound_super
    finish = asyncio.Event()

    async def source(**kwargs):
        yield {"type": "token", "text": "started"}
        await finish.wait()
        yield {"type": "done", "result": {"response": "original completed"}}

    service.invoke_stream.side_effect = source
    await component._stream_super_employee_invoke(actor.request, "codex", _body(), None)
    body = _body()
    if change == "workspace":
        body["context"]["workspace_id"] = "different-workspace"
    conflict = await component._stream_super_employee_invoke(
        actor.request, "claude" if change == "tool" else "codex", body, None
    )
    assert conflict.status_code == 409
    assert json.loads(conflict.body)["execution_state"] == "blocked"
    assert _history(actor)["status"] == "running"
    finish.set()
    await asyncio.wait_for(asyncio.gather(*component._turn_workers), 5)
    assert _history(actor)["status"] == "completed"
    service.invoke_stream.assert_called_once()


@pytest.mark.asyncio
async def test_stream_close_failure_still_settles_unknown(bound_super):
    from app.application.ai_chat import dialogue_memory

    component, actor, service = bound_super

    class BrokenClose:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            raise RuntimeError("close failed")

    service.invoke_stream.return_value = BrokenClose()
    await component._stream_super_employee_invoke(actor.request, "codex", _body(), None)
    await asyncio.wait_for(asyncio.gather(*component._turn_workers, return_exceptions=True), 5)
    assert _history(actor)["status"] == "unknown"
    context = service.invoke_stream.call_args.kwargs["context"]
    assert not dialogue_memory._turn_is_live(
        dialogue_memory.conversation_key(context), "original-turn"
    )


@pytest.mark.asyncio
async def test_sql_reconstruction_preserves_original_dispatch_and_admission(
    bound_super,
):
    from app.application.ai_chat import dialogue_memory

    component, actor, service = bound_super
    service.invoke.return_value = {
        "dispatch": {
            "request_id": "original-dispatch",
            "task_id": "original-task",
            "status": "queued",
        }
    }
    body = CodexSuperEmployeeMobileMessageBody(**_body())
    await component._invoke(actor.request, "codex", body, None)
    context = service.invoke.call_args.kwargs["context"]
    dialogue_memory._path(dialogue_memory.conversation_key(context)).unlink()
    service.read_dispatch_receipt.return_value = {
        "dispatch": {
            "request_id": "original-dispatch",
            "task_id": "original-task",
            "status": "completed",
        },
        "assistant_message": {"body": "read from original Para task"},
    }
    fresh = SuperEmployeeRoutes(component.ports, lambda: None)
    response = fresh._messages(actor.request, "codex", 80, None, "pinned:codex", "original-turn")
    assert response["data"]["turn_receipt"]["status"] == "completed"
    service.read_dispatch_receipt.assert_called_once_with(
        user_id=actor.user_id, request_id="original-dispatch", task_id="original-task"
    )
    replay = await fresh._invoke(actor.request, "codex", body, None)
    assert replay["data"]["execution_state"] == "queued"
    service.invoke.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["completed", "running", "missing"])
async def test_exact_turn_get_refreshes_only_the_original_dispatch(bound_super, state):
    component, actor, service = bound_super
    service.invoke.return_value = {
        "dispatch": {
            "request_id": "original-dispatch",
            "task_id": "original-task",
            "status": "queued",
        }
    }
    await component._invoke(
        actor.request, "codex", CodexSuperEmployeeMobileMessageBody(**_body()), None
    )
    service.invoke.reset_mock(side_effect=True)
    service.invoke.side_effect = AssertionError("GET may not execute")
    service.read_dispatch_receipt.return_value = (
        None
        if state == "missing"
        else {
            "dispatch": {
                "request_id": "original-dispatch",
                "task_id": "original-task",
                "status": state,
            },
            "assistant_message": {"body": "authoritative task receipt"},
        }
    )
    response = component._messages(
        actor.request, "codex", 80, None, "pinned:codex", "original-turn"
    )
    assert response["data"]["turn_receipt"]["status"] == (
        "unknown" if state == "missing" else state
    )
    service.read_dispatch_receipt.assert_called_once_with(
        user_id=actor.user_id, request_id="original-dispatch", task_id="original-task"
    )
    service.invoke.assert_not_called()
    service.list_messages.assert_not_called()


@pytest.mark.parametrize(
    "state",
    ["completed", "running", "missing", "wrong_task", "unbound", "messages_only"],
)
def test_dispatch_reader_never_backfills_or_invokes(state, tmp_path):
    from app.application.super_employee_service import (
        CODEX_PROFILE,
        SuperEmployeeService,
    )

    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    request = {
        "user_id": 71,
        "employee_id": service._p.employee_id,
        "request_id": "original-dispatch",
        "created_at": "2026-11-21T00:00:00Z",
        "dispatch_receipt": {
            "request_id": "original-dispatch",
            "task_id": "original-task",
            "dispatcher": "para_api",
            "status": "accepted",
            "accepted": True,
            "api_url": "" if state == "unbound" else "https://para.test",
        },
    }
    outbox_path = None
    original_outbox = None
    if state != "messages_only":
        service._messages.write_outbox(request, status="accepted", accepted=True, reason="")
        outbox_path = next(service._messages.outbox_dir.glob("*.json"))
        original_outbox = outbox_path.read_bytes()
    service._read_all_message_rows = MagicMock(
        side_effect=AssertionError("presentation rows are not dispatch authority")
    )
    service._para_api_url = lambda: "https://para.test"
    service._http_client_factory = MagicMock()
    service._para_token = MagicMock(return_value="read-token")
    service._para_request = MagicMock(
        return_value={
            "task": (
                None
                if state == "missing"
                else {
                    "id": "other-task" if state == "wrong_task" else "original-task",
                    "status": state,
                }
            )
        }
    )
    service._para_task_status_reply = lambda task: "task receipt"
    service.list_messages = MagicMock(side_effect=AssertionError("may backfill CLI"))
    service.invoke = MagicMock(side_effect=AssertionError("may not invoke"))
    service._compose_direct_chat_reply = MagicMock(side_effect=AssertionError("may not run CLI"))
    service._dispatching.dispatch = MagicMock(side_effect=AssertionError("may not redispatch"))
    receipt = service.read_dispatch_receipt(
        user_id=71, request_id="original-dispatch", task_id="original-task"
    )
    assert (receipt is None) is (state in {"missing", "wrong_task", "unbound", "messages_only"})
    if state in {"completed", "running"}:
        assert receipt["dispatch"] == {
            "request_id": "original-dispatch",
            "task_id": "original-task",
            "dispatcher": "para_api",
            "accepted": True,
            "status": state,
            "task_status": state,
            "reconciliation_required": False,
        }
        assert receipt["assistant_message"]["body"] == "task receipt"
    assert (
        service.read_dispatch_receipt(
            user_id=72, request_id="original-dispatch", task_id="original-task"
        )
        is None
    )
    if state in {"unbound", "messages_only"}:
        service._para_request.assert_not_called()
        service._para_token.assert_not_called()
    else:
        service._para_request.assert_called_once_with(
            ANY,
            "https://para.test",
            "read-token",
            "GET",
            "/api/tasks/original-task",
            json_body=None,
        )
    if outbox_path is not None:
        assert outbox_path.read_bytes() == original_outbox
    else:
        assert not list(service._messages.outbox_dir.glob("*.json"))
    service._dispatching.dispatch.assert_not_called()
    service.list_messages.assert_not_called()
    service._read_all_message_rows.assert_not_called()
    service.invoke.assert_not_called()
    service._compose_direct_chat_reply.assert_not_called()
