"""Malformed local fault specifications never break a history response."""

from __future__ import annotations

import inspect
from unittest.mock import Mock

import pytest

from app.application.ai_chat.conversation_history import apply_history_fault


@pytest.mark.parametrize(
    "value,delay",
    [
        ("2.5", 2.5),
        ("100", 30),
        ("-1", None),
        ("0", None),
        ("nan", None),
        ("inf", None),
        ("bad", None),
        ("", None),
    ],
)
def test_delay_fault_is_finite_nonnegative_and_bounded(tmp_path, monkeypatch, value, delay):
    spec = tmp_path / "fault.txt"
    spec.write_text(f"delay:{value}")
    monkeypatch.setenv("XCAGI_HISTORY_FAULT_FILE", str(spec))
    sleep = Mock()
    monkeypatch.setattr("time.sleep", sleep)
    payload = {"success": True, "messages": [{"content": "原文"}]}
    assert apply_history_fault(payload) is payload
    if delay is None:
        sleep.assert_not_called()
    else:
        sleep.assert_called_once_with(delay)


def test_history_fault_callers_use_sync_route_workers():
    from app.fastapi_routes.domains.conversation import conversation_routes
    from app.legacy.routes.conversation import compat_extra

    for route in (
        conversation_routes.conversations_get,
        compat_extra.conversations_get,
        compat_extra.conversations_sessions_list,
    ):
        assert not inspect.iscoroutinefunction(route)
