"""Tests for app.mod_sdk.lan_pages_compat."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from app.mod_sdk.lan_pages_compat import (
    list_lan_pages_registry,
    MOD_PAGE_PREFIX,
    HOST_PAGES,
)


class TestLanPagesRegistry:
    @patch("app.mod_sdk.lan_pages_compat.is_lan_via_mod_enabled", return_value=True)
    def test_mod_enabled(self, mock_enabled):
        result = list_lan_pages_registry()
        assert result["success"] is True
        assert result["pages_via_mod"] is True
        assert result["execution_path"] == "mod_pages"
        assert result["phase"] == "K"

    @patch("app.mod_sdk.lan_pages_compat.is_lan_via_mod_enabled", return_value=False)
    def test_mod_disabled(self, mock_enabled):
        result = list_lan_pages_registry()
        assert result["success"] is True
        assert result["pages_via_mod"] is False
        assert result["execution_path"] == "host.routes"

    def test_host_pages_constant(self):
        assert "/lan-gate" in HOST_PAGES

    def test_mod_page_prefix(self):
        assert "mod/" in MOD_PAGE_PREFIX

    @patch("app.mod_sdk.lan_pages_compat.is_lan_via_mod_enabled", return_value=True)
    def test_host_route_preserved(self, mock_enabled):
        result = list_lan_pages_registry()
        assert result["host_route_preserved"] is True

    @patch("app.mod_sdk.lan_pages_compat.is_lan_via_mod_enabled", return_value=True)
    def test_page_count(self, mock_enabled):
        result = list_lan_pages_registry()
        assert result["page_count"] == len(HOST_PAGES)
