"""The sandbox SDK must not turn its host into an unrestricted HTTP proxy."""

from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace

import httpx
import pytest

from modstore_server import openapi_connector_runtime as outbound
from modstore_server.script_agent.sandbox_host import SandboxHostContext, SandboxRpcServer


@pytest.fixture
def http_boundary(monkeypatch):
    state = SimpleNamespace(requests=[], options=[], status=200, stream=None)
    client_type = httpx.AsyncClient

    def respond(request):
        state.requests.append(request)
        return httpx.Response(
            state.status,
            headers={"Location": "http://127.0.0.1/private", "Content-Type": "text/plain"},
            stream=state.stream,
            content=None if state.stream is not None else b"public fixture",
        )

    def client(**options):
        state.options.append(options)
        return client_type(transport=httpx.MockTransport(respond), **options)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(
        outbound.socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    state.server = SandboxRpcServer(SandboxHostContext(user_id=101))
    return state


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://10.0.0.1/private",
        "http://169.254.169.254/metadata",
        "http://[::1]/private",
        "http://[fc00::1]/private",
        "http://[fec0::1]/private",
        "http://localhost/private",
        "https://user:password@public.example/data",
    ],
)
def test_sdk_rejects_private_destinations_before_request(http_boundary, url):
    with pytest.raises(RuntimeError):
        asyncio.run(http_boundary.server._handle_http_get({"url": url}))
    assert not http_boundary.requests


def test_sdk_rejects_private_dns_answers(http_boundary, monkeypatch):
    monkeypatch.setattr(
        outbound.socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 80))],
    )
    with pytest.raises(RuntimeError):
        asyncio.run(http_boundary.server._handle_http_get({"url": "http://private.example/"}))
    assert not http_boundary.requests


def test_sdk_pins_dns_and_preserves_origin_without_header_override(http_boundary):
    result = asyncio.run(
        http_boundary.server._handle_http_get(
            {
                "url": "https://public.example:8443/data",
                "params": {"q": "fixture"},
                "headers": {"host": "localhost", "Host": "internal", "Accept": "text/plain"},
            }
        )
    )
    assert result["text"] == "public fixture"
    request = http_boundary.requests[0]
    assert str(request.url) == "https://93.184.216.34:8443/data?q=fixture"
    assert request.headers.get_list("host") == ["public.example:8443"]
    assert request.headers["accept"] == "text/plain"
    assert request.extensions["sni_hostname"] == "public.example"
    assert http_boundary.options[0]["trust_env"] is False
    assert http_boundary.options[0]["follow_redirects"] is False


def test_sdk_does_not_follow_private_redirect(http_boundary):
    http_boundary.status = 302
    result = asyncio.run(
        http_boundary.server._handle_http_get({"url": "https://public.example/redirect"})
    )
    assert result["status"] == 302
    assert len(http_boundary.requests) == 1
    assert http_boundary.requests[0].url.host == "93.184.216.34"


def test_sdk_stops_reading_oversized_response(http_boundary):
    class OversizedBody(httpx.AsyncByteStream):
        chunks_read = 0
        closed = False

        async def __aiter__(self):
            for _ in range(3):
                self.chunks_read += 1
                yield b"x" * 600_000

        async def aclose(self):
            self.closed = True

    http_boundary.stream = OversizedBody()
    with pytest.raises(RuntimeError, match="响应过大"):
        asyncio.run(http_boundary.server._handle_http_get({"url": "https://public.example/"}))
    assert http_boundary.stream.chunks_read == 2
    assert http_boundary.stream.closed
