"""Tests for app.services.document_templates.renderer — pure helper functions."""

from __future__ import annotations

import json

import pytest

from app.services.document_templates.renderer import (
    _is_unreadable_workbook_error,
    _parse_json_dict,
    _parse_json_list,
)

# ========================= _is_unreadable_workbook_error =================


class TestIsUnreadableWorkbookError:
    def test_unable_to_read(self):
        assert _is_unreadable_workbook_error("Unable to read workbook") is True

    def test_could_not_read(self):
        assert _is_unreadable_workbook_error("Could not read worksheets") is True

    def test_invalid_xml(self):
        assert _is_unreadable_workbook_error("Invalid XML content") is True

    def test_badzipfile(self):
        assert _is_unreadable_workbook_error("BadZipFile: not a zip file") is True

    def test_normal_error(self):
        assert _is_unreadable_workbook_error("Permission denied") is False

    def test_empty(self):
        assert _is_unreadable_workbook_error("") is False

    def test_none(self):
        assert _is_unreadable_workbook_error(None) is False

    def test_case_insensitive(self):
        assert _is_unreadable_workbook_error("unable TO READ workbook") is True


# ========================= _parse_json_dict ==============================


class TestParseJsonDict:
    def test_valid_dict(self):
        result = _parse_json_dict('{"key": "value"}')
        assert result == {"key": "value"}

    def test_invalid_json(self):
        result = _parse_json_dict("not json")
        assert result == {}

    def test_none(self):
        result = _parse_json_dict(None)
        assert result == {}

    def test_empty_string(self):
        result = _parse_json_dict("")
        assert result == {}

    def test_list_input(self):
        result = _parse_json_dict("[1,2,3]")
        assert result == {}

    def test_already_dict(self):
        result = _parse_json_dict({"key": "val"})
        assert result == {"key": "val"}


# ========================= _parse_json_list ==============================


class TestParseJsonList:
    def test_valid_list(self):
        result = _parse_json_list("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_invalid_json(self):
        result = _parse_json_list("not json")
        assert result == []

    def test_none(self):
        result = _parse_json_list(None)
        assert result == []

    def test_empty_string(self):
        result = _parse_json_list("")
        assert result == []

    def test_dict_input(self):
        result = _parse_json_list('{"key": "val"}')
        assert result == []

    def test_already_list(self):
        result = _parse_json_list([1, 2])
        assert result == [1, 2]
