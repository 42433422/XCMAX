"""Regressions for extracted MODstore policies without importing service facades."""

from __future__ import annotations

import pytest

from modstore_server.customer_service_triage import (
    _parse_domain_clarify_reply,
    resolve_triage_lane,
    ticket_taxonomy,
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
    ("intent", "submitter", "evidence", "expected"),
    [
        ("product_issue", "customer", {"issue_domain": "platform"}, ("缺陷", "平台", "客户对话")),
        ("custom_delivery", "admin", {"issue_domain": "custom"}, ("交付实施", "客户定制", "管理员自建")),
        ("refund", "customer", {}, ("服务请求", "", "客户对话")),
        ("account_support", "unknown", {"source": "github_self_heal"}, ("事故", "", "GitHub 自愈")),
        ("general", "unknown", {}, ("咨询", "", "")),
    ],
)
def test_ticket_taxonomy_derivation(intent, submitter, evidence, expected):
    taxonomy = ticket_taxonomy(intent, submitter, evidence)
    assert (
        taxonomy["ticket_type_label"],
        taxonomy["ticket_domain_label"],
        taxonomy["ticket_source_label"],
    ) == expected


@pytest.mark.parametrize(
    ("value", "enabled"),
    [
        (True, True),
        (False, False),
        (" YES ", True),
        ("on", True),
        ("1", True),
        ("no", False),
        (0, False),
        (None, False),
    ],
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
