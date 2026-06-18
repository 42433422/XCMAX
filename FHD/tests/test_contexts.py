"""Contexts 模块测试：flags、manifest、context_notifier。"""

from __future__ import annotations

import os

import pytest

from app.contexts.context_notifier import ContextNotifier, get_context_notifier
from app.contexts.flags import _truthy, is_any_event_primary_enabled, is_event_primary_enabled
from app.contexts.manifest import BOUNDED_CONTEXTS, BoundedContextMeta, contexts_by_id

# ══════════════════════════════════════════════════════════════════════════════
# Flags
# ══════════════════════════════════════════════════════════════════════════════


class TestTruthy:
    def test_truthy_values(self):
        for val in ("1", "true", "True", "TRUE", "yes", "on"):
            assert _truthy(val) is True

    def test_falsy_values(self):
        for val in ("0", "false", "no", "off", "", "random"):
            assert _truthy(val) is False


class TestIsAnyEventPrimaryEnabled:
    def test_not_set(self, monkeypatch):
        monkeypatch.delenv("XCAGI_EVENT_PRIMARY", raising=False)
        assert is_any_event_primary_enabled() is False

    def test_enabled(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EVENT_PRIMARY", "1")
        assert is_any_event_primary_enabled() is True

    def test_disabled(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EVENT_PRIMARY", "0")
        assert is_any_event_primary_enabled() is False


class TestIsEventPrimaryEnabled:
    def test_global_enabled(self, monkeypatch):
        monkeypatch.setenv("XCAGI_EVENT_PRIMARY", "1")
        assert is_event_primary_enabled("shipment") is True

    def test_specific_enabled(self, monkeypatch):
        monkeypatch.delenv("XCAGI_EVENT_PRIMARY", raising=False)
        monkeypatch.setenv("XCAGI_EVENT_PRIMARY_SHIPMENT", "1")
        assert is_event_primary_enabled("shipment") is True

    def test_specific_not_set(self, monkeypatch):
        monkeypatch.delenv("XCAGI_EVENT_PRIMARY", raising=False)
        monkeypatch.delenv("XCAGI_EVENT_PRIMARY_ORDER", raising=False)
        assert is_event_primary_enabled("order") is False

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.delenv("XCAGI_EVENT_PRIMARY", raising=False)
        monkeypatch.setenv("XCAGI_EVENT_PRIMARY_INVENTORY", "true")
        assert is_event_primary_enabled("inventory") is True


# ══════════════════════════════════════════════════════════════════════════════
# Manifest
# ══════════════════════════════════════════════════════════════════════════════


class TestBoundedContextMeta:
    def test_fields(self):
        meta = BoundedContextMeta(
            context_id="test",
            event_prefixes=("test.",),
            aggregate_paths=("app.domain.test",),
            handler_module="app.test_handler",
        )
        assert meta.context_id == "test"
        assert meta.event_prefixes == ("test.",)
        assert meta.aggregate_paths == ("app.domain.test",)
        assert meta.handler_module == "app.test_handler"

    def test_frozen(self):
        meta = BoundedContextMeta(
            context_id="test",
            event_prefixes=("test.",),
            aggregate_paths=("app.domain.test",),
            handler_module="app.test_handler",
        )
        with pytest.raises(AttributeError):
            meta.context_id = "changed"


class TestBoundedContexts:
    def test_not_empty(self):
        assert len(BOUNDED_CONTEXTS) > 0

    def test_known_contexts(self):
        ids = {m.context_id for m in BOUNDED_CONTEXTS}
        assert "shipment" in ids
        assert "order" in ids
        assert "inventory" in ids
        assert "product" in ids
        assert "customer" in ids
        assert "intent" in ids

    def test_each_has_handler_module(self):
        for ctx in BOUNDED_CONTEXTS:
            assert ctx.handler_module, f"{ctx.context_id} missing handler_module"

    def test_each_has_event_prefixes(self):
        for ctx in BOUNDED_CONTEXTS:
            assert ctx.event_prefixes, f"{ctx.context_id} missing event_prefixes"


class TestContextsById:
    def test_returns_dict(self):
        result = contexts_by_id()
        assert isinstance(result, dict)
        assert "shipment" in result
        assert isinstance(result["shipment"], BoundedContextMeta)


# ══════════════════════════════════════════════════════════════════════════════
# ContextNotifier
# ══════════════════════════════════════════════════════════════════════════════


class TestGetContextNotifier:
    def test_returns_none(self):
        result = get_context_notifier()
        assert result is None
