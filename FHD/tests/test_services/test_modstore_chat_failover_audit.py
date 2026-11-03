"""Audited template calls must still client-failover on platform 404."""

from __future__ import annotations

import httpx
import pytest

from app.application.market_llm.completions import complete_async
from app.application.market_llm.protocols import (
    ChatInput,
    CompletionPorts,
    Connection,
    ResponsePorts,
)
from app.infrastructure.llm.modstore_chat_failover import is_market_chat_failoverable
from app.infrastructure.modstore_transport import MarketModelError


class _FakeLogger:
    def warning(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _Client:
    def __init__(self, responses):
        self._responses = list(responses)
        self.posts = []

    async def post(self, url, json=None, headers=None):
        self.posts.append({"url": url, "json": json})
        status, body = self._responses.pop(0)
        request = httpx.Request("POST", url)
        return httpx.Response(status, json=body, request=request)


@pytest.mark.asyncio
async def test_complete_async_failovers_with_audit_callback():
    captured = []

    def audit(body, status, request_id):
        captured.append((status, body[:20]))

    client = _Client(
        [
            (404, {"detail": "模型供应商请求失败"}),
            (
                200,
                {
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 1},
                },
            ),
        ]
    )

    async def get_client():
        return client

    ports = CompletionPorts(
        candidates=lambda provider, model: [
            (provider, model),
            ("deepseek", "deepseek-chat"),
        ],
        prepare_sync=lambda messages, provider, model: messages,
        prepare_async=lambda messages, provider, model: _async_identity(messages),
        post_sync=lambda **kwargs: None,
        client=get_client,
        failoverable=is_market_chat_failoverable,
        response=ResponsePorts(
            normalize=lambda payload, provider, model: payload,
            notify=lambda **kwargs: None,
            clock=lambda: 0.0,
            logger=_FakeLogger(),
        ),
        status_code=lambda response, default=200: response.status_code,
    )

    connection = Connection("https://market.example", "secret-token-xyz-999", 1, 30.0)
    request = ChatInput(
        [{"role": "user", "content": "hi"}],
        extra={
            "allow_failover": True,
            "route_token": "pin-platform-default",
            "_reviewed_excel_audit_response": audit,
        },
    )
    result = await complete_async(connection, ("platform", "platform-default"), request, ports)
    assert result["model"] == "deepseek-chat"
    assert len(client.posts) == 2
    # Intermediate 404 must not archive; only the terminal success.
    assert len(captured) == 1
    assert captured[0][0] == 200
    # Failover attempt must drop the pinned route_token.
    assert "route_token" not in (client.posts[1]["json"] or {})
    assert client.posts[0]["json"].get("route_token") == "pin-platform-default"


async def _async_identity(value):
    return value


@pytest.mark.asyncio
async def test_complete_async_terminal_404_raises_market_error_and_audits():
    captured = []

    def audit(body, status, request_id):
        captured.append(status)

    client = _Client([(404, {"detail": "gone"})])

    async def get_client():
        return client

    ports = CompletionPorts(
        candidates=lambda provider, model: [(provider, model)],
        prepare_sync=lambda messages, provider, model: messages,
        prepare_async=lambda messages, provider, model: _async_identity(messages),
        post_sync=lambda **kwargs: None,
        client=get_client,
        failoverable=is_market_chat_failoverable,
        response=ResponsePorts(
            normalize=lambda payload, provider, model: payload,
            notify=lambda **kwargs: None,
            clock=lambda: 0.0,
            logger=_FakeLogger(),
        ),
        status_code=lambda response, default=200: response.status_code,
    )
    connection = Connection("https://market.example", "secret-token-xyz-999", 1, 30.0)
    request = ChatInput(
        [{"role": "user", "content": "hi"}],
        extra={"allow_failover": True, "_reviewed_excel_audit_response": audit},
    )
    with pytest.raises(MarketModelError) as raised:
        await complete_async(connection, ("platform", "platform-default"), request, ports)
    assert raised.value.status_code == 404
    assert captured == [404]
