"""Tests for app.mod_sdk.lan_pages_compat."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk.lan_pages_compat import (
    HOST_PAGES,
    MOD_PAGE_PREFIX,
    list_lan_pages_registry,
)


class TestConstants:
    """Tests for module constants."""

    def test_host_pages_contains_lan_gate(self) -> None:
        assert "/lan-gate" in HOST_PAGES

    def test_mod_page_prefix_starts_with_mod(self) -> None:
        assert MOD_PAGE_PREFIX.startswith("/mod/")


class TestListLanPagesRegistry:
    """Tests for list_lan_pages_registry."""

    @patch("app.mod_sdk.lan_pages_compat.is_lan_via_mod_enabled", return_value=True)
    def test_registry_with_mod_enabled(self, mock_enabled: MagicMock) -> None:
        result = list_lan_pages_registry()
        assert result["success"] is True
        assert result["pages_via_mod"] is True
        assert result["host_route_preserved"] is True
        assert result["execution_path"] == "mod_pages"
        assert result["phase"] == "K"

    @patch("app.mod_sdk.lan_pages_compat.is_lan_via_mod_enabled", return_value=False)
    def test_registry_with_mod_disabled(self, mock_enabled: MagicMock) -> None:
        result = list_lan_pages_registry()
        assert result["success"] is True
        assert result["pages_via_mod"] is False
        assert result["execution_path"] == "host.routes"

    @patch("app.mod_sdk.lan_pages_compat.is_lan_via_mod_enabled", return_value=True)
    def test_registry_has_page_count(self, mock_enabled: MagicMock) -> None:
        result = list_lan_pages_registry()
        assert result["page_count"] == len(HOST_PAGES)

    @patch("app.mod_sdk.lan_pages_compat.is_lan_via_mod_enabled", return_value=True)
    def test_registry_has_mod_id(self, mock_enabled: MagicMock) -> None:
        result = list_lan_pages_registry()
        assert "mod_id" in result
        assert result["mod_id"] is not None
