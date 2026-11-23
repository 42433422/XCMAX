"""Audited template calls must still client-failover on platform 404."""

from __future__ import annotations

import json
from unittest.mock import Mock

import httpx
import pytest

from app.application.market_llm.completions import complete_async, complete_sync, post_sync
from app.application.market_llm.protocols import (
    ChatInput,
    CompletionPorts,
    Connection,
    ResponsePorts,
    StreamPorts,
)
from app.application.market_llm.streaming import stream_async, stream_sync
from app.infrastructure.llm.modstore_chat_failover import is_market_chat_failoverable
from app.infrastructure.modstore_transport import (
    MarketModelError,
    aiter_market_sse_data_payloads,
    iter_market_sse_data_payloads,
)


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

    async def post(self, url, json=None, headers=None, timeout=None):
        assert isinstance(timeout, httpx.Timeout) and timeout.read <= 30
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
    with pytest.raises((MarketModelError, ValueError)) as raised:
        await complete_async(connection, ("platform", "platform-default"), request, ports)
    if isinstance(raised.value, MarketModelError):
        assert raised.value.status_code == 404
    else:
        assert "平台错误(404)" in str(raised.value)
    assert captured == [404]


_MODES = ["sync", "async", "sync-stream", "async-stream"]


async def _call_transport(mode, handler, extra, candidates):
    """Exercise actual payload/HTTP ownership in all four transport entry points."""
    connection = Connection("https://market.example", "synthetic-token", 7, 30.0)
    request = ChatInput([{"role": "user", "content": "hello"}], extra=extra)
    response_ports = ResponsePorts(
        normalize=lambda payload, provider, model: payload,
        notify=lambda **kwargs: None,
        clock=lambda: 0.0,
        logger=_FakeLogger(),
    )
    transport = httpx.MockTransport(handler)

    def sync_client(**kwargs):
        return httpx.Client(transport=transport, **kwargs)

    def send_sync(**kwargs):
        return post_sync(
            connection,
            (kwargs["provider"], kwargs["model"]),
            ChatInput(kwargs["messages"], extra=kwargs["extra"] or {}),
            kwargs["allow_failover"],
            sync_client,
            response_ports,
        )

    async with httpx.AsyncClient(transport=transport) as client:

        async def get_client():
            return client

        common = {
            "candidates": candidates,
            "prepare_sync": lambda messages, provider, model: messages,
            "prepare_async": lambda messages, provider, model: _async_identity(messages),
            "failoverable": is_market_chat_failoverable,
            "status_code": lambda response, default=200: response.status_code,
        }
        if mode in {"sync", "async"}:
            ports = CompletionPorts(
                **common, post_sync=send_sync, client=get_client, response=response_ports
            )
            if mode == "sync":
                return complete_sync(connection, ("primary", "first"), request, ports)
            return await complete_async(connection, ("primary", "first"), request, ports)
        ports = StreamPorts(
            **common,
            sync_client=sync_client,
            async_client=get_client,
            sync_payloads=lambda response: iter_market_sse_data_payloads(
                response, payload_has_content=lambda data: True
            ),
            async_payloads=lambda response: aiter_market_sse_data_payloads(
                response, payload_has_content=lambda data: True
            ),
            connect_timeout=lambda: 10.0,
            logger=response_ports.logger,
        )
        if mode == "sync-stream":
            return list(stream_sync(connection, ("primary", "first"), request, ports))
        return [
            part async for part in stream_async(connection, ("primary", "first"), request, ports)
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    "policy", ["environment", "explicit", "audit", "byok", "user_override", "pinned"]
)
async def test_transport_failover_veto_applies_to_discovery_and_platform(monkeypatch, mode, policy):
    monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER", "0" if policy == "environment" else "1")
    posted = []
    extra = {
        "environment": {"allow_failover": True},
        "explicit": {"allow_failover": False},
        "audit": {"_reviewed_excel_audit_response": lambda *args: None},
        "byok": {"allow_failover": True, "key_source": "byok"},
        "user_override": {"allow_failover": True, "key_source": "user_override"},
        "pinned": {"route_token": "synthetic-pin"},
    }[policy]

    def respond(request):
        posted.append(json.loads(request.content))
        return httpx.Response(429, json={"error": "quota exhausted"})

    candidates = Mock(return_value=[("primary", "first"), ("backup", "second")])
    with pytest.raises(ValueError):
        await _call_transport(mode, respond, extra, candidates)
    candidates.assert_not_called()
    assert len(posted) == 1 and posted[0]["allow_failover"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("terminal_status", [200, 429, 401, 402, 403])
async def test_bounded_failover_owns_route_pin_request_key_and_terminal_receipt(
    monkeypatch, mode, terminal_status
):
    monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER", "1")
    posted, archived = [], []

    def respond(request):
        posted.append(json.loads(request.content))
        status = terminal_status if terminal_status in {401, 402, 403} or len(posted) == 2 else 429
        return httpx.Response(
            status,
            json={"content": "backup reply"} if status == 200 else {"error": "quota exhausted"},
        )

    extra = {
        "allow_failover": True,
        "key_source": "platform",
        "route_token": "synthetic-pin",
        "config_revision": "r1",
        "client_request_id": "synthetic-original",
        "_reviewed_excel_audit_response": lambda body, status, request_id: archived.append(status),
    }
    candidates = Mock(return_value=[("primary", "first"), ("backup", "second")])
    if terminal_status == 200:
        result = await _call_transport(mode, respond, extra, candidates)
        assert "backup reply" in str(result)
    else:
        with pytest.raises(ValueError) as error:
            await _call_transport(mode, respond, extra, candidates)
        assert error.value.response.status_code == terminal_status
    assert archived == [terminal_status]
    if terminal_status in {401, 402, 403}:
        assert len(posted) == 1
    else:
        assert [row["provider"] for row in posted] == ["primary", "backup"]
        assert [row["allow_failover"] for row in posted] == [True, False]
        assert [row["client_request_id"] for row in posted] == [
            "synthetic-original",
            "synthetic-original-f1",
        ]
        assert posted[0]["route_token"] == "synthetic-pin"
        assert not {"route_token", "key_source", "config_revision"} & posted[1].keys()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync-stream", "async-stream"])
async def test_started_stream_cannot_replay_on_backup(monkeypatch, mode):
    monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER", "1")
    posted = []

    class Body(httpx.SyncByteStream, httpx.AsyncByteStream):
        def __iter__(self):
            yield b'data: {"delta":"first"}\n\n'
            raise httpx.ReadTimeout("synthetic timed out")

        async def __aiter__(self):
            for chunk in self:
                yield chunk

    def respond(request):
        posted.append(json.loads(request.content))
        return httpx.Response(200, stream=Body())

    with pytest.raises(httpx.ReadTimeout):
        await _call_transport(
            mode,
            respond,
            {"allow_failover": True},
            lambda *args: [("primary", "first"), ("backup", "second")],
        )
    assert len(posted) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout, httpx.WriteError, httpx.RemoteProtocolError, 500, 502, 503, 504]
)
async def test_unconfirmed_transport_or_proxy_result_never_selects_another_model(
    monkeypatch, mode, failure
):
    monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER", "1")
    posted = []

    def respond(request):
        posted.append(json.loads(request.content))
        if isinstance(failure, int):
            return httpx.Response(failure, json={"error": "timeout; outcome unavailable"})
        raise failure("request sent; no response", request=request)

    with pytest.raises((ValueError, httpx.HTTPError)):
        await _call_transport(
            mode,
            respond,
            {"allow_failover": True, "client_request_id": "same-request"},
            lambda *args: [("primary", "first"), ("backup", "second")],
        )
    assert len(posted) == 1
    assert posted[0]["model"] == "first"
    assert posted[0]["client_request_id"] == "same-request"
