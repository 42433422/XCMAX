"""Regression: LLM 调用不得在进程级复用 httpx.AsyncClient（多 asyncio.run / 线程会踩已关闭的 loop）。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx


def test_chat_openai_compatible_two_sequential_asyncio_runs() -> None:
    body = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
    req = httpx.Request("POST", "https://example/v1/chat/completions")
    mock_resp = httpx.Response(200, json=body, request=req)

    with patch.object(
        httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_resp
    ) as m_post:
        from modstore_server.llm_chat_proxy import chat_openai_compatible

        async def once():
            return await chat_openai_compatible(
                "https://example/v1", "k", "m", [{"role": "user", "content": "hi"}]
            )

        r1 = asyncio.run(once())
        r2 = asyncio.run(once())

    assert r1.get("ok") is True
    assert r2.get("ok") is True
    assert m_post.call_count == 2
