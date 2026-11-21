"""Regression for native OpenAI SDK timeout normalization in spawned tools."""

import asyncio
import time

import httpx
import pytest
from openai import NOT_GIVEN, RateLimitError

from app.application.tool_execution_deadline import invocation_deadline
from app.infrastructure.llm.providers.openai_sdk_provider import (
    _bounded_sdk_timeout,
    _sdk_responses,
)
from tests.test_application.test_planner_context_continuity import (
    native_sdk_planner as native_sdk_planner,
)


def test_nested_sdk_timeout_remains_bounded_and_preserves_stricter_phase_limit():
    configured = httpx.Timeout(30, connect=1)
    configured.read = httpx.Timeout(5)
    result = _bounded_sdk_timeout(configured, 10)
    assert result.as_dict() == {"connect": 1.0, "read": 5.0, "write": 10.0, "pool": 10.0}


def test_no_phase_can_bypass_inherited_deadline():
    result = _bounded_sdk_timeout(httpx.Timeout(None), 2)
    assert all(value == 2 for value in result.as_dict().values())


def test_unsupported_sdk_timeout_fails_closed():
    configured = httpx.Timeout(30)
    configured.read = object()
    with pytest.raises(ValueError, match="invalid read timeout"):
        _bounded_sdk_timeout(configured, 10)


def test_native_provider_normalizes_nested_timeout_before_dispatch(native_sdk_planner, monkeypatch):
    state = native_sdk_planner
    configured = httpx.Timeout(30, connect=1, pool=None)
    nested_read = httpx.Timeout(5)
    configured.read = nested_read
    state.client.timeout = configured
    monkeypatch.setattr("app.infrastructure.llm.client._resolve_openai_timeout_seconds", lambda: 7)

    with invocation_deadline(time.monotonic() + 10):
        response = asyncio.run(state.provider.chat_completion([], model="fixture"))
    assert response["choices"][0]["message"]["content"] == "{}"
    assert len(state.posts) == 1
    assert state.posts[0].extensions["timeout"] == {
        "connect": 1.0,
        "read": 5.0,
        "write": 7.0,
        "pool": 7.0,
    }
    assert state.client.timeout is configured
    assert configured.read is nested_read
    assert state.client.max_retries == 2
    assert not state.client.is_closed()


def test_native_stream_entry_normalizes_notgiven_without_sdk_retry(native_sdk_planner):
    state = native_sdk_planner
    configured = httpx.Timeout(30, connect=1, pool=None)
    nested_read = httpx.Timeout(5)
    configured.read = nested_read
    state.client.timeout = configured
    state.statuses = [429, 200]

    async def request():
        source = _sdk_responses(
            state.client,
            {"model": "fixture", "messages": [], "stream": True, "timeout": NOT_GIVEN},
            stream=True,
        )
        try:
            return await anext(source)
        finally:
            await source.aclose()

    with invocation_deadline(time.monotonic() + 10), pytest.raises(RateLimitError):
        asyncio.run(request())
    assert len(state.posts) == 1
    timeouts = state.posts[0].extensions["timeout"]
    assert timeouts["connect"] == 1
    assert timeouts["read"] == 5
    assert all(0 < value <= 10 for value in timeouts.values())
    assert state.client.timeout is configured
    assert configured.read is nested_read
    assert state.client.max_retries == 2
    assert not state.client.is_closed()
