"""Offline requests share one safe dispatch path across response formats."""

import asyncio
import json
import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request

from app.application.planner_compat.admission import ChatAdmission
from app.application.planner_compat.application import CompatChatApplication, FastPaths
from app.application.planner_compat.protocols import ChatBackends, ChatResponses, ChatTrace
from app.application.planner_compat.runtime import await_with_timeout
from app.application.planner_compat.streaming import CompatStream
from app.application.planner_compat_execute import ChatTurnExecutor
from app.fastapi_routes.xcagi_compat_chat_models import XcagiCompatChatBody
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _components(business):
    admission = ChatAdmission(
        merge_paths=lambda context, _message: (dict(context or {}), []),
        authenticate=lambda _request, context: context,
        with_tier=lambda context, _tier: context,
        authorize_read=lambda *args, **kwargs: (True, None),
        requires_read=lambda _message: False,
        interrupt=lambda _message: None,
        after_interrupt=lambda context: context,
        vector_guard=Mock(side_effect=AssertionError("online index must not run")),
        reply=lambda text, **_kwargs: {"response": text},
    )
    paths = FastPaths(
        business=business,
        kitten=AsyncMock(side_effect=AssertionError("online context must not run")),
    )
    return admission, paths


@pytest.mark.asyncio
@pytest.mark.parametrize("business_result", [None, {"success": True, "response": "本地查询结果"}])
async def test_offline_stream_and_json_match_without_calling_online_paths(
    business_result,
):
    business = Mock(return_value=business_result)
    admission, paths = _components(business)
    trace = Mock(side_effect=lambda payload, **_kwargs: payload)
    executor = Mock()
    executor.trace.attach.side_effect = lambda payload, *_args, **_kwargs: payload
    app = CompatChatApplication(
        admission,
        executor,
        paths,
        Mock(),
        Mock(),
        lambda _r: "standard",
        lambda: 5,
        AsyncMock(),
    )
    stream = CompatStream(
        admission,
        paths,
        Mock(),
        trace,
        lambda payload: (json.dumps(payload, ensure_ascii=False) + "\n").encode(),
        lambda _r: "standard",
        AsyncMock(),
        logging.getLogger(__name__),
    )
    body = XcagiCompatChatBody(message="测试离线查询", mode="offline")
    response = await app.single(Mock(), body)
    events = [json.loads(chunk) async for chunk in stream.run(Mock(), body)]
    assert events[-1]["result"] == response
    assert business.call_count == 2
    admission.vector_guard.assert_not_called()
    if business_result is None:
        assert response["success"] is False
        assert response["data"]["model_called"] is False
    else:
        assert response == business_result


def test_stream_offline_never_creates_remote_client(monkeypatch, trusted_actor):
    from app.fastapi_routes import xcagi_compat_chat_helpers as facade

    factory = Mock(side_effect=AssertionError("remote client must not be created"))
    monkeypatch.setattr(facade, "create_modstore_openai_client_from_request", factory)
    actor = trusted_actor(user_id=73, tenant_id=7, role="offline-reader", permissions=[])
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/chat-stream",
            "headers": [
                (name.lower().encode(), value.encode()) for name, value in actor.headers.items()
            ],
        }
    )
    events = list(
        facade._xcagi_planner_stream_bytes(
            request,
            XcagiCompatChatBody(message="普通问答", mode="offline"),
            ai_tier="standard",
        )
    )
    done = json.loads(events[-1].replace(b"data: ", b"").strip())
    assert done["result"]["success"] is False
    assert done["result"]["data"]["model_called"] is False
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_online_and_offline_request_scopes_are_isolated():
    from app.infrastructure.llm import client

    async def observe(mode):
        with client.request_llm_mode(mode):
            await asyncio.sleep(0)
            return client.resolve_mode()

    assert await asyncio.gather(observe("offline"), observe("online")) == ["offline", "online"]


@pytest.mark.parametrize(
    ("status", "executed", "verified", "expected", "state"),
    [
        ("unavailable", False, True, False, "blocked"),
        ("failed", False, True, False, "blocked"),
        ("submitted", True, True, False, "accepted"),
        ("completed", True, False, False, "blocked"),
        ("verified_empty", True, True, True, "completed"),
    ],
)
def test_business_success_requires_verified_completed_receipt(
    status, executed, verified, expected, state
):
    from app.domain.app_pure.chat_business_safety_core import BusinessChatIntent, _payload

    intent = BusinessChatIntent(domain="attendance", operation="attendance_read")
    result = _payload(
        "result", intent, {"status": status, "executed": executed, "verified": verified}
    )
    assert result["success"] is expected
    assert result["execution_state"] == state


@pytest.mark.asyncio
async def test_online_json_and_stream_share_the_langgraph_mainline():
    receipt = {"success": True, "response": "已查询考勤", "data": {"id": 1}}
    business = Mock(side_effect=AssertionError("online route must use the mainline"))
    admission, paths = _components(business)
    admission = replace(admission, vector_guard=lambda *_args: None)
    mainline_calls = []

    async def mainline(body, context, *, message=None, kitten_extra=None):
        mainline_calls.append((body.message, dict(context), message))
        return receipt

    trace = Mock(side_effect=lambda payload, **_kwargs: payload)
    executor = ChatTurnExecutor(
        ChatBackends(mainline),
        ChatResponses(lambda _timeout: {}, lambda _error: None),
        ChatTrace(attach=lambda payload, *_args, **_kwargs: payload),
        await_with_timeout,
    )
    app = CompatChatApplication(
        admission, executor, paths, Mock(), Mock(), lambda _r: "standard", lambda: 5, AsyncMock()
    )

    async def backend(_request, body, *, ai_tier):
        payload = await mainline(body, body.context or {}, message=body.message)
        yield (json.dumps({"type": "done", "result": payload}) + "\n").encode()

    stream = CompatStream(
        admission,
        paths,
        SimpleNamespace(enrich=AsyncMock()),
        trace,
        lambda payload: (json.dumps(payload, ensure_ascii=False) + "\n").encode(),
        lambda _r: "standard",
        backend,
        logging.getLogger(__name__),
    )
    body = XcagiCompatChatBody(message="查询今天的考勤", mode="online")
    json_result = await app.single(Mock(), body)
    events = [json.loads(chunk) async for chunk in stream.run(Mock(), body)]
    assert events[-1]["result"] == json_result == receipt
    assert [call[0] for call in mainline_calls] == ["查询今天的考勤"] * 2
    business.assert_not_called()
