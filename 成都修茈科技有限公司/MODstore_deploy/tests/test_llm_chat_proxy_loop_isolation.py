"""Regression: LLM 调用不得在进程级复用 httpx.AsyncClient（多 asyncio.run / 线程会踩已关闭的 loop）。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest


@pytest.mark.parametrize(
    "provider,body,finish_reason",
    [
        (
            "openai",
            {"choices": [{"message": {"content": "ok"}, "finish_reason": "length"}]},
            "length",
        ),
        (
            "anthropic",
            {"content": [{"type": "text", "text": "ok"}], "stop_reason": "max_tokens"},
            "max_tokens",
        ),
        (
            "google",
            {
                "candidates": [
                    {"content": {"parts": [{"text": "ok"}]}, "finishReason": "MAX_TOKENS"}
                ]
            },
            "MAX_TOKENS",
        ),
    ],
)
def test_chat_provider_completion_survives_two_sequential_asyncio_runs(
    provider, body, finish_reason
) -> None:
    req = httpx.Request("POST", "https://example/v1/chat/completions")
    mock_resp = httpx.Response(200, json=body, request=req)

    with patch.object(
        httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_resp
    ) as m_post:
        from modstore_server import llm_chat_proxy as proxy

        async def once():
            messages = [{"role": "user", "content": "hi"}]
            if provider == "openai":
                return await proxy.chat_openai_compatible(
                    "https://example/v1", "synthetic-secret", "m", messages
                )
            return await getattr(proxy, f"chat_{provider}")("synthetic-secret", "m", messages)

        r1 = asyncio.run(once())
        r2 = asyncio.run(once())

    assert r1.get("ok") is True
    assert r2.get("ok") is True
    assert r1["finish_reason"] == r2["finish_reason"] == finish_reason
    assert m_post.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["stop", "length", None])
async def test_completion_stream_keeps_original_finish_reason(finish_reason):
    from modstore_server.llm_chat_proxy import _events_from_completion

    events = [
        event
        async for event in _events_from_completion(
            {"ok": True, "content": "answer", "finish_reason": finish_reason}
        )
    ]
    assert events[-1] == {"type": "finish", "finish_reason": finish_reason}
