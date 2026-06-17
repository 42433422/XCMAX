"""Tests for app.desktop_runtime.paths."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.desktop_runtime.paths import (
    DATA_DIR_ENV,
    DESKTOP_ENV,
    LEGACY_DATA_DIR_ENV,
    ensure_desktop_dirs,
    get_desktop_data_dir,
    get_desktop_mode,
    is_desktop_mode,
    sqlite_database_url,
)


class TestGetDesktopMode:
    """Tests for get_desktop_mode."""

    def test_default_mode(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert get_desktop_mode() == "0"

    def test_enabled_mode(self) -> None:
        with patch.dict("os.environ", {DESKTOP_ENV: "1"}):
            assert get_desktop_mode() == "1"

    def test_true_mode(self) -> None:
        with patch.dict("os.environ", {DESKTOP_ENV: "true"}):
            assert get_desktop_mode() == "true"


class TestIsDesktopMode:
    """Tests for is_desktop_mode."""

    def test_enabled_values(self) -> None:
        for val in ("1", "true", "yes", "on"):
            with patch.dict("os.environ", {DESKTOP_ENV: val}):
                assert is_desktop_mode() is True

    def test_disabled_values(self) -> None:
        for val in ("0", "false", "no", "off", ""):
            with patch.dict("os.environ", {DESKTOP_ENV: val}, clear=True):
                assert is_desktop_mode() is False


class TestGetDesktopDataDir:
    """Tests for get_desktop_data_dir."""

    def test_explicit_data_dir(self) -> None:
        result = get_desktop_data_dir("/custom/path")
        assert str(result) == "/custom/path"

    def test_env_data_dir(self) -> None:
        with patch.dict("os.environ", {DATA_DIR_ENV: "/env/path"}):
            result = get_desktop_data_dir()
            assert str(result) == "/env/path"

    def test_legacy_env_data_dir(self) -> None:
        with patch.dict("os.environ", {LEGACY_DATA_DIR_ENV: "/legacy/path"}, clear=True):
            result = get_desktop_data_dir()
            assert str(result) == "/legacy/path"

    def test_default_data_dir(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = get_desktop_data_dir()
            assert "XCAGI" in str(result)


class TestEnsureDesktopDirs:
    """Tests for ensure_desktop_dirs."""

    def test_creates_all_dirs(self, tmp_path: Path) -> None:
        result = ensure_desktop_dirs(str(tmp_path / "xcagi_test"))
        assert all(p.exists() for p in result.values())
        assert "root" in result
        assert "data" in result
        assert "uploads" in result
        assert "logs" in result
        assert "mods" in result

    def test_returns_path_objects(self, tmp_path: Path) -> None:
        result = ensure_desktop_dirs(str(tmp_path / "xcagi_test2"))
        for v in result.values():
            assert isinstance(v, Path)


class TestSqliteDatabaseUrl:
    """Tests for sqlite_database_url."""

    def test_returns_sqlite_url(self, tmp_path: Path) -> None:
        result = sqlite_database_url(str(tmp_path / "xcagi_test"))
        assert result.startswith("sqlite:///")
        assert "xcagi.db" in result
