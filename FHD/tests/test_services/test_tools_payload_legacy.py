"""Tests for app.services.tools_payload_legacy — coverage ramp."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from app.services.tools_payload_legacy import dispatch_legacy_tool_payload


def _json_fn(data, status=200):
    return {"_response": data, "_status": status}


def _hdr_getter(key):
    return None


def _parse_order_text(text):
    return {"order_text": text}


# ========================= products tool =================================


class TestProductsTool:
    def test_search_with_keyword(self):
        result = dispatch_legacy_tool_payload(
            "products", "search", {"keyword": "test"}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True
        assert "keyword=test" in result["_response"]["redirect"]

    def test_exec_action_falls_to_view(self):
        result = dispatch_legacy_tool_payload(
            "products", "exec", {"action": "view"}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True
        assert "products" in result["_response"]["redirect"]

    def test_view_action(self):
        result = dispatch_legacy_tool_payload(
            "products", "view", {}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True

    def test_run_action_with_keyword(self):
        result = dispatch_legacy_tool_payload(
            "products", "run", {"keyword": "abc", "action": "search"}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True

    def test_no_keyword_no_search(self):
        result = dispatch_legacy_tool_payload(
            "products", "other", {}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True


# ========================= chat tool =====================================


class TestChatTool:
    def test_chat_redirect(self):
        result = dispatch_legacy_tool_payload(
            "chat", "open", {}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True
        assert "chat" in result["_response"]["redirect"]


# ========================= ai_ecosystem tool =============================


class TestAiEcosystemTool:
    def test_list_action(self):
        result = dispatch_legacy_tool_payload(
            "ai_ecosystem", "list", {}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True
        assert "data" in result["_response"]

    def test_query_action(self):
        result = dispatch_legacy_tool_payload(
            "ai_ecosystem", "query", {}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True

    def test_other_action(self):
        result = dispatch_legacy_tool_payload(
            "ai_ecosystem", "open", {}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True
        assert "redirect" in result["_response"]


# ========================= business_docking tool =========================


class TestBusinessDockingTool:
    def test_extract_no_file_path(self):
        result = dispatch_legacy_tool_payload(
            "business_docking", "extract", {}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is False
        assert result["_status"] == 400

    def test_other_action_redirect(self):
        result = dispatch_legacy_tool_payload(
            "business_docking", "open", {}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True


# ========================= customers tool ================================


class TestCustomersTool:
    def test_search_with_keyword(self):
        result = dispatch_legacy_tool_payload(
            "customers", "search", {"keyword": "公司A"}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True
        assert "keyword=" in result["_response"]["redirect"]

    def test_query_with_name_as_keyword(self):
        result = dispatch_legacy_tool_payload(
            "customers", "query", {"unit_name": "公司B"}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True

    def test_view_action(self):
        result = dispatch_legacy_tool_payload(
            "customers", "view", {}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True

    def test_exec_action_with_sub_action(self):
        result = dispatch_legacy_tool_payload(
            "customers", "执行", {"action": "search", "keyword": "公司F"}, json_response_fn=_json_fn, hdr_getter=_hdr_getter, parse_order_text_fn=_parse_order_text
        )
        assert result["_response"]["success"] is True
