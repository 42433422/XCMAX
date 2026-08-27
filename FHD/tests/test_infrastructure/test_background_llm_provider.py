from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.llm.providers.modstore_provider import ModstoreProvider
from app.infrastructure.llm.providers.registry import _resolve_background_market_provider


def test_desktop_background_provider_resumes_persisted_session(monkeypatch) -> None:
    adapter = SimpleNamespace(
        auth_token="persisted-token",
        platform_url="https://xiu-ci.com",
        is_configured=True,
    )
    latest = lambda user_id=None: "desktop-session"  # noqa: E731

    monkeypatch.delenv("XCAGI_BACKGROUND_LLM_USER_ID", raising=False)
    monkeypatch.setattr("app.utils.deployment.is_desktop_mode", lambda: True)
    monkeypatch.setattr(
        "app.fastapi_routes.market_account.latest_session_id_with_market_token",
        latest,
    )
    from_session = MagicMock(return_value=adapter)
    monkeypatch.setattr(
        "app.services.conversation.modstore_adapter.ModstorePlatformAdapter.from_session",
        from_session,
    )

    provider = _resolve_background_market_provider()

    assert provider is not None
    assert provider.provider_id == "modstore"
    assert provider.credential_scope == "desktop_session"
    assert provider._session_id == "desktop-session"


def test_server_background_provider_does_not_select_an_arbitrary_user(monkeypatch) -> None:
    called = False

    def latest(user_id=None):
        nonlocal called
        called = True
        return "must-not-be-used"

    monkeypatch.delenv("XCAGI_BACKGROUND_LLM_USER_ID", raising=False)
    monkeypatch.setattr("app.utils.deployment.is_desktop_mode", lambda: False)
    monkeypatch.setattr(
        "app.fastapi_routes.market_account.latest_session_id_with_market_token",
        latest,
    )

    assert _resolve_background_market_provider() is None
    assert called is False


@pytest.mark.asyncio
async def test_background_modstore_provider_refreshes_once_after_401(monkeypatch) -> None:
    adapter = SimpleNamespace(
        auth_token="expired-token",
        _client=None,
        chat_completion=AsyncMock(
            side_effect=[
                ValueError("平台错误(401): expired"),
                {"choices": [{"message": {"content": "ok"}}]},
            ]
        ),
    )
    refresh = AsyncMock(return_value="fresh-token")
    monkeypatch.setattr(
        "app.fastapi_routes.market_account.resolve_valid_market_access_token",
        refresh,
    )
    provider = ModstoreProvider(adapter, session_id="session-a")

    result = await provider.chat_completion([{"role": "user", "content": "ping"}])

    assert result == {"choices": [{"message": {"content": "ok"}}]}
    assert adapter.auth_token == "fresh-token"
    assert adapter.chat_completion.await_count == 2
    refresh.assert_awaited_once_with("session-a")
