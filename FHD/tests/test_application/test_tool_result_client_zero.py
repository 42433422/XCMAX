"""Tests for app.application.tools.tool_result_client."""
from __future__ import annotations

import pytest

from app.application.tools.tool_result_client import (
    _CLIENT_KEYS,
    _pick_client_fields,
    flatten_tool_result_dict_for_client,
)


class TestPickClientFields:
    """Tests for _pick_client_fields."""

    def test_picks_known_fields(self) -> None:
        src = {"download_url": "https://example.com/f", "file_name": "test.pdf", "other": "ignored"}
        result = _pick_client_fields(src)
        assert result == {"download_url": "https://example.com/f", "file_name": "test.pdf"}

    def test_skips_none_values(self) -> None:
        src = {"download_url": None, "file_name": "test.pdf"}
        result = _pick_client_fields(src)
        assert "download_url" not in result
        assert result["file_name"] == "test.pdf"

    def test_skips_empty_string_values(self) -> None:
        src = {"download_url": "", "file_name": "test.pdf"}
        result = _pick_client_fields(src)
        assert "download_url" not in result

    def test_empty_source(self) -> None:
        result = _pick_client_fields({})
        assert result == {}


class TestFlattenToolResultDictForClient:
    """Tests for flatten_tool_result_dict_for_client."""

    def test_none_input(self) -> None:
        result = flatten_tool_result_dict_for_client(None)
        assert result == {}

    def test_empty_dict(self) -> None:
        result = flatten_tool_result_dict_for_client({})
        assert result == {}

    def test_non_dict_input(self) -> None:
        result = flatten_tool_result_dict_for_client("not a dict")
        assert result == {}

    def test_top_level_fields(self) -> None:
        raw = {"download_url": "https://example.com/f", "file_name": "test.pdf"}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["download_url"] == "https://example.com/f"
        assert result["file_name"] == "test.pdf"

    def test_nested_data_fields(self) -> None:
        raw = {"data": {"download_url": "https://nested.com/f", "order_number": "ORD-001"}}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["download_url"] == "https://nested.com/f"
        assert result["order_number"] == "ORD-001"

    def test_top_level_takes_precedence_over_nested(self) -> None:
        raw = {"download_url": "top-level", "data": {"download_url": "nested"}}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["download_url"] == "top-level"

    def test_nested_document_fields(self) -> None:
        raw = {"document": {"file_name": "doc.pdf", "doc_name": "My Doc"}}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["file_name"] == "doc.pdf"
        assert result["doc_name"] == "My Doc"

    def test_success_field_mapped_to_tool_success(self) -> None:
        raw = {"success": True}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["tool_success"] is True

    def test_tool_key_from_tool_key(self) -> None:
        raw = {"tool_key": "my_tool"}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["tool_key"] == "my_tool"

    def test_tool_key_from_tool_name(self) -> None:
        raw = {"tool_name": "my_tool"}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["tool_key"] == "my_tool"

    def test_error_field_mapped(self) -> None:
        raw = {"error": "something went wrong"}
        result = flatten_tool_result_dict_for_client(raw)
        assert result["tool_error"] == "something went wrong"

    def test_error_truncated_to_500_chars(self) -> None:
        raw = {"error": "x" * 1000}
        result = flatten_tool_result_dict_for_client(raw)
        assert len(result["tool_error"]) == 500

    def test_empty_tool_key_ignored(self) -> None:
        raw = {"tool_key": ""}
        result = flatten_tool_result_dict_for_client(raw)
        assert "tool_key" not in result

    def test_client_keys_constant(self) -> None:
        assert "download_url" in _CLIENT_KEYS
        assert "file_name" in _CLIENT_KEYS
        assert "message" in _CLIENT_KEYS
