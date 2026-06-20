"""Tests for app.desktop_runtime.db."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.desktop_runtime.db import configure_sqlite_defaults, database_file


class TestConfigureSqliteDefaults:
    """Tests for configure_sqlite_defaults."""

    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    @patch("app.desktop_runtime.db.sqlite_database_url", return_value="sqlite:///test.db")
    def test_sets_database_url_env(self, mock_url: MagicMock, mock_dirs: MagicMock) -> None:
        mock_dirs.return_value = {
            "root": Path("/tmp/test_xcagi"),
            "data": Path("/tmp/test_xcagi/data"),
        }
        with patch.dict("os.environ", {}, clear=False):
            result = configure_sqlite_defaults()
            assert "DATABASE_URL" in os.environ

    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    @patch("app.desktop_runtime.db.sqlite_database_url", return_value="sqlite:///custom.db")
    def test_respects_env_override(self, mock_url: MagicMock, mock_dirs: MagicMock) -> None:
        mock_dirs.return_value = {
            "root": Path("/tmp/test_xcagi"),
            "data": Path("/tmp/test_xcagi/data"),
        }
        with patch.dict(
            "os.environ", {"XCAGI_DESKTOP_DATABASE_URL": "sqlite:///override.db"}, clear=False
        ):
            result = configure_sqlite_defaults()
            assert os.environ["DATABASE_URL"] == "sqlite:///override.db"

    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    @patch("app.desktop_runtime.db.sqlite_database_url", return_value="sqlite:///test.db")
    def test_sets_vector_db_url(self, mock_url: MagicMock, mock_dirs: MagicMock) -> None:
        mock_dirs.return_value = {
            "root": Path("/tmp/test_xcagi"),
            "data": Path("/tmp/test_xcagi/data"),
        }
        with patch.dict("os.environ", {}, clear=False):
            result = configure_sqlite_defaults()
            assert "VECTOR_DB_URL" in os.environ

    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    @patch("app.desktop_runtime.db.sqlite_database_url", return_value="sqlite:///test.db")
    def test_returns_database_url(self, mock_url: MagicMock, mock_dirs: MagicMock) -> None:
        mock_dirs.return_value = {
            "root": Path("/tmp/test_xcagi"),
            "data": Path("/tmp/test_xcagi/data"),
        }
        with patch.dict("os.environ", {}, clear=False):
            result = configure_sqlite_defaults()
            assert isinstance(result, str)


class TestDatabaseFile:
    """Tests for database_file."""

    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    def test_returns_path_to_xcagi_db(self, mock_dirs: MagicMock) -> None:
        mock_dirs.return_value = {"data": Path("/tmp/test_xcagi/data")}
        result = database_file()
        assert result.name == "xcagi.db"
        assert "data" in str(result)

    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    def test_custom_data_dir(self, mock_dirs: MagicMock) -> None:
        mock_dirs.return_value = {"data": Path("/custom/path/data")}
        result = database_file("/custom/path")
        assert str(result).startswith("/custom/path")
