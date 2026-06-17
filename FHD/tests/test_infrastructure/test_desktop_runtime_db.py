"""Tests for app.desktop_runtime.db."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from unittest.mock import patch

from app.desktop_runtime.db import configure_sqlite_defaults, database_file


class TestConfigureSqliteDefaults:
    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    def test_returns_database_url(self, mock_dirs, monkeypatch):
        mock_dirs.return_value = {
            "root": Path("/tmp/desktop"),
            "data": Path("/tmp/desktop/data"),
        }
        monkeypatch.delenv("XCAGI_DESKTOP_DATABASE_URL", raising=False)
        monkeypatch.delenv("XCAGI_DESKTOP_VECTOR_DB_URL", raising=False)

        result = configure_sqlite_defaults()
        assert "sqlite" in result.lower() or "DATABASE_URL" in os.environ

    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    def test_custom_env_url(self, mock_dirs, monkeypatch):
        mock_dirs.return_value = {
            "root": Path("/tmp/desktop"),
            "data": Path("/tmp/desktop/data"),
        }
        monkeypatch.setenv("XCAGI_DESKTOP_DATABASE_URL", "sqlite:///custom.db")

        result = configure_sqlite_defaults()
        assert result == "sqlite:///custom.db"

    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    def test_vector_db_url_set(self, mock_dirs, monkeypatch):
        mock_dirs.return_value = {
            "root": Path("/tmp/desktop"),
            "data": Path("/tmp/desktop/data"),
        }
        monkeypatch.delenv("XCAGI_DESKTOP_DATABASE_URL", raising=False)
        monkeypatch.delenv("XCAGI_DESKTOP_VECTOR_DB_URL", raising=False)

        configure_sqlite_defaults()
        assert "VECTOR_DB_URL" in os.environ


class TestDatabaseFile:
    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    def test_returns_path(self, mock_dirs):
        mock_dirs.return_value = {
            "root": Path("/tmp/desktop"),
            "data": Path("/tmp/desktop/data"),
        }
        result = database_file()
        assert str(result).endswith("xcagi.db")

    @patch("app.desktop_runtime.db.ensure_desktop_dirs")
    def test_custom_data_dir(self, mock_dirs):
        mock_dirs.return_value = {
            "root": Path("/custom"),
            "data": Path("/custom/data"),
        }
        result = database_file(data_dir="/custom")
        assert "xcagi.db" in str(result)
