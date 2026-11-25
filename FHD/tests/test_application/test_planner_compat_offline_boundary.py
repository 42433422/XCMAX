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
        reply=lambda text, **_kwargs: {"response": text},
    )
    paths = FastPaths(
        business=business,
        kitten=AsyncMock(side_effect=AssertionError("online context must not run")),
    )
    return admission, paths


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "business_result", "expected_code", "business_calls"),
    [
        ("查询今天的考勤", None, None, 2),
        ("查询今天的考勤", {"success": True, "response": "本地查询结果"}, None, 2),
        ("普通问答", None, None, 0),
        ("登记明天事假半天", None, "runtime_offline_mutation_blocked", 0),
        ("导出今天考勤", None, "runtime_offline_mutation_blocked", 0),
        ("打印今天考勤", None, "runtime_offline_mutation_blocked", 0),
    ],
)
async def test_offline_stream_and_json_match_without_calling_online_paths(
    message, business_result, expected_code, business_calls
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
    body = XcagiCompatChatBody(message=message, mode="offline")
    response = await app.single(Mock(), body)
    events = [json.loads(chunk) async for chunk in stream.run(Mock(), body)]
    assert events[-1]["result"] == response
    assert business.call_count == business_calls
    executor.execute.assert_not_called()
    stream.backend.assert_not_called()
    paths.kitten.assert_not_awaited()
    if expected_code:
        assert response["success"] is False
        assert response["execution_state"] == "blocked"
        assert response["error_code"] == expected_code
        assert response["data"]["model_called"] is False
    elif business_result is None:
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
@pytest.mark.parametrize("admitted", [False, True])
async def test_json_timeout_returns_only_original_admitted_run(admitted):
    from app.application.planner_compat import runtime

    admission, paths = _components(Mock())
    calls = []

    def worker():
        calls.append("started")
        if admitted:
            runtime.publish_admitted_chat_run("original-run", "test-turn")

    async def mainline(*_args, **_kwargs):
        await asyncio.to_thread(worker)
        raise TimeoutError

    trace = Mock(side_effect=AssertionError("timeout must not create a synthetic run"))
    executor = ChatTurnExecutor(
        ChatBackends(mainline),
        ChatResponses(lambda _timeout: {"requires_reconciliation": True}, lambda _error: None),
        ChatTrace(attach=trace),
        await_with_timeout,
    )
    app = CompatChatApplication(
        admission, executor, paths, Mock(), Mock(), lambda _r: "standard", lambda: 5, AsyncMock()
    )
    body = XcagiCompatChatBody(
        message="需要核对的原操作", mode="online", context={"turn_id": "test-turn"}
    )
    result = await app.single(Mock(), body)
    assert calls == ["started"]
    assert result["requires_reconciliation"] is True
    assert result.get("run_id") == ("original-run" if admitted else None)
    trace.assert_not_called()


@pytest.mark.asyncio
async def test_online_json_and_stream_share_the_langgraph_mainline():
    receipt = {"success": True, "response": "已查询考勤", "data": {"id": 1}}
    business = Mock(side_effect=AssertionError("online route must use the mainline"))
    admission, paths = _components(business)
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


@pytest.mark.asyncio
async def test_offline_batch_never_invokes_legacy_mutation_handlers():
    """The batch adapter must use the same guarded offline path as JSON/SSE."""
    from app.fastapi_routes.xcagi_compat_chat_models import XcagiCompatChatBatchBody

    business = Mock(side_effect=AssertionError("legacy business executor must not run"))
    admission, paths = _components(business)
    executor = Mock()
    executor.trace.attach.side_effect = lambda payload, *_args, **_kwargs: payload
    app = CompatChatApplication(
        admission,
        executor,
        paths,
        Mock(),
        Mock(),
        lambda _request: "standard",
        lambda: 5,
        lambda request, body: app.single(request, body),
    )
    body = XcagiCompatChatBatchBody(
        messages=["登记明天事假半天", "导出今天考勤", "打印今天考勤"],
        mode="offline",
    )
    result = await app.batch(Mock(), body)
    assert result["count"] == result["processed_count"] == 3
    assert all(
        item["data"]["error_code"] == "runtime_offline_mutation_blocked"
        and item["execution_state"] == "blocked"
        for item in result["results"]
    )
    business.assert_not_called()
    executor.execute.assert_not_called()


def test_no_unreviewed_direct_legacy_business_or_offline_dispatch_callers():
    """Catch new direct call sites bypassing the one guarded offline boundary.

    This audits Python calls in FHD/app only; it is not a claim about external
    plugins, packaged clients or the not-yet-integrated Xiaox migration.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app"
    allowed = {
        "try_handle_business_chat_action": {"application/planner_compat_service.py"},
        "offline_turn": {
            "application/planner_compat/application.py",
            "application/planner_compat/streaming.py",
        },
    }
    callers = {name: set() for name in allowed}
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if not any(name in source for name in allowed):
            continue
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            if name in callers:
                callers[name].add(path.relative_to(root).as_posix())
    assert callers == allowed, f"Review/migrate legacy direct dispatch callers: {callers}"
