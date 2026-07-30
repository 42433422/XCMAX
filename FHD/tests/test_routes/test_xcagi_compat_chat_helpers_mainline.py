from __future__ import annotations

import contextvars
import json
from unittest.mock import patch

import pytest
from starlette.requests import Request

from app.fastapi_routes import xcagi_compat_chat_helpers as helpers


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/ai/chat/stream",
            "headers": [],
        }
    )


def _body(message: str = "查询产品 9803") -> helpers.XcagiCompatChatBody:
    return helpers.XcagiCompatChatBody(message=message, user_id="u1")


def _decode_events(chunks: list[bytes]) -> list[dict]:
    return [
        json.loads(chunk.decode("utf-8").removeprefix("data: ").strip())
        for chunk in chunks
    ]


def test_stream_uses_mainline_payload_without_legacy_adapter() -> None:
    payload = {
        "success": True,
        "response": "已查询产品库，找到 1 条记录。\n结果已核验。",
        "run_id": "run_verified",
    }
    with (
        patch.object(helpers, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(helpers, "_ensure_vector_index_if_needed", return_value=None),
        patch.object(helpers, "_stream_mainline_payload", return_value=payload),
        patch.object(
            helpers,
            "start_legacy_chat_run",
            side_effect=AssertionError("legacy adapter must not run"),
        ),
    ):
        events = _decode_events(
            list(helpers._xcagi_planner_stream_bytes(_request(), _body(), ai_tier="p2"))
        )

    assert events == [
        {"type": "token", "text": payload["response"]},
        {"type": "done", "result": payload},
    ]


def test_stream_mainline_preserves_requires_token_contract() -> None:
    payload = {
        "success": True,
        "requires_token": True,
        "token_name": "DB_WRITE_TOKEN",
        "token_description": "数据库写入令牌",
        "response": "请先授权数据库写入。",
    }
    with (
        patch.object(helpers, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(helpers, "_ensure_vector_index_if_needed", return_value=None),
        patch.object(helpers, "_stream_mainline_payload", return_value=payload),
    ):
        events = _decode_events(
            list(helpers._xcagi_planner_stream_bytes(_request(), _body(), ai_tier="p2"))
        )

    assert events == [
        {
            "type": "requires_token",
            "token_name": "DB_WRITE_TOKEN",
            "token_description": "数据库写入令牌",
            "message": "请先授权数据库写入。",
        }
    ]


def test_stream_passes_authenticated_owner_to_mainline() -> None:
    request = _request()
    request.state.user_id = 42
    payload = {"success": True, "response": "账号模型回复"}
    with (
        patch.object(helpers, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(helpers, "_ensure_vector_index_if_needed", return_value=None),
        patch.object(helpers, "_stream_mainline_payload", return_value=payload) as mainline,
    ):
        events = _decode_events(
            list(helpers._xcagi_planner_stream_bytes(request, _body(), ai_tier="p2"))
        )

    assert events[-1] == {"type": "done", "result": payload}
    assert mainline.call_args.kwargs["authenticated_owner_user_id"] == 42


@pytest.mark.asyncio
async def test_async_stream_bridge_propagates_request_context() -> None:
    marker: contextvars.ContextVar[str] = contextvars.ContextVar(
        "stream_request_marker",
        default="missing",
    )
    marker.set("request-bound")

    def fake_stream(*_args, **_kwargs):
        yield marker.get().encode("utf-8")

    with patch.object(helpers, "_xcagi_planner_stream_bytes", side_effect=fake_stream):
        chunks = [
            chunk
            async for chunk in helpers._xcagi_planner_stream_bytes_async(
                _request(),
                _body(),
                ai_tier="p2",
            )
        ]

    assert chunks == [b"request-bound"]
