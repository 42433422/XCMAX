"""Slow fake model admission cannot stall health or outlive a cancelled chat."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from app.application import llm_intent_gate as gate
from app.application import normal_chat_dispatch as dispatch
from app.infrastructure.llm import structured_output as so
from app.infrastructure.request_context import (
    get_current_request,
    reset_current_request,
    set_current_request,
)
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope


@pytest.fixture(autouse=True)
def synthetic_only(monkeypatch):
    gate._cache.clear()
    monkeypatch.setattr(gate, "_eligible_text", lambda text: text)
    monkeypatch.setattr(dispatch, "_has_pending_workflow", lambda _: False)
    monkeypatch.setattr(
        so.invoke,
        "chat_completion_openai_format",
        AsyncMock(side_effect=AssertionError("real provider forbidden")),
    )
    yield
    gate._cache.clear()


def result():
    return so.StructuredResult({"intent": "products", "confidence": 0.95, "slots": {}}, 1, False)


def request(tenant):
    return SimpleNamespace(state=SimpleNamespace(tenant_id=tenant))


def short_deadline(monkeypatch):
    original = gate._completion_request
    monkeypatch.setattr(
        gate, "_completion_request", lambda text: {**original(text), "timeout_seconds": 0.02}
    )


@pytest.mark.asyncio
async def test_health_and_heartbeat_respond_while_real_async_route_waits(monkeypatch):
    from app.fastapi_routes.mounts import health

    started, release = asyncio.Event(), asyncio.Event()
    seen = []
    inner = request(72)

    async def model(*args, **kwargs):
        seen.append((get_current_request(), current_tenant_id(), threading.get_ident()))
        started.set()
        await release.wait()
        return result()

    def handler(route):
        seen.append((get_current_request(), current_tenant_id(), threading.get_ident()))
        return {"success": True, "response": "synthetic"}

    monkeypatch.setattr(so, "complete_structured", model)
    monkeypatch.setattr(dispatch, "build_product_query_response_dict", handler)
    monkeypatch.setattr(
        health,
        "runtime_integrity_snapshot",
        lambda _: {"status": "healthy", "degraded_reasons": []},
    )
    monkeypatch.setattr(
        health, "build_identity", lambda: {"git_sha": "synthetic", "release_id": "synthetic"}
    )
    app = FastAPI()
    health.register_health_routes(app)
    outer = request(41)
    token = set_current_request(outer)
    try:
        with tenant_scope(41):
            task = asyncio.create_task(
                dispatch.try_normal_slot_read_payload_async(
                    "照例核对一下", request=inner, user_id="synthetic"
                )
            )
            try:
                await asyncio.wait_for(started.wait(), 2)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://synthetic.invalid"
                ) as client:
                    replies = await asyncio.wait_for(
                        asyncio.gather(
                            client.get("/api/ping"),
                            client.get("/api/health?lite=true"),
                            asyncio.sleep(0.01),
                        ),
                        0.5,
                    )
                assert [r.status_code for r in replies[:2]] == [200, 200]
                assert not task.done()
            finally:
                release.set()
            assert await task == {"success": True, "response": "synthetic"}
            assert get_current_request() is outer
            assert current_tenant_id() == 41
    finally:
        reset_current_request(token)
    assert [(req, tid) for req, tid, _ in seen] == [(inner, 72), (inner, 72)]
    assert seen[0][2] == threading.get_ident()
    assert seen[1][2] != threading.get_ident()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True], ids=["deadline", "disconnect"])
async def test_model_is_cancelled_without_cache_or_handler(monkeypatch, cancel):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def model(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(so, "complete_structured", model)
    handler = Mock()
    monkeypatch.setattr(dispatch, "build_product_query_response_dict", handler)
    if not cancel:
        short_deadline(monkeypatch)
    task = asyncio.create_task(
        dispatch.try_normal_slot_read_payload_async(
            "照例核对一下", request=request(72), user_id="synthetic"
        )
    )
    await asyncio.wait_for(started.wait(), 2)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert await task is None
    assert stopped.is_set()
    assert gate._cache == {}
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_synchronous_rule_cannot_later_start_model(monkeypatch):
    started, release, stopped = threading.Event(), threading.Event(), threading.Event()

    def slow_rule(message, fallback):
        started.set()
        try:
            release.wait(2)
            fallback(message)
            return {"intent": "unknown"}
        finally:
            stopped.set()

    model = AsyncMock(return_value=result())
    monkeypatch.setattr(dispatch, "_route_with_gate", slow_rule)
    monkeypatch.setattr(so, "complete_structured", model)
    task = asyncio.create_task(
        dispatch.try_normal_slot_read_payload_async(
            "synthetic", request=request(72), user_id="synthetic"
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        assert await asyncio.to_thread(stopped.wait, 2)
    model.assert_not_awaited()
    assert gate._cache == {}


@pytest.mark.asyncio
async def test_cancel_suppressed_by_provider_still_cannot_dispatch_or_cache(monkeypatch):
    async def bad_model(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return result()

    short_deadline(monkeypatch)
    monkeypatch.setattr(so, "complete_structured", bad_model)
    handler = Mock()
    monkeypatch.setattr(dispatch, "build_product_query_response_dict", handler)
    assert (
        await dispatch.try_normal_slot_read_payload_async(
            "照例核对一下", request=request(72), user_id="synthetic"
        )
        is None
    )
    handler.assert_not_called()
    assert gate._cache == {}


@pytest.mark.asyncio
async def test_parallel_requests_keep_tenant_context(monkeypatch):
    seen = []

    async def model(*args, **kwargs):
        before = (get_current_request(), current_tenant_id())
        await asyncio.sleep(0.01)
        assert (get_current_request(), current_tenant_id()) == before
        seen.append(before)
        return result()

    monkeypatch.setattr(so, "complete_structured", model)
    monkeypatch.setattr(
        dispatch,
        "build_product_query_response_dict",
        lambda _: {"response": str(current_tenant_id())},
    )
    requests = [request(71), request(72)]
    replies = await asyncio.gather(
        *(
            dispatch.try_normal_slot_read_payload_async(
                f"照例核对一下{index}", request=req, user_id="synthetic"
            )
            for index, req in enumerate(requests)
        )
    )
    assert replies == [{"response": "71"}, {"response": "72"}]
    assert {tid for _, tid in seen} == {71, 72}
    assert all(req.state.tenant_id == tid for req, tid in seen)


@pytest.mark.parametrize("running_loop", [False, True])
def test_sync_compatibility_honors_deadline_and_context(monkeypatch, running_loop):
    cancelled = threading.Event()
    inner = request(72)

    async def model(*args, **kwargs):
        assert get_current_request() is inner
        assert current_tenant_id() == 72
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.set()

    monkeypatch.setattr(so, "complete_structured", model)

    def invoke():
        with pytest.raises(so.StructuredOutputError, match="timeout"):
            so.complete_structured_sync([], timeout_seconds=0.02)

    async def in_loop():
        invoke()
        assert await asyncio.to_thread(cancelled.wait, 1)

    token = set_current_request(inner)
    try:
        with tenant_scope(72):
            asyncio.run(in_loop()) if running_loop else invoke()
    finally:
        reset_current_request(token)
    assert cancelled.wait(1)


@pytest.mark.asyncio
async def test_stream_cancellation_during_gate_never_enters_planner(monkeypatch):
    from app.application.planner_compat.application import FastPaths
    from app.application.planner_compat.streaming import CompatStream
    from app.fastapi_routes.xcagi_compat_chat_models import XcagiCompatChatBody

    started, stopped = asyncio.Event(), asyncio.Event()

    async def model(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(so, "complete_structured", model)
    backend = Mock()
    stream = CompatStream(
        admission=SimpleNamespace(context=lambda *args: {}),
        fast_paths=FastPaths(
            AsyncMock(return_value=None),
            Mock(),
            dispatch.try_normal_slot_read_payload_async,
            AsyncMock(),
        ),
        persona=Mock(),
        trace=Mock(),
        encode_event=Mock(),
        resolve_tier=Mock(),
        backend=backend,
        logger=Mock(),
    ).run(request(72), XcagiCompatChatBody(message="照例核对一下", user_id="synthetic"))
    task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await stream.aclose()
    assert stopped.is_set()
    assert gate._cache == {}
    backend.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message", ["列出所有产品", "不要删除客户", "导出库存为Excel文件", "照例核对一下"]
)
async def test_async_rules_preserve_sync_policy_and_only_defer_real_fallback(monkeypatch, message):
    synchronous = Mock(return_value=None)
    asynchronous = AsyncMock(return_value=None)
    monkeypatch.setattr(dispatch, "_llm_route", synchronous)
    monkeypatch.setattr(gate, "llm_route_message_async", asynchronous)
    expected = dispatch.route_normal_mode_message(message)
    assert await dispatch.route_normal_mode_message_async(message) == expected
    assert asynchronous.await_count == synchronous.call_count
