"""Tests for app.desktop_automation.drivers."""
from __future__ import annotations

import pytest

from app.desktop_automation.drivers import _BaseDriver, WindowsDriver, MacDriver, MCPDriver


class TestBaseDriver:
    def test_name(self):
        d = _BaseDriver()
        assert d.name == "base"

    def test_is_available_false(self):
        d = _BaseDriver()
        assert d.is_available() is False


class TestWindowsDriver:
    def test_name(self):
        d = WindowsDriver()
        assert d.name == "windows"

    def test_is_available_false(self):
        d = WindowsDriver()
        assert d.is_available() is False


class TestMacDriver:
    def test_name(self):
        d = MacDriver()
        assert d.name == "mac"

    def test_is_available_false(self):
        d = MacDriver()
        assert d.is_available() is False


class TestMCPDriver:
    def test_name(self):
        d = MCPDriver()
        assert d.name == "mcp"

    def test_is_available_false(self):
        d = MCPDriver()
        assert d.is_available() is False

    def test_target_attribute(self):
        d = MCPDriver(target="test-target")
        assert d.target == "test-target"

    def test_default_target_empty(self):
        d = MCPDriver()
        assert d.target == ""
