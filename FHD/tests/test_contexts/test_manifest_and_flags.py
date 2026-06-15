"""app/contexts/manifest 与 flags 纯函数单测（Phase 4 长尾）。"""

from __future__ import annotations

import os

import pytest

from app.contexts.flags import is_any_event_primary_enabled, is_event_primary_enabled
from app.contexts.manifest import BOUNDED_CONTEXTS, BoundedContextMeta, contexts_by_id


class TestManifest:
    def test_bounded_contexts_non_empty(self):
        assert len(BOUNDED_CONTEXTS) >= 5

    def test_contexts_by_id_keys_match_ids(self):
        by_id = contexts_by_id()
        assert set(by_id) == {m.context_id for m in BOUNDED_CONTEXTS}

    def test_shipment_meta_fields(self):
        shipment = contexts_by_id()["shipment"]
        assert shipment.event_prefixes == ("shipment.",)
        assert shipment.handler_module.endswith("shipment_domain_handlers")

    def test_bounded_context_meta_is_frozen(self):
        meta = BoundedContextMeta(
            context_id="x",
            event_prefixes=("x.",),
            aggregate_paths=("app.domain.x",),
            handler_module="app.handlers.x",
        )
        with pytest.raises(AttributeError):
            meta.context_id = "y"  # type: ignore[misc]


class TestFlags:
    @pytest.fixture(autouse=True)
    def _clear_event_primary_env(self):
        keys = [k for k in os.environ if k.startswith("XCAGI_EVENT_PRIMARY")]
        saved = {k: os.environ.pop(k) for k in keys}
        try:
            yield
        finally:
            for k in keys:
                os.environ.pop(k, None)
            os.environ.update(saved)

    def test_any_disabled_when_unset(self):
        assert is_any_event_primary_enabled() is False

    def test_any_enabled_truthy_values(self):
        for val in ("1", "true", "YES", "On"):
            os.environ["XCAGI_EVENT_PRIMARY"] = val
            assert is_any_event_primary_enabled() is True

    def test_any_disabled_for_falsy_string(self):
        os.environ["XCAGI_EVENT_PRIMARY"] = "0"
        assert is_any_event_primary_enabled() is False

    def test_per_context_disabled_when_unset(self):
        assert is_event_primary_enabled("shipment") is False

    def test_per_context_global_wins(self):
        os.environ["XCAGI_EVENT_PRIMARY"] = "yes"
        assert is_event_primary_enabled("inventory") is True

    def test_per_context_specific_key(self):
        os.environ["XCAGI_EVENT_PRIMARY_ORDER"] = "on"
        assert is_event_primary_enabled("order") is True
        assert is_event_primary_enabled("shipment") is False

    def test_context_id_trimmed_and_uppercased(self):
        os.environ["XCAGI_EVENT_PRIMARY_SHIPMENT"] = "1"
        assert is_event_primary_enabled("  shipment  ") is True
