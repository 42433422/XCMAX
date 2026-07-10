"""Conditional gzip decision matrix and stream pass-through tests."""

from __future__ import annotations

import gzip

import pytest

from app.middleware.conditional_gzip import ConditionalGZipMiddleware

_JSON_HEADERS = [(b"content-type", b"application/json")]


def _inner_app(headers, chunks):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": list(headers)})
        for index, chunk in enumerate(chunks):
            await send(
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": index < len(chunks) - 1,
                }
            )

    return app


async def _run(middleware, accept_encoding=b"gzip"):
    captured: list[dict] = []

    async def send(message):
        captured.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/anything",
        "query_string": b"",
        "headers": [(b"accept-encoding", accept_encoding)] if accept_encoding else [],
    }
    await middleware(scope, lambda: None, send)
    return captured


def _headers(captured) -> dict[bytes, bytes]:
    return dict(captured[0]["headers"])


@pytest.mark.asyncio
async def test_large_json_single_body_is_compressed():
    body = b'{"data":"' + b"x" * 4096 + b'"}'
    captured = await _run(ConditionalGZipMiddleware(_inner_app(_JSON_HEADERS, [body])))

    headers = _headers(captured)
    assert headers[b"content-encoding"] == b"gzip"
    assert b"accept-encoding" in headers[b"vary"].lower()
    assert gzip.decompress(captured[1]["body"]) == body
    assert int(headers[b"content-length"]) == len(captured[1]["body"])


@pytest.mark.asyncio
async def test_small_json_is_not_compressed():
    body = b'{"ok":true}'
    captured = await _run(ConditionalGZipMiddleware(_inner_app(_JSON_HEADERS, [body])))
    assert b"content-encoding" not in _headers(captured)
    assert captured[1]["body"] == body


@pytest.mark.asyncio
async def test_sse_is_never_compressed():
    body = b"data: " + b"x" * 8192 + b"\n\n"
    headers = [(b"content-type", b"text/event-stream; charset=utf-8")]
    captured = await _run(ConditionalGZipMiddleware(_inner_app(headers, [body])))
    assert b"content-encoding" not in _headers(captured)
    assert captured[1]["body"] == body


@pytest.mark.asyncio
async def test_streaming_body_is_passed_through_unbuffered():
    chunks = [b"data: hello\n\n", b"data: world\n\n", b"data: done\n\n"]
    captured = await _run(ConditionalGZipMiddleware(_inner_app(_JSON_HEADERS, chunks)))
    assert b"content-encoding" not in _headers(captured)
    assert [message["body"] for message in captured[1:]] == chunks


@pytest.mark.asyncio
async def test_identity_and_similar_tokens_do_not_enable_gzip():
    body = b"x" * 4096
    middleware = ConditionalGZipMiddleware(_inner_app(_JSON_HEADERS, [body]))
    for encoding in (b"identity", b"x-gzip-compatible"):
        captured = await _run(middleware, accept_encoding=encoding)
        assert b"content-encoding" not in _headers(captured)
        assert captured[1]["body"] == body


@pytest.mark.asyncio
async def test_binary_and_already_encoded_responses_are_untouched():
    binary = b"\x00" * 4096
    captured = await _run(
        ConditionalGZipMiddleware(
            _inner_app([(b"content-type", b"application/octet-stream")], [binary])
        )
    )
    assert b"content-encoding" not in _headers(captured)

    encoded = gzip.compress(b"y" * 4096)
    captured = await _run(
        ConditionalGZipMiddleware(
            _inner_app(
                [(b"content-type", b"application/json"), (b"content-encoding", b"br")],
                [encoded],
            )
        )
    )
    assert _headers(captured)[b"content-encoding"] == b"br"
    assert captured[1]["body"] == encoded


@pytest.mark.asyncio
async def test_existing_vary_header_is_extended():
    body = b'{"data":"' + b"z" * 4096 + b'"}'
    captured = await _run(
        ConditionalGZipMiddleware(_inner_app(_JSON_HEADERS + [(b"vary", b"Origin")], [body]))
    )
    vary = _headers(captured)[b"vary"].lower()
    assert b"origin" in vary
    assert b"accept-encoding" in vary


@pytest.mark.asyncio
async def test_websocket_scope_is_passed_through():
    called = {}

    async def inner(scope, receive, send):
        called["ok"] = True

    middleware = ConditionalGZipMiddleware(inner)
    await middleware({"type": "websocket"}, lambda: None, lambda message: None)
    assert called["ok"] is True
