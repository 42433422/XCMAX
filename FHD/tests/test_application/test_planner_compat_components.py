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
        assert results[index] == {"success": True, "response": label, "run_id": f"run-{label}"}
        identity, client, context = captured[label]
        assert identity == label
        assert client is ports[index].client_value
        assert context["_mod_authorization"] is authorizations[index]
        assert context["run_id"] == context["agent_run_id"] == f"run-{label}"
        assert ports[index].client.call_args.args[0].state.label == label
        ports[index].finish.assert_called_once()


@pytest.mark.asyncio
async def test_batch_interrupt_updates_context_and_failed_turn_does_not_stop_next(
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
    assert [item["success"] for item in result["results"]] == [True, False, True]
    assert result["results"][-1]["response"] == "completed"
    assert all(context["cleared"] and "pending" not in context for context in contexts)
    assert all(context["_mod_authorization"] is authorization for context in contexts)
    assert ports.client.call_count == 2  # Each executed turn uses the shared single-turn API.
    assert all(call.args[0].state.label == "test" for call in ports.client.call_args_list)
    assert ports.start.call_count == ports.finish.call_count == 2


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
        assert [item["success"] for item in result["results"]] == [False, True]
        assert result["results"][1]["run_id"] == "already-traced"
        assert mainline.await_count == 2
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
