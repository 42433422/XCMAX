"""Tests for app.db.init_db — coverage ramp."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.db.init_db import (
    _is_desktop_mode_env,
    build_mod_database_seed_plan,
    ensure_sqlite_per_mod_database_copies,
    get_db_path,
    get_distillation_db_path,
    initialize_databases,
    refresh_config_database_urls,
)

# ========================= _is_desktop_mode_env ==========================


class TestIsDesktopModeEnv:
    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DESKTOP_MODE", raising=False)
        assert _is_desktop_mode_env() is False

    def test_1(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
        assert _is_desktop_mode_env() is True

    def test_true(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "true")
        assert _is_desktop_mode_env() is True

    def test_yes(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "yes")
        assert _is_desktop_mode_env() is True

    def test_on(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "on")
        assert _is_desktop_mode_env() is True

    def test_false(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "false")
        assert _is_desktop_mode_env() is False

    def test_empty(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "")
        assert _is_desktop_mode_env() is False


# ========================= refresh_config_database_urls ==================


class TestRefreshConfigDatabaseUrls:
    def test_none_config(self):
        refresh_config_database_urls(None)

    def test_sets_env_vars(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.setenv("VECTOR_DB_URL", "pgvector://test")
        monkeypatch.setenv("DATABASE_PATH", "/tmp/test.db")

        class MockConfig:
            DATABASE_URL = ""
            VECTOR_DB_URL = ""
            DATABASE_PATH = ""

        refresh_config_database_urls(MockConfig)
        assert MockConfig.DATABASE_URL == "postgresql://test"
        assert MockConfig.VECTOR_DB_URL == "pgvector://test"
        assert MockConfig.DATABASE_PATH == "/tmp/test.db"

    def test_no_env_vars(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("VECTOR_DB_URL", raising=False)
        monkeypatch.delenv("DATABASE_PATH", raising=False)

        class MockConfig:
            DATABASE_URL = "original"
            VECTOR_DB_URL = "original"
            DATABASE_PATH = "original"

        refresh_config_database_urls(MockConfig)
        assert MockConfig.DATABASE_URL == "original"

    def test_partial_env_vars(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://test")
        monkeypatch.delenv("VECTOR_DB_URL", raising=False)
        monkeypatch.delenv("DATABASE_PATH", raising=False)

        class MockConfig:
            DATABASE_URL = ""
            VECTOR_DB_URL = "keep"
            DATABASE_PATH = "keep"

        refresh_config_database_urls(MockConfig)
        assert MockConfig.DATABASE_URL == "postgresql://test"
        assert MockConfig.VECTOR_DB_URL == "keep"


# ========================= initialize_databases ==========================


class TestInitializeDatabases:
    def test_creates_db_from_seed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

        seed_dir = tmp_path / "seed"
        seed_dir.mkdir()
        (seed_dir / "products.db").write_bytes(b"test")

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.db.init_db._iter_seed_dirs", return_value=[str(seed_dir)]),
            patch("app.db.init_db.sqlite_conn") as mock_conn,
        ):
            mock_cm = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_cm.__enter__ = Mock(return_value=mock_cm)
            mock_cm.__exit__ = Mock(return_value=False)
            mock_cm.cursor.return_value = mock_cursor
            mock_conn.return_value = mock_cm

            initialize_databases(["products.db"])

    def test_skips_existing_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
        (tmp_path / "products.db").write_bytes(b"existing")

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.db.init_db._iter_seed_dirs", return_value=[]),
        ):
            initialize_databases(["products.db"])
            assert (tmp_path / "products.db").read_bytes() == b"existing"

    def test_no_seed_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.db.init_db._iter_seed_dirs", return_value=[]),
        ):
            initialize_databases(["nonexistent.db"])


# ========================= ensure_sqlite_per_mod_database_copies =========


class TestEnsureSqlitePerModDatabaseCopies:
    def test_copies_for_mod(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
        (tmp_path / "products.db").write_bytes(b"mother_db")

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix") as mock_suffix,
        ):
            mock_suffix.side_effect = lambda name, mod_id: (
                f"products__{mod_id}.db" if mod_id else name
            )
            ensure_sqlite_per_mod_database_copies(["test_mod"])

        assert (tmp_path / "products__test_mod.db").exists()

    def test_skips_existing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
        (tmp_path / "products.db").write_bytes(b"mother_db")
        (tmp_path / "products__test_mod.db").write_bytes(b"existing_mod_db")

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix") as mock_suffix,
        ):
            mock_suffix.side_effect = lambda name, mod_id: (
                f"products__{mod_id}.db" if mod_id else name
            )
            ensure_sqlite_per_mod_database_copies(["test_mod"])

        assert (tmp_path / "products__test_mod.db").read_bytes() == b"existing_mod_db"

    def test_empty_mod_ids(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix") as mock_suffix,
        ):
            mock_suffix.side_effect = lambda name, mod_id: (
                f"products__{mod_id}.db" if mod_id else name
            )
            ensure_sqlite_per_mod_database_copies([])


# ========================= get_db_path ===================================


class TestGetDbPath:
    def test_default_no_mod(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value=None),
        ):
            result = get_db_path("products.db")
            assert result == os.path.join(str(tmp_path), "products.db")

    def test_with_mod_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value="test_mod"),
            patch(
                "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
                return_value="products__test_mod.db",
            ),
        ):
            result = get_db_path("products.db")
            assert "products__test_mod.db" in result


# ========================= get_distillation_db_path ======================


class TestGetDistillationDbPath:
    def test_returns_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.request_active_mod_ctx.get_request_active_mod_id", return_value=None),
        ):
            result = get_distillation_db_path()
            assert "distillation.db" in result


# ========================= build_mod_database_seed_plan ==================


class TestBuildModDatabaseSeedPlan:
    @patch("app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix")
    @patch("app.infrastructure.mods.mod_manager.get_mod_manager")
    @patch("app.db.init_db.get_app_data_dir")
    def test_returns_structure(self, mock_dir, mock_mm, mock_suffix, tmp_path):
        mock_dir.return_value = str(tmp_path)
        mock_suffix.return_value = "products__test.db"
        mock_mm.return_value.list_loaded_mods.return_value = []
        mock_mm.return_value.scan_mods.return_value = []
        result = build_mod_database_seed_plan()
        assert "architecture_note_zh" in result
        assert "mods" in result
        assert isinstance(result["mods"], list)

    @patch("app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix")
    @patch("app.infrastructure.mods.mod_manager.get_mod_manager")
    @patch("app.db.init_db.get_app_data_dir")
    def test_with_mod_metadata(self, mock_dir, mock_mm, mock_suffix, tmp_path):
        mock_dir.return_value = str(tmp_path)
        mock_suffix.return_value = "products__test_mod.db"
        mock_meta = Mock()
        mock_meta.id = "test_mod"
        mock_meta.mod_path = str(tmp_path / "test_mod")
        os.makedirs(tmp_path / "test_mod", exist_ok=True)
        mock_mm.return_value.list_loaded_mods.return_value = [mock_meta]
        mock_mm.return_value.scan_mods.return_value = [mock_meta]
        result = build_mod_database_seed_plan()
        assert len(result["mods"]) == 1
        assert result["mods"][0]["mod_id"] == "test_mod"

    @patch("app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix")
    @patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        side_effect=RuntimeError("no manager"),
    )
    @patch("app.db.init_db.get_app_data_dir")
    def test_mod_manager_failure(self, mock_dir, mock_mm, mock_suffix, tmp_path):
        mock_dir.return_value = str(tmp_path)
        mock_suffix.return_value = "products__test.db"
        result = build_mod_database_seed_plan()
        assert result["mods"] == []
