"""Tests for app.application.tools.tool_result_client."""
from __future__ import annotations

import pytest

from app.application.tools.tool_result_client import (
    flatten_tool_result_dict_for_client,
    _pick_client_fields,
)


class TestPickClientFields:
    def test_empty_dict(self):
        assert _pick_client_fields({}) == {}

    def test_picks_known_keys(self):
        src = {"download_url": "https://...", "file_name": "test.pdf", "unknown_key": "skip"}
        result = _pick_client_fields(src)
        assert "download_url" in result
        assert "file_name" in result
        assert "unknown_key" not in result

    def test_skips_none_values(self):
        src = {"download_url": None, "file_name": "test.pdf"}
        result = _pick_client_fields(src)
        assert "download_url" not in result
        assert "file_name" in result

    def test_skips_empty_string_values(self):
        src = {"download_url": "", "file_name": "test.pdf"}
        result = _pick_client_fields(src)
        assert "download_url" not in result


class TestFlattenToolResultDictForClient:
    def test_none_returns_empty(self):
        assert flatten_tool_result_dict_for_client(None) == {}

    def test_empty_dict_returns_empty(self):
        assert flatten_tool_result_dict_for_client({}) == {}

    def test_non_dict_returns_empty(self):
        assert flatten_tool_result_dict_for_client("not a dict") == {}

    def test_top_level_fields(self):
        raw = {"download_url": "https://...", "file_name": "test.pdf"}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["download_url"] == "https://..."
        assert result["file_name"] == "test.pdf"

    def test_nested_data_fields(self):
        raw = {"data": {"download_url": "https://nested...", "order_number": "123"}}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["download_url"] == "https://nested..."
        assert result["order_number"] == "123"

    def test_nested_document_fields(self):
        raw = {"document": {"file_path": "/tmp/doc.pdf", "doc_name": "doc"}}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["file_path"] == "/tmp/doc.pdf"
        assert result["doc_name"] == "doc"

    def test_top_level_takes_precedence(self):
        raw = {"download_url": "top", "data": {"download_url": "nested"}}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["download_url"] == "top"

    def test_success_field_mapped(self):
        raw = {"success": True}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["tool_success"] is True

    def test_tool_key_mapped(self):
        raw = {"tool_key": "search"}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["tool_key"] == "search"

    def test_tool_name_mapped_to_tool_key(self):
        raw = {"tool_name": "search"}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["tool_key"] == "search"

    def test_error_field_mapped(self):
        raw = {"error": "something went wrong"}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["tool_error"] == "something went wrong"

    def test_error_truncated(self):
        raw = {"error": "x" * 600}
        result = flatten_tool_result_dict_for_client(raw)
        assert len(result["tool_error"]) <= 500

    def test_tool_key_stripped(self):
        raw = {"tool_key": "  search  "}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["tool_key"] == "search"
