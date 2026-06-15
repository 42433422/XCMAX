"""Tests for app.services.document_templates.crud — pure helper functions."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.services.document_templates.crud import _normalize_db_template_id


# ========================= _normalize_db_template_id =====================


class TestNormalizeDbTemplateId:
    def test_plain_int(self):
        assert _normalize_db_template_id("42") == 42

    def test_db_prefix(self):
        assert _normalize_db_template_id("db:42") == 42

    def test_db_prefix_with_spaces(self):
        assert _normalize_db_template_id("db: 42") == 42

    def test_int_input(self):
        assert _normalize_db_template_id(42) == 42

    def test_non_numeric(self):
        assert _normalize_db_template_id("abc") is None

    def test_empty(self):
        assert _normalize_db_template_id("") is None

    def test_none(self):
        assert _normalize_db_template_id(None) is None

    def test_whitespace(self):
        assert _normalize_db_template_id("  ") is None

    def test_float_string(self):
        assert _normalize_db_template_id("3.14") is None

    def test_negative(self):
        assert _normalize_db_template_id("-1") is None
