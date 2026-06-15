"""测试 ensure_mod_postgres 模块的 Mod 分库创建。"""
import os
import pytest
from unittest.mock import MagicMock, patch

from app.db.ensure_mod_postgres import (
    _mod_isolated_enabled,
    _skip_mod_db_create,
    ensure_postgres_per_mod_databases,
)


# ---------------------------------------------------------------------------
# _mod_isolated_enabled
# ---------------------------------------------------------------------------

class TestModIsolatedEnabled:
    def test_enabled_with_1(self):
        with patch.dict(os.environ, {"XCAGI_MOD_ISOLATED_DATABASES": "1"}):
            assert _mod_isolated_enabled() is True

    def test_enabled_with_true(self):
        with patch.dict(os.environ, {"XCAGI_MOD_ISOLATED_DATABASES": "true"}):
            assert _mod_isolated_enabled() is True

    def test_enabled_with_yes(self):
        with patch.dict(os.environ, {"XCAGI_MOD_ISOLATED_DATABASES": "yes"}):
            assert _mod_isolated_enabled() is True

    def test_enabled_with_on(self):
        with patch.dict(os.environ, {"XCAGI_MOD_ISOLATED_DATABASES": "on"}):
            assert _mod_isolated_enabled() is True

    def test_disabled_with_0(self):
        with patch.dict(os.environ, {"XCAGI_MOD_ISOLATED_DATABASES": "0"}):
            assert _mod_isolated_enabled() is False

    def test_disabled_with_empty(self):
        with patch.dict(os.environ, {"XCAGI_MOD_ISOLATED_DATABASES": ""}, clear=False):
            os.environ.pop("XCAGI_MOD_ISOLATED_DATABASES", None)
            assert _mod_isolated_enabled() is False

    def test_disabled_with_random(self):
        with patch.dict(os.environ, {"XCAGI_MOD_ISOLATED_DATABASES": "maybe"}):
            assert _mod_isolated_enabled() is False


# ---------------------------------------------------------------------------
# _skip_mod_db_create
# ---------------------------------------------------------------------------

class TestSkipModDbCreate:
    def test_skip_with_1(self):
        with patch.dict(os.environ, {"FHD_SKIP_MOD_DB_CREATE": "1"}):
            assert _skip_mod_db_create() is True

    def test_skip_with_true(self):
        with patch.dict(os.environ, {"FHD_SKIP_MOD_DB_CREATE": "true"}):
            assert _skip_mod_db_create() is True

    def test_no_skip(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            assert _skip_mod_db_create() is False


# ---------------------------------------------------------------------------
# ensure_postgres_per_mod_databases
# ---------------------------------------------------------------------------

class TestEnsurePostgresPerModDatabases:
    def test_disabled_returns_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XCAGI_MOD_ISOLATED_DATABASES", None)
            result = ensure_postgres_per_mod_databases()
            assert result == []

    def test_skip_returns_empty(self):
        with patch.dict(os.environ, {
            "XCAGI_MOD_ISOLATED_DATABASES": "1",
            "FHD_SKIP_MOD_DB_CREATE": "1",
        }):
            result = ensure_postgres_per_mod_databases()
            assert result == []

    def test_non_postgres_returns_empty(self):
        with patch.dict(os.environ, {
            "XCAGI_MOD_ISOLATED_DATABASES": "1",
            "DATABASE_URL": "sqlite:///test.db",
        }, clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases()
            assert result == []

    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_no_mod_ids_returns_empty(self, mock_load):
        mock_boot = MagicMock()
        mock_boot._discover_mod_ids.return_value = []
        mock_load.return_value = mock_boot

        with patch.dict(os.environ, {
            "XCAGI_MOD_ISOLATED_DATABASES": "1",
            "DATABASE_URL": "postgresql://user:pass@localhost/xcagi",
        }, clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases()
            assert result == []

    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_base_db_missing_returns_empty(self, mock_load):
        mock_boot = MagicMock()
        mock_boot._discover_mod_ids.return_value = ["mod1"]
        mock_boot._normalize_mod_file_suffix.return_value = "mod1"
        mock_boot._db_exists.return_value = False  # base DB missing
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_boot._maintenance_engine.return_value = mock_engine
        mock_load.return_value = mock_boot

        with patch.dict(os.environ, {
            "XCAGI_MOD_ISOLATED_DATABASES": "1",
            "DATABASE_URL": "postgresql://user:pass@localhost/xcagi",
        }, clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases()
            assert result == []

    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_existing_dbs_not_recreated(self, mock_load):
        mock_boot = MagicMock()
        mock_boot._discover_mod_ids.return_value = ["mod1"]
        mock_boot._normalize_mod_file_suffix.return_value = "mod1"
        # base DB exists, mod DB also exists
        mock_boot._db_exists.side_effect = lambda conn, dbn: True
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.dispose = MagicMock()
        mock_boot._maintenance_engine.return_value = mock_engine
        mock_load.return_value = mock_boot

        with patch.dict(os.environ, {
            "XCAGI_MOD_ISOLATED_DATABASES": "1",
            "DATABASE_URL": "postgresql://user:pass@localhost/xcagi",
        }, clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases()
            assert result == []

    @patch("app.db.ensure_mod_postgres._migrate_mod_databases")
    @patch("app.db.ensure_mod_postgres._load_bootstrap_module")
    def test_creates_new_db(self, mock_load, mock_migrate):
        mock_boot = MagicMock()
        mock_boot._discover_mod_ids.return_value = ["mod1"]
        mock_boot._normalize_mod_file_suffix.return_value = "mod1"
        mock_boot.DEFAULT_CLONE_FROM_BASE_MOD_IDS = ()

        # base DB exists, mod DB does not
        call_count = [0]
        def db_exists_side_effect(conn, dbn):
            call_count[0] += 1
            return dbn == "xcagi"  # base exists, mod doesn't

        mock_boot._db_exists.side_effect = db_exists_side_effect
        mock_boot._create_db_empty = MagicMock()
        mock_boot._url_for_database.return_value = "postgresql://user:pass@localhost/xcagi__mod1"
        mock_boot._enable_pgvector = MagicMock()

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.dispose = MagicMock()
        mock_boot._maintenance_engine.return_value = mock_engine
        mock_load.return_value = mock_boot

        with patch.dict(os.environ, {
            "XCAGI_MOD_ISOLATED_DATABASES": "1",
            "DATABASE_URL": "postgresql://user:pass@localhost/xcagi",
        }, clear=False):
            os.environ.pop("FHD_SKIP_MOD_DB_CREATE", None)
            result = ensure_postgres_per_mod_databases()
            assert "xcagi__mod1" in result
