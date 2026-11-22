"""Regression for native OpenAI SDK timeout normalization in spawned tools."""

import httpx
import httpx2
import pytest

from app.infrastructure.llm.providers.openai_sdk_provider import _bounded_sdk_timeout


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


def test_native_httpx2_sdk_timeout_keeps_native_type_and_phase_caps():
    configured = httpx2.Timeout(30, connect=1)
    result = _bounded_sdk_timeout(configured, 10)
    assert isinstance(result, httpx2.Timeout)
    assert result.as_dict() == {
        "connect": 1.0,
        "read": 10.0,
        "write": 10.0,
        "pool": 10.0,
    }


def test_native_httpx2_timeout_rejects_unknown_phase_instead_of_disabling_deadline():
    configured = httpx2.Timeout(30)
    configured.read = object()
    with pytest.raises(ValueError, match="invalid read timeout"):
        _bounded_sdk_timeout(configured, 10)
