"""app/contexts/context_notifier 单测。"""

from __future__ import annotations

from app.contexts.context_notifier import get_context_notifier


def test_get_context_notifier_returns_none():
    assert get_context_notifier() is None
