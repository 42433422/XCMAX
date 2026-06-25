"""Branch coverage for app.infrastructure.request_context.client_mods.

Covers parse_client_mods_off_header + ContextVar set/reset/get (0/4 branches).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.infrastructure.request_context import client_mods


class TestParseClientModsOffHeader:
    def test_lower_header_true(self):
        assert client_mods.parse_client_mods_off_header({"x-client-mods-off": "1"}) is True

    def test_lower_header_true_string(self):
        assert client_mods.parse_client_mods_off_header({"x-client-mods-off": "true"}) is True

    def test_lower_header_yes(self):
        assert client_mods.parse_client_mods_off_header({"x-client-mods-off": "yes"}) is True

    def test_lower_header_on(self):
        assert client_mods.parse_client_mods_off_header({"x-client-mods-off": "on"}) is True

    def test_lower_header_false_value(self):
        assert client_mods.parse_client_mods_off_header({"x-client-mods-off": "0"}) is False

    def test_lower_header_empty(self):
        assert client_mods.parse_client_mods_off_header({"x-client-mods-off": ""}) is False

    def test_lower_header_garbage(self):
        assert client_mods.parse_client_mods_off_header({"x-client-mods-off": "nope"}) is False

    def test_upper_header_true(self):
        assert client_mods.parse_client_mods_off_header({"X-Client-Mods-Off": "true"}) is True

    def test_upper_header_false_value(self):
        assert client_mods.parse_client_mods_off_header({"X-Client-Mods-Off": "false"}) is False

    def test_upper_header_takes_precedence_when_lower_absent(self):
        # Only upper-case variant present
        assert client_mods.parse_client_mods_off_header({"X-Client-Mods-Off": "1"}) is True

    def test_no_header_returns_false(self):
        assert client_mods.parse_client_mods_off_header({}) is False

    def test_none_value_in_header(self):
        assert client_mods.parse_client_mods_off_header({"x-client-mods-off": None}) is False

    def test_whitespace_value_trimmed(self):
        assert client_mods.parse_client_mods_off_header({"x-client-mods-off": "  TRUE  "}) is True

    def test_both_headers_lower_checked_first(self):
        # Lower-case key is checked first in the tuple order
        headers = {"x-client-mods-off": "0", "X-Client-Mods-Off": "1"}
        assert client_mods.parse_client_mods_off_header(headers) is False


class TestContextVarLifecycle:
    def test_default_is_false(self):
        assert client_mods.get_request_client_mods_ui_off() is False

    def test_set_true_then_get(self):
        token = client_mods.set_request_client_mods_ui_off(True)
        try:
            assert client_mods.get_request_client_mods_ui_off() is True
        finally:
            client_mods.reset_request_client_mods_ui_off(token)
        assert client_mods.get_request_client_mods_ui_off() is False

    def test_set_false_then_get(self):
        token = client_mods.set_request_client_mods_ui_off(False)
        try:
            assert client_mods.get_request_client_mods_ui_off() is False
        finally:
            client_mods.reset_request_client_mods_ui_off(token)

    def test_set_truthy_non_bool_coerced(self):
        token = client_mods.set_request_client_mods_ui_off(1)
        try:
            assert client_mods.get_request_client_mods_ui_off() is True
        finally:
            client_mods.reset_request_client_mods_ui_off(token)

    def test_set_falsy_non_bool_coerced(self):
        token = client_mods.set_request_client_mods_ui_off(0)
        try:
            assert client_mods.get_request_client_mods_ui_off() is False
        finally:
            client_mods.reset_request_client_mods_ui_off(token)

    def test_nested_set_reset(self):
        t1 = client_mods.set_request_client_mods_ui_off(True)
        assert client_mods.get_request_client_mods_ui_off() is True
        t2 = client_mods.set_request_client_mods_ui_off(False)
        assert client_mods.get_request_client_mods_ui_off() is False
        client_mods.reset_request_client_mods_ui_off(t2)
        assert client_mods.get_request_client_mods_ui_off() is True
        client_mods.reset_request_client_mods_ui_off(t1)
        assert client_mods.get_request_client_mods_ui_off() is False
