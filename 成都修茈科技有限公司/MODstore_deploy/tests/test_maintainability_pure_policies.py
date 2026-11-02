"""Regressions for extracted MODstore policies without importing service facades."""

from __future__ import annotations

import pytest

from modstore_server.customer_service_triage import (
    _parse_domain_clarify_reply,
    resolve_triage_lane,
)
from modstore_server.employee_executor_policies import (
    _flag_enabled,
    _is_transient_llm_error,
)


@pytest.mark.parametrize(
    ("message", "domain"),
    [
        ("是平台", "platform"),
        (" 平台问题！", "platform"),
        ("软件", "software"),
        ("这个Mod功能问题", "software"),
        ("客户定制功能出错", "custom"),
        ("账号定制", "custom"),
        ("需要客服", ""),
        ("", ""),
    ],
)
def test_clarify_domain_compatibility(message, domain):
    assert _parse_domain_clarify_reply(message) == domain


@pytest.mark.parametrize(
    ("intent", "lane"),
    [
        ("product_issue", "product_defect"),
        ("account_support", "ultimate_review"),
        ("general", "ultimate_review"),
        ("greeting", "ultimate_review"),
        ("refund", "commerce"),
        ("catalog_complaint", "commerce"),
        ("catalog_review", "commerce"),
        ("llm_extension", "commerce"),
        ("unknown", "general"),
    ],
)
def test_triage_lane_compatibility(intent, lane):
    assert resolve_triage_lane(intent) == lane


@pytest.mark.parametrize(
    ("value", "enabled"),
    [(True, True), (False, False), (" YES ", True), ("on", True), ("1", True), ("no", False), (0, False), (None, False)],
)
def test_executor_flag_policy(value, enabled):
    assert _flag_enabled(value) is enabled


@pytest.mark.parametrize(
    ("message", "transient"),
    [
        ("readtimeout while connecting", True),
        ("HTTP 503 Service Unavailable", True),
        ("rate limit 429", True),
        ("connection reset by peer", True),
        ("invalid auth token", False),
        ("business validation error", False),
        ("", False),
    ],
)
def test_executor_transient_error_policy(message, transient):
    assert _is_transient_llm_error(message) is transient
