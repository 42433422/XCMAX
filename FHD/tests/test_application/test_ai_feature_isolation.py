"""AI feature channel isolation between smart chat and business docking."""

from __future__ import annotations

from app.application.ai_feature_isolation import (
    BUSINESS_DOCKING,
    SMART_CHAT,
    ai_feature_channel,
    allows_channel,
    normalize_channel,
    tag_mapping,
)
from app.application.elt.errors import ReviewedExcelError, is_definite_provider_failure


def test_normalize_channel_aliases():
    assert normalize_channel("chat") == SMART_CHAT
    assert normalize_channel("office_docking") == BUSINESS_DOCKING
    assert normalize_channel("reviewed-excel") == BUSINESS_DOCKING


def test_tag_and_filter_by_active_channel():
    with ai_feature_channel(SMART_CHAT):
        chat = tag_mapping({"k": 1})
        dock = tag_mapping({"k": 2}, channel=BUSINESS_DOCKING)
        assert chat["ai_feature_channel"] == SMART_CHAT
        assert allows_channel(chat, SMART_CHAT)
        assert not allows_channel(dock, SMART_CHAT)
        assert allows_channel({}, SMART_CHAT)  # legacy untagged visible


def test_definite_provider_failure_detects_404():
    assert is_definite_provider_failure(ReviewedExcelError("gone", provider_status=404))
    assert not is_definite_provider_failure(ReviewedExcelError("maybe"))
