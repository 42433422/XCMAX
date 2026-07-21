"""app/contexts/flags — 变异测试友好分支覆盖。"""

from __future__ import annotations

import app.contexts.flags as flags


def test_truthy_accepts_common_true_tokens():
    assert flags._truthy("1") is True
    assert flags._truthy("true") is True
    assert flags._truthy("YES") is True
    assert flags._truthy(" On ") is True


def test_truthy_rejects_false_and_garbage():
    assert flags._truthy("0") is False
    assert flags._truthy("false") is False
    assert flags._truthy("") is False
    assert flags._truthy("maybe") is False


def test_any_event_primary_unset(monkeypatch):
    monkeypatch.delenv("XCAGI_EVENT_PRIMARY", raising=False)
    assert flags.is_any_event_primary_enabled() is False


def test_any_event_primary_enabled(monkeypatch):
    monkeypatch.setenv("XCAGI_EVENT_PRIMARY", "1")
    assert flags.is_any_event_primary_enabled() is True
    assert flags.is_event_primary_enabled("shipment") is True


def test_context_specific_flag(monkeypatch):
    monkeypatch.delenv("XCAGI_EVENT_PRIMARY", raising=False)
    monkeypatch.setenv("XCAGI_EVENT_PRIMARY_SHIPMENT", "true")
    assert flags.is_event_primary_enabled("shipment") is True
    assert flags.is_event_primary_enabled("billing") is False


def test_context_flag_whitespace_and_case(monkeypatch):
    monkeypatch.delenv("XCAGI_EVENT_PRIMARY", raising=False)
    monkeypatch.setenv("XCAGI_EVENT_PRIMARY_ORDER", " YES ")
    assert flags.is_event_primary_enabled(" order ") is True
