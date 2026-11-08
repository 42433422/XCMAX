"""Request ownership and production fallback behavior at the public chat API."""

from __future__ import annotations

import asyncio
import importlib.util
import threading
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, Request

from app.application import planner_compat_service as service
from app.fastapi_routes.xcagi_compat_chat_models import (
    XcagiCompatChatBatchBody,
    XcagiCompatChatBody,
)


def _facade(name: str) -> ModuleType:
    path = Path(service.__file__)
    spec = importlib.util.spec_from_file_location(f"app.application.{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(label: str = "test") -> Request:
    return Request({"type": "http", "headers": [], "state": {"label": label}})


def _bind(monkeypatch: pytest.MonkeyPatch, facade: ModuleType, label: str) -> SimpleNamespace:
    client = object()
    ports = SimpleNamespace(
        client=Mock(return_value=client),
        start=Mock(return_value=SimpleNamespace(run_id=f"run-{label}")),
        finish=Mock(side_effect=lambda run_id, payload, **_kw: {**payload, "run_id": run_id}),
        attach=Mock(side_effect=lambda payload, *_a, **_kw: payload),
    )
    bindings = {
        "_merge_runtime_context_with_message_paths": lambda context, _message: (
            dict(context or {}),
            [],
        ),
        "_runtime_context_with_authenticated_actor": lambda _request, context: context,
        "assert_p2_elevated_claim_or_raise": lambda _request: None,
        "resolve_ai_tier": lambda _request: "p1",
        "runtime_context_with_tier": lambda context, tier: {**context, "ai_tier": tier},
        "_client_issue_payload": AsyncMock(return_value=None),
        "_business_action": lambda *_a, **_kw: None,
        "_slot_read": AsyncMock(return_value=None),
        "_kitten_context": AsyncMock(side_effect=lambda context, _message: (context, {})),
        "_ensure_chat_db_read_authorized": lambda *_a, **_kw: (True, None),
        "_message_requires_db_read_token": lambda _message: False,
        "planner_workflow_interrupt_reply": lambda _message: None,
        "_ensure_vector_index_if_needed": lambda *_a: None,
        "_xcagi_chat_timeout_seconds": lambda: 5.0,
        "_xcagi_compat_reply_payload": lambda reply, **kw: {
            "success": True,
            "response": reply,
            **(
                {"data": {"runtime_context": kw["runtime_context_update"]}}
                if "runtime_context_update" in kw
                else {}
            ),
        },
        "_clear_legacy_tool_result_if_reply_has_no_records": lambda _reply: None,
        "create_modstore_openai_client_from_request": ports.client,
        "start_legacy_chat_run": ports.start,
        "finalize_legacy_chat_run": ports.finish,
        "_attach_compat_chat_trace": ports.attach,
    }
    for name, value in bindings.items():
        monkeypatch.setattr(facade, name, value)
    ports.client_value = client
    return ports


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code,processed", [(503, 1), (400, 2)])
async def test_batch_preserves_structured_http_receipts_and_pauses_uncertain_errors(
    monkeypatch: pytest.MonkeyPatch, status_code: int, processed: int
) -> None:
    facade = _facade("planner_structured_failure")
    _bind(monkeypatch, facade, "structured-failure")
    execute = AsyncMock(
        side_effect=[
            HTTPException(
                status_code=status_code,
                detail={
                    "message": "执行未确认",
                    "run_id": "original-run",
                    "data": {"receipt_id": "receipt-1"},
                },
            ),
            {"success": True, "run_id": "next-run"},
        ]
    )
    monkeypatch.setattr(facade, "_execute_ai_chat_mainline", execute)
    result = await facade.execute_compat_chat_batch(
        _request(),
        XcagiCompatChatBatchBody(
            messages=["first", "second"], context={"use_ai_chat_mainline": True}
        ),
    )
    assert result["results"][0]["run_id"] == "original-run"
    assert result["results"][0]["data"]["receipt_id"] == "receipt-1"
    assert result["processed_count"] == execute.await_count == processed
    assert result["execution_state"] == ("blocked" if status_code >= 500 else "failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_independent_facades_keep_request_client_trace_and_thread_context(
    monkeypatch: pytest.MonkeyPatch, batch: bool
) -> None:
    task_identity = ContextVar("planner_test_identity")
    barrier = threading.Barrier(2)
    captured: dict[str, tuple] = {}
    facades = [_facade("planner_left"), _facade("planner_right")]
    ports = [
        _bind(monkeypatch, facade, label)
        for facade, label in zip(facades, ("left", "right"), strict=True)
    ]
    authorizations = [{"mod_id": label} for label in ("left", "right")]

    async def execute(index: int):
        label = ("left", "right")[index]

        def legacy(message, **kwargs):
            barrier.wait(timeout=5)
            captured[label] = (task_identity.get(), kwargs["client"], kwargs["runtime_context"])
            return message

        monkeypatch.setattr(facades[index], "run_agent_chat", legacy)
        context = {"use_legacy_chat_adapter": True, "_mod_authorization": authorizations[index]}
        token = task_identity.set(label)
        request = _request(label)
        try:
            if batch:
                payload = await facades[index].execute_compat_chat_batch(
                    request, XcagiCompatChatBatchBody(messages=[label], context=context)
                )
                return payload["results"][0]
            return await facades[index].execute_compat_chat(
                request, XcagiCompatChatBody(message=label, context=context)
            )
        finally:
            task_identity.reset(token)

    results = await asyncio.gather(execute(0), execute(1))
    for index, label in enumerate(("left", "right")):
        identity, client, context = captured[label]
        assert results[index] == {
            "success": True,
            "response": label,
            "run_id": f"run-{label}",
            "turn_id": context["turn_id"],
        }
        assert results[index]["turn_id"] != results[1 - index]["turn_id"]
        assert identity == label
        assert client is ports[index].client_value
        assert context["_mod_authorization"] is authorizations[index]
        assert context["run_id"] == context["agent_run_id"] == f"run-{label}"
        assert ports[index].client.call_args.args[0].state.label == label
        ports[index].finish.assert_called_once()


@pytest.mark.asyncio
async def test_batch_interrupt_updates_context_and_uncertain_failure_stops_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade = _facade("planner_batch")
    ports = _bind(monkeypatch, facade, "batch")
    authorization = {"mod_id": "owned-mod"}
    contexts = []
    monkeypatch.setattr(
        facade,
        "planner_workflow_interrupt_reply",
        lambda message: "cancelled" if message == "cancel" else None,
    )
    monkeypatch.setattr(
        facade,
        "runtime_context_after_workflow_interrupt",
        lambda context: {
            "use_legacy_chat_adapter": True,
            "_mod_authorization": context["_mod_authorization"],
            "cleared": True,
        },
    )

    def legacy(message, **kwargs):
        contexts.append(kwargs["runtime_context"])
        if message == "bad":
            raise RuntimeError("failed turn")
        return "completed"

    monkeypatch.setattr(facade, "run_agent_chat", legacy)
    result = await facade.execute_compat_chat_batch(
        _request(),
        XcagiCompatChatBatchBody(
            messages=["cancel", "bad", "good"],
            context={"pending": "old", "_mod_authorization": authorization},
        ),
    )
    assert result["count"] == 3
    assert result["success"] is False
    assert [item["success"] for item in result["results"]] == [True, False, False]
    assert result["execution_state"] == "blocked"
    assert result["results"][1]["requires_reconciliation"] is True
    assert result["results"][-1]["data"]["status"] == "not_started"
    assert all(context["cleared"] and "pending" not in context for context in contexts)
    assert all(context["_mod_authorization"] is authorization for context in contexts)
    assert ports.client.call_count == 1  # The unconfirmed turn must not dispatch its successor.
    assert all(call.args[0].state.label == "test" for call in ports.client.call_args_list)
    assert ports.start.call_count == ports.finish.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pending", "state"),
    [
        ({"requires_token": True, "token_name": "DB_WRITE_TOKEN"}, "waiting_approval"),
        ({"data": {"requires_token": True}}, "waiting_approval"),
        ({"result": {"pending_approval": True}}, "waiting_approval"),
        ({"legacy_tool_records": [{"output": {"pending_approval": True}}]}, "waiting_approval"),
        ({"tool_records": [{"output": {"outcome": "unknown"}}]}, "blocked"),
        ({"data": {"status": "waiting_user"}}, "waiting_user"),
        ({"result": {"needs_user_input": True}}, "waiting_user"),
        ({"status": "paused"}, "paused"),
        ({"data": {"status": "unknown"}}, "blocked"),
        ({"requires_token": True, "data": {"status": "unknown"}}, "blocked"),
        ({"status": "running", "result": {"pending_approval": True}}, "waiting_approval"),
        ({"data": {"status": "running"}}, "blocked"),
        ({"result": {"outcome": "outcome_unknown"}}, "blocked"),
        ({"result": {"execution_state": "inflight"}}, "blocked"),
        ({"result": {"status": "in_progress"}}, "blocked"),
        ({"result": {"status": "approval_required"}}, "waiting_approval"),
        ({"result": {"status": "authorization_required"}}, "waiting_approval"),
        ({"result": {"status": "needs_user_input"}}, "waiting_user"),
        ({"result": {"status": "partial"}}, "blocked"),
        ({"result": {"status": "partial_success"}}, "blocked"),
        ({"result": {"status": "blocked"}}, "blocked"),
        ({"outputs": {"first": {"outcome": "unknown"}}}, "blocked"),
        ({"node_outputs": {"first": {"outcome": "unknown"}}}, "blocked"),
    ],
)
async def test_batch_retains_receipts_and_does_not_execute_after_a_pending_item(
    monkeypatch: pytest.MonkeyPatch, pending: dict, state: str
) -> None:
    facade = _facade("planner_pending_batch")
    _bind(monkeypatch, facade, "pending")
    first = {"success": True, "response": "已完成", "run_id": "finished-run"}
    waiting = {"success": True, "run_id": "pending-run", **pending}
    execute = AsyncMock(side_effect=[first, waiting])
    monkeypatch.setattr(facade, "_execute_ai_chat_mainline", execute)
    legacy = Mock(side_effect=AssertionError("a pending batch must not fall back"))
    monkeypatch.setattr(facade, "run_agent_chat", legacy)

    result = await facade.execute_compat_chat_batch(
        _request(),
        XcagiCompatChatBatchBody(
            messages=["first", "pending", "must not execute"],
            context={"turn_id": "batch-with-pause", "use_ai_chat_mainline": True},
        ),
    )

    assert result["success"] is False
    assert result["execution_state"] == state
    assert result["wait_reason"]
    assert result["count"] == 3 and result["processed_count"] == 2
    assert result["results"][:2] == [first, waiting]
    unstarted = result["results"][2]
    assert unstarted["data"]["status"] == "not_started"
    assert unstarted["data"]["turn_id"] == result["turn_ids"][2]
    assert unstarted["data"]["blocked_by_turn_id"] == result["turn_ids"][1]
    assert execute.await_count == 2
    legacy.assert_not_called()


@pytest.mark.asyncio
async def test_batch_item_identity_is_stable_on_retry_and_scoped_to_the_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade = _facade("planner_batch_identity")
    _bind(monkeypatch, facade, "identity")
    turns = []

    async def replay(_body, context, **_kwargs):
        turns.append(context["turn_id"])
        return {"success": True, "run_id": context["turn_id"]}

    monkeypatch.setattr(facade, "_execute_ai_chat_mainline", replay)
    context = {"turn_id": "stable-batch", "use_ai_chat_mainline": True}
    body = XcagiCompatChatBatchBody(messages=["same", "same"], context=context)
    first = await facade.execute_compat_chat_batch(_request(), body)
    retry = await facade.execute_compat_chat_batch(_request(), body)
    other = await facade.execute_compat_chat_batch(
        _request(), body.model_copy(update={"context": {**context, "turn_id": "other-batch"}})
    )

    assert first["batch_turn_id"] == "stable-batch"
    assert first["turn_ids"] == retry["turn_ids"] == turns[:2] == turns[2:4]
    assert len(set(first["turn_ids"])) == 2
    assert not set(first["turn_ids"]) & set(other["turn_ids"])
    assert body.context == context


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [{"success": False}, {"status": "error"}, {"status": "failure"}]
)
async def test_batch_does_not_report_nested_business_failure_as_success(
    monkeypatch: pytest.MonkeyPatch,
    failure: dict,
) -> None:
    facade = _facade("planner_batch_business_failure")
    _bind(monkeypatch, facade, "business-failure")
    execute = AsyncMock(
        side_effect=[
            {"success": True, "run_id": "failed-run", "result": failure},
            {"success": True, "run_id": "completed-run"},
        ]
    )
    monkeypatch.setattr(facade, "_execute_ai_chat_mainline", execute)
    result = await facade.execute_compat_chat_batch(
        _request(),
        XcagiCompatChatBatchBody(
            messages=["failed", "independent next item"],
            context={"use_ai_chat_mainline": True},
        ),
    )
    assert result["success"] is False
    assert result["execution_state"] == "failed"
    assert result["processed_count"] == 2
    assert execute.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("failure", [RuntimeError, TimeoutError])
async def test_production_failure_never_implicitly_retries_legacy(
    monkeypatch: pytest.MonkeyPatch, batch: bool, failure: type[Exception]
) -> None:
    facade = _facade("planner_production")
    ports = _bind(monkeypatch, facade, "production")
    for name in (
        "PYTEST_CURRENT_TEST",
        "XCAGI_USE_LEGACY_CHAT_ADAPTER",
        "XCAGI_ALLOW_LEGACY_CHAT_FALLBACK",
    ):
        monkeypatch.delenv(name, raising=False)
    mainline = AsyncMock(
        side_effect=[failure("unavailable"), {"success": True, "run_id": "already-traced"}]
    )
    legacy = Mock(side_effect=AssertionError("legacy retry must not execute"))
    monkeypatch.setattr(facade, "_execute_ai_chat_mainline", mainline)
    monkeypatch.setattr(facade, "run_agent_chat", legacy)
    if batch:
        result = await facade.execute_compat_chat_batch(
            _request(), XcagiCompatChatBatchBody(messages=["bad", "good"])
        )
        assert result["execution_state"] == "blocked"
        assert result["results"][0]["requires_reconciliation"] is True
        assert result["results"][1]["data"]["status"] == "not_started"
        assert mainline.await_count == 1
    elif failure is RuntimeError:
        with pytest.raises(HTTPException, match="503"):
            await facade.execute_compat_chat(_request(), XcagiCompatChatBody(message="bad"))
    else:
        result = await facade.execute_compat_chat(_request(), XcagiCompatChatBody(message="bad"))
        assert result["success"] is False
    legacy.assert_not_called()
    ports.start.assert_not_called()
    ports.finish.assert_not_called()
    assert ports.attach.call_count == (1 if failure is TimeoutError else 0)


@pytest.mark.asyncio
async def test_timeout_boundary_consumes_task_when_wait_fails_before_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = []
    executed = False

    async def work():
        nonlocal executed
        executed = True

    async def fail_early(task, *, timeout):
        tasks.append(task)
        raise TimeoutError("before await")

    monkeypatch.setattr(service.asyncio, "wait_for", fail_early)
    with pytest.raises(TimeoutError, match="before await"):
        await service._await_with_timeout(work(), timeout=1)
    assert not executed
    assert len(tasks) == 1 and tasks[0].cancelled()


@pytest.mark.asyncio
async def test_streams_bind_each_facade_and_close_the_owned_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = []
    facades = [_facade("planner_stream_a"), _facade("planner_stream_b")]
    streams = []
    for facade, label in zip(facades, ("a", "b"), strict=True):
        _bind(monkeypatch, facade, label)

        async def backend(_request, _body, *, ai_tier, label=label):
            try:
                yield f"{label}:{ai_tier}:first".encode()
                yield f"{label}:{ai_tier}:last".encode()
            finally:
                closed.append(label)

        monkeypatch.setattr(facade, "_xcagi_planner_stream_bytes_async", backend)
        streams.append(
            facade.compat_chat_stream_async(
                _request(label), XcagiCompatChatBody(message="stream", system_prompt="provided")
            )
        )
    try:
        assert await anext(streams[0]) == b"a:p1:first"
        assert await anext(streams[1]) == b"b:p1:first"
        await streams[0].aclose()
        assert closed == ["a"]
        assert await anext(streams[1]) == b"b:p1:last"
    finally:
        await streams[0].aclose()
        await streams[1].aclose()
    assert closed == ["a", "b"]
