"""Tests for app.desktop_automation.drivers."""
from __future__ import annotations

import pytest

from app.desktop_automation.drivers import (
    MCPDriver,
    MacDriver,
    WindowsDriver,
    _BaseDriver,
)


class TestBaseDriver:
    """Tests for _BaseDriver."""

    def test_name(self) -> None:
        driver = _BaseDriver()
        assert driver.name == "base"

    def test_is_available_returns_false(self) -> None:
        driver = _BaseDriver()
        assert driver.is_available() is False


class TestWindowsDriver:
    """Tests for WindowsDriver."""

    def test_name(self) -> None:
        driver = WindowsDriver()
        assert driver.name == "windows"

    def test_is_available_returns_false(self) -> None:
        driver = WindowsDriver()
        assert driver.is_available() is False

    def test_inherits_from_base(self) -> None:
        assert issubclass(WindowsDriver, _BaseDriver)


class TestMacDriver:
    """Tests for MacDriver."""

    def test_name(self) -> None:
        driver = MacDriver()
        assert driver.name == "mac"

    def test_is_available_returns_false(self) -> None:
        driver = MacDriver()
        assert driver.is_available() is False

    def test_inherits_from_base(self) -> None:
        assert issubclass(MacDriver, _BaseDriver)


class TestMCPDriver:
    """Tests for MCPDriver."""

    def test_name(self) -> None:
        driver = MCPDriver()
        assert driver.name == "mcp"

    def test_is_available_returns_false(self) -> None:
        driver = MCPDriver()
        assert driver.is_available() is False

    def test_default_target(self) -> None:
        driver = MCPDriver()
        assert driver.target == ""

    def test_custom_target(self) -> None:
        driver = MCPDriver(target="my-target")
        assert driver.target == "my-target"

    def test_inherits_from_base(self) -> None:
        assert issubclass(MCPDriver, _BaseDriver)
