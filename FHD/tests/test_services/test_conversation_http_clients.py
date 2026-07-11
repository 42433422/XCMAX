"""Regression tests for conversation clients and malformed Windows proxy env."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from app.services.conversation.api import ApiMixin
from app.services.conversation.llm_adapter import OpenAICompatibleAdapter
from app.services.conversation.modstore_adapter import ModstorePlatformAdapter


@pytest.fixture
def invalid_windows_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model httpx 0.26 failing on Windows when NO_PROXY contains bare IPv6."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1")

    def fail_if_environment_proxies_are_read() -> dict[str, str]:
        raise httpx.InvalidURL("Invalid port: ':'")

    monkeypatch.setattr(
        "httpx._client.get_environment_proxies",
        fail_if_environment_proxies_are_read,
    )


@pytest.mark.asyncio
async def test_direct_llm_async_clients_ignore_invalid_proxy_environment(
    invalid_windows_proxy_environment: None,
) -> None:
    adapter = OpenAICompatibleAdapter(provider="deepseek", api_key="test-key")

    normal_client = await adapter._get_client()
    stream_client = await adapter._get_stream_client()

    assert isinstance(normal_client, httpx.AsyncClient)
    assert isinstance(stream_client, httpx.AsyncClient)
    await adapter.close()


@pytest.mark.asyncio
async def test_modstore_async_client_ignores_invalid_proxy_environment(
    invalid_windows_proxy_environment: None,
) -> None:
    adapter = ModstorePlatformAdapter(platform_url="http://localhost:8000")

    client = await adapter._get_client()

    assert isinstance(client, httpx.AsyncClient)
    await adapter.close()


@pytest.mark.asyncio
async def test_legacy_llm_async_client_ignores_invalid_proxy_environment(
    invalid_windows_proxy_environment: None,
) -> None:
    service = ApiMixin()
    service._deepseek_async_client = None
    service._deepseek_async_loop = None

    client = await service._get_deepseek_async_client()

    assert isinstance(client, httpx.AsyncClient)
    await client.aclose()


def test_modstore_sync_client_ignores_invalid_proxy_environment(
    invalid_windows_proxy_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = ModstorePlatformAdapter(platform_url="http://localhost:8000")
    response = MagicMock(
        status_code=200,
        **{
            "json.return_value": {
                "content": "ok",
                "success": True,
                "usage": {},
            }
        },
    )
    monkeypatch.setattr(httpx.Client, "post", lambda *_args, **_kwargs: response)

    result = adapter.chat_completion_sync([{"role": "user", "content": "hello"}])

    assert result["choices"][0]["message"]["content"] == "ok"


class _StreamResponse:
    status_code = 200

    def __enter__(self) -> _StreamResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def iter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
        yield "data: [DONE]"


def test_modstore_sync_stream_client_ignores_invalid_proxy_environment(
    invalid_windows_proxy_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = ModstorePlatformAdapter(platform_url="http://localhost:8000")
    monkeypatch.setattr(
        httpx.Client,
        "stream",
        lambda *_args, **_kwargs: _StreamResponse(),
    )

    chunks = list(
        adapter.stream_chat_completion_sync([{"role": "user", "content": "hello"}])
    )

    assert chunks == ['{"choices":[{"delta":{"content":"ok"}}]}']
