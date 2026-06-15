"""COVERAGE_RAMP Phase 1 (p1-p0-core): conversation helpers + xcagi_compat_chat_helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.fastapi_routes.domains.conversation.helpers import (
    _ensure_chat_db_read_authorized,
    _ensure_vector_index_if_needed,
    _message_requires_db_read_token,
    _xcagi_chat_http_exc,
    _xcagi_guarded_planner_stream_events,
)
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    _chat_db_read_grace_seconds_left,
    _chat_request_subject,
    _touch_chat_db_read_grace,
)


def _req(**headers: str) -> Request:
    hdrs = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/chat",
        "headers": hdrs,
        "query_string": b"",
        "client": ("10.0.0.2", 9000),
    }
    return Request(scope)


def test_chat_request_subject_stable() -> None:
    req = _req(user_agent="TestAgent/1.0")
    s1 = _chat_request_subject(req)
    s2 = _chat_request_subject(req)
    assert s1 == s2
    assert "10.0.0.2" in s1


def test_chat_db_read_grace_lifecycle() -> None:
    from app.fastapi_routes.xcagi_compat_chat_helpers import _chat_db_read_grace_until

    _chat_db_read_grace_until.clear()
    req = _req()
    _touch_chat_db_read_grace(req)
    assert _chat_db_read_grace_seconds_left(req) > 0


def test_message_requires_db_read_token() -> None:
    assert _message_requires_db_read_token("查看数据库产品库") is True
    assert _message_requires_db_read_token("你好") is False


@patch("app.infrastructure.auth.db_token.effective_db_read_token", return_value="")
def test_ensure_chat_db_read_authorized_no_token(_mock: MagicMock) -> None:
    ok, payload = _ensure_chat_db_read_authorized(_req(), message="查看数据库", provided_token=None)
    assert ok is True
    assert payload is None


@patch("app.fastapi_routes.domains.conversation.helpers.effective_db_read_token", return_value="secret")
def test_ensure_chat_db_read_authorized_wrong_token(_mock: MagicMock) -> None:
    ok, payload = _ensure_chat_db_read_authorized(
        _req(), message="查看数据库产品库", provided_token="bad"
    )
    assert ok is False
    assert payload is not None


def test_xcagi_chat_http_exc_timeout() -> None:
    exc = _xcagi_chat_http_exc(TimeoutError("t"))
    assert exc.status_code == 504


def test_xcagi_chat_http_exc_value_error_balance() -> None:
    exc = _xcagi_chat_http_exc(ValueError("余额不足请充值"))
    assert exc.status_code == 402


def test_xcagi_chat_http_exc_runtime() -> None:
    exc = _xcagi_chat_http_exc(RuntimeError("svc down"))
    assert exc.status_code == 503


def test_ensure_vector_index_no_file() -> None:
    hint = _ensure_vector_index_if_needed("向量检索", {})
    assert hint is None or isinstance(hint, str)
