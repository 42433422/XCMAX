"""resolve_valid_market_access_token 的 TTL 缓存：短窗口内不重复打远端市场。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.fastapi_routes import market_account as ma


@pytest.fixture(autouse=True)
def _clear_cache():
    ma.invalidate_market_token_validation_cache()
    yield
    ma.invalidate_market_token_validation_cache()


@pytest.mark.asyncio
async def test_second_validation_within_ttl_skips_remote_call():
    proxy = AsyncMock(return_value={"id": 1, "username": "u"})
    with patch.object(ma, "session_market_token", return_value="tok-abc"), patch.object(
        ma, "_user_id_from_session", return_value=1
    ), patch.object(ma, "_proxy_json", proxy):
        first = await ma.resolve_valid_market_access_token("sid-cache")
        second = await ma.resolve_valid_market_access_token("sid-cache")
    assert first == "tok-abc"
    assert second == "tok-abc"
    assert proxy.await_count == 1


@pytest.mark.asyncio
async def test_cache_invalidated_when_token_changes():
    proxy = AsyncMock(return_value={"id": 1})
    tokens = iter(["tok-old", "tok-new", "tok-new"])
    with patch.object(ma, "session_market_token", side_effect=lambda _sid: next(tokens)), patch.object(
        ma, "_user_id_from_session", return_value=1
    ), patch.object(ma, "_proxy_json", proxy):
        assert await ma.resolve_valid_market_access_token("sid-x") == "tok-old"
        # 令牌换新（缓存里存的是 tok-old）→ 须重新校验
        assert await ma.resolve_valid_market_access_token("sid-x") == "tok-new"
    assert proxy.await_count == 2


@pytest.mark.asyncio
async def test_401_refresh_updates_cache():
    refreshed = AsyncMock(return_value="tok-refreshed")
    proxy = AsyncMock(return_value={"__proxy_error__": True, "status_code": 401})
    with patch.object(ma, "session_market_token", return_value="tok-stale"), patch.object(
        ma, "_user_id_from_session", return_value=1
    ), patch.object(ma, "_proxy_json", proxy), patch.object(
        ma, "refresh_session_market_token", refreshed
    ), patch.object(ma, "_proxy_error_http_status", return_value=401):
        out = await ma.resolve_valid_market_access_token("sid-r")
    assert out == "tok-refreshed"


@pytest.mark.asyncio
async def test_invalidate_specific_session():
    ma._remember_validated_market_token("sid-1", "tok-1")
    ma._remember_validated_market_token("sid-2", "tok-2")
    ma.invalidate_market_token_validation_cache("sid-1")
    assert ma._cached_validated_market_token("sid-1") is None
    assert ma._cached_validated_market_token("sid-2") == "tok-2"
