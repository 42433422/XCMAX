"""app/middleware/conditional_gzip 单测：压缩决策矩阵与 SSE 透传。"""

from __future__ import annotations

import gzip

import pytest

from app.middleware.conditional_gzip import ConditionalGZipMiddleware

_JSON_HEADERS = [(b"content-type", b"application/json")]


def _inner_app(headers, chunks):
    """构造发送 start + N 个 body 消息的最小 ASGI app。"""

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": list(headers)})
        for i, chunk in enumerate(chunks):
            await send(
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": i < len(chunks) - 1,
                }
            )

    return app


async def _run(mw, accept_encoding=b"gzip"):
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
    await mw(scope, lambda: None, send)
    return captured


def _headers(captured) -> dict[bytes, bytes]:
    return dict(captured[0]["headers"])


@pytest.mark.asyncio
async def test_large_json_single_body_is_compressed():
    body = (b'{"data":"' + b"x" * 4096 + b'"}')
    mw = ConditionalGZipMiddleware(_inner_app(_JSON_HEADERS, [body]))
    captured = await _run(mw)

    hdrs = _headers(captured)
    assert hdrs[b"content-encoding"] == b"gzip"
    assert b"accept-encoding" in hdrs[b"vary"].lower()
    compressed = captured[1]["body"]
    assert len(compressed) < len(body)
    assert gzip.decompress(compressed) == body
    assert int(hdrs[b"content-length"]) == len(compressed)


@pytest.mark.asyncio
async def test_small_json_not_compressed():
    body = b'{"ok":true}'
    mw = ConditionalGZipMiddleware(_inner_app(_JSON_HEADERS, [body]))
    captured = await _run(mw)

    hdrs = _headers(captured)
    assert b"content-encoding" not in hdrs
    assert captured[1]["body"] == body


@pytest.mark.asyncio
async def test_sse_content_type_never_compressed():
    body = b"data: " + b"x" * 8192 + b"\n\n"
    headers = [(b"content-type", b"text/event-stream; charset=utf-8")]
    mw = ConditionalGZipMiddleware(_inner_app(headers, [body]))
    captured = await _run(mw)

    hdrs = _headers(captured)
    assert b"content-encoding" not in hdrs
    assert captured[1]["body"] == body


@pytest.mark.asyncio
async def test_streaming_multi_chunk_passthrough_unbuffered():
    """流式响应（more_body=True）必须逐块原样透传，不得缓冲/压缩。"""
    chunks = [b"data: hello\n\n", b"data: world\n\n", b"data: done\n\n"]
    mw = ConditionalGZipMiddleware(_inner_app(_JSON_HEADERS, chunks))
    captured = await _run(mw)

    assert captured[0]["type"] == "http.response.start"
    assert b"content-encoding" not in _headers(captured)
    bodies = [m["body"] for m in captured[1:]]
    assert bodies == chunks


@pytest.mark.asyncio
async def test_no_gzip_in_accept_encoding_passthrough():
    body = b"x" * 4096
    mw = ConditionalGZipMiddleware(_inner_app(_JSON_HEADERS, [body]))
    captured = await _run(mw, accept_encoding=b"identity")

    assert b"content-encoding" not in _headers(captured)
    assert captured[1]["body"] == body


@pytest.mark.asyncio
async def test_binary_content_type_not_compressed():
    body = b"\x00" * 4096
    headers = [(b"content-type", b"application/octet-stream")]
    mw = ConditionalGZipMiddleware(_inner_app(headers, [body]))
    captured = await _run(mw)

    assert b"content-encoding" not in _headers(captured)
    assert captured[1]["body"] == body


@pytest.mark.asyncio
async def test_already_encoded_response_untouched():
    payload = gzip.compress(b"y" * 4096)
    headers = [(b"content-type", b"application/json"), (b"content-encoding", b"br")]
    mw = ConditionalGZipMiddleware(_inner_app(headers, [payload]))
    captured = await _run(mw)

    hdrs = _headers(captured)
    assert hdrs[b"content-encoding"] == b"br"
    assert captured[1]["body"] == payload


@pytest.mark.asyncio
async def test_existing_vary_header_extended():
    body = b'{"data":"' + b"z" * 4096 + b'"}'
    headers = _JSON_HEADERS + [(b"vary", b"Origin")]
    mw = ConditionalGZipMiddleware(_inner_app(headers, [body]))
    captured = await _run(mw)

    vary = _headers(captured)[b"vary"].lower()
    assert b"origin" in vary
    assert b"accept-encoding" in vary


@pytest.mark.asyncio
async def test_websocket_scope_passthrough():
    called = {}

    async def inner(scope, receive, send):
        called["ok"] = True

    mw = ConditionalGZipMiddleware(inner)
    await mw({"type": "websocket"}, lambda: None, lambda m: None)
    assert called["ok"] is True
