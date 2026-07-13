"""Request adapters release async clients on the creating event loop."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.conversation.modstore_adapter import ModstorePlatformAdapter


def test_unknown_session_cannot_fall_back_to_another_users_latest_token() -> None:
    market_account = SimpleNamespace(
        session_id_from_request=MagicMock(return_value="unknown-session"),
        session_market_token=MagicMock(return_value=""),
        _user_id_from_session=MagicMock(return_value=None),
        latest_session_market_token=MagicMock(return_value="another-users-token"),
    )

    with (
        patch.dict(
            os.environ,
            {
                "MODSTORE_AUTH_TOKEN": "",
                "XCAGI_MARKET_BASE_URL": "https://market.example.test",
            },
            clear=False,
        ),
        patch.dict(
            "sys.modules",
            {"app.fastapi_routes.market_account": market_account},
        ),
    ):
        adapter = ModstorePlatformAdapter.from_session(session_id="unknown-session")

    assert adapter.auth_token == ""
    market_account.latest_session_market_token.assert_not_called()


def test_known_session_fallback_is_filtered_by_its_user_id() -> None:
    market_account = SimpleNamespace(
        session_id_from_request=MagicMock(return_value="known-session"),
        session_market_token=MagicMock(return_value=""),
        _user_id_from_session=MagicMock(return_value=42),
        latest_session_market_token=MagicMock(return_value="same-users-latest-token"),
    )

    with (
        patch.dict(
            os.environ,
            {
                "MODSTORE_AUTH_TOKEN": "",
                "XCAGI_MARKET_BASE_URL": "https://market.example.test",
            },
            clear=False,
        ),
        patch.dict(
            "sys.modules",
            {"app.fastapi_routes.market_account": market_account},
        ),
    ):
        adapter = ModstorePlatformAdapter.from_session(session_id="known-session")

    assert adapter.auth_token == "same-users-latest-token"
    market_account.latest_session_market_token.assert_called_once_with(user_id=42)


@pytest.mark.asyncio
async def test_request_adapter_closes_client_after_chat_completion() -> None:
    adapter = ModstorePlatformAdapter(
        platform_url="https://market.example.test",
        auth_token="request-token",
        close_after_call=True,
    )
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "success": True,
        "content": "真实回答",
        "usage": {"total_tokens": 8},
    }
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    adapter._get_client = AsyncMock(return_value=client)
    adapter.close = AsyncMock()

    result = await adapter.chat_completion(messages=[{"role": "user", "content": "你好"}])

    assert result["choices"][0]["message"]["content"] == "真实回答"
    adapter.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_adapter_closes_client_when_stream_finishes() -> None:
    adapter = ModstorePlatformAdapter(
        platform_url="https://market.example.test",
        auth_token="request-token",
        close_after_call=True,
    )

    class _Response:
        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"你好"}}]}'
            yield "data: [DONE]"

    class _StreamContext:
        async def __aenter__(self):
            return _Response()

        async def __aexit__(self, *_args):
            return None

    client = MagicMock()
    client.stream.return_value = _StreamContext()
    adapter._get_client = AsyncMock(return_value=client)
    adapter.close = AsyncMock()

    chunks = [
        chunk
        async for chunk in adapter.stream_chat_completion(
            messages=[{"role": "user", "content": "你好"}]
        )
    ]

    assert chunks == ['{"choices":[{"delta":{"content":"你好"}}]}', "[DONE]"]
    adapter.close.assert_awaited_once()
