"""Tests for app.db.init_db — additional coverage for remaining branches.

Focus: ensure_postgresql_auth_bootstrap, ensure_sessions_market_access_token_column,
ensure_sessions_market_refresh_token_column, ensure_sessions_enterprise_entitlement_columns,
ensure_sessions_account_meta_columns, init_im_tables, init_approval_tables,
ensure_product_query_indexes, init_service_bridge_tables, ensure_runtime_auth_bootstrap,
ensure_user_preferences_bootstrap, _seed_sqlite_rbac_defaults, _iter_seed_dirs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Use MagicMock for all mocks to support context manager protocol
Mock = MagicMock  # type: ignore[assignment,misc]  # noqa: F811

import pytest
from sqlalchemy import create_engine, text

# ========================= _iter_seed_dirs - deep =========================


class TestIterSeedDirsDeep:
    def test_yields_resource_and_base(self):
        from app.db.init_db import _iter_seed_dirs

        with (
            patch("app.db.init_db.get_resource_path", return_value="/r/db_seed"),
            patch("app.db.init_db.get_base_dir", return_value="/base"),
        ):
            result = list(_iter_seed_dirs())
        assert "/r/db_seed" in result
        assert "/base" in result

    def test_includes_meipass_when_present(self):
        from app.db.init_db import _iter_seed_dirs

        fake_meipass = "/tmp/meipass"
        with (
            patch("app.db.init_db.get_resource_path", return_value="/r/db_seed"),
            patch("app.db.init_db.get_base_dir", return_value="/base"),
            patch.object(
                sys, "_MEIPASS", fake_ipass if (fake_ipass := fake_meipass) else None, create=True
            ),
        ):
            result = list(_iter_seed_dirs())
        assert fake_meipass in result

    def test_no_meipass_attribute(self):
        from app.db.init_db import _iter_seed_dirs

        # Ensure _MEIPASS is not present
        original = getattr(sys, "_MEIPASS", None)
        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS
        try:
            with (
                patch("app.db.init_db.get_resource_path", return_value="/r/db_seed"),
                patch("app.db.init_db.get_base_dir", return_value="/base"),
            ):
                result = list(_iter_seed_dirs())
            assert len(result) == 2
        finally:
            if original is not None:
                sys._MEIPASS = original


# ========================= ensure_postgresql_auth_bootstrap - deep =========


class TestEnsurePostgresqlAuthBootstrapDeep:
    def test_non_postgresql_skipped(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine):
            ensure_postgresql_auth_bootstrap(None)
        # Non-postgresql dialect -> early return, no DDL (begin) executed
        mock_engine.begin.assert_not_called()

    def test_none_engine_skipped(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=None),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            ensure_postgresql_auth_bootstrap(None)
        # No engine resolved -> early return before any seeding work
        mock_seed.assert_not_called()

    def test_creates_users_table_when_missing(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        # First inspect: no tables; Second inspect: users exists (created)
        mock_insp_1 = Mock()
        mock_insp_1.get_table_names.return_value = []
        mock_insp_2 = Mock()
        mock_insp_2.get_table_names.return_value = ["users"]

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[mock_insp_1, mock_insp_2]),
            patch("app.db.init_db._seed_default_admin_user"),
        ):
            ensure_postgresql_auth_bootstrap(mock_engine)
            # users table created (1 begin call); sessions also created (1 begin call)
            assert mock_engine.begin.call_count >= 2

    def test_creates_sessions_table_when_users_exists(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"

        # First inspect returns users, second returns users + sessions
        mock_insp_1 = Mock()
        mock_insp_1.get_table_names.return_value = ["users"]
        mock_insp_2 = Mock()
        mock_insp_2.get_table_names.return_value = ["users"]

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[mock_insp_1, mock_insp_2]),
            patch("app.db.init_db._seed_default_admin_user"),
        ):
            ensure_postgresql_auth_bootstrap(mock_engine)
        # users already present (no users DDL), sessions missing -> exactly one
        # begin() for the CREATE TABLE sessions
        mock_engine.begin.assert_called_once()

    def test_sessions_skipped_when_users_still_missing(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"

        mock_insp_1 = Mock()
        mock_insp_1.get_table_names.return_value = []
        mock_insp_2 = Mock()
        mock_insp_2.get_table_names.return_value = []  # users still missing

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[mock_insp_1, mock_insp_2]),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            ensure_postgresql_auth_bootstrap(mock_engine)
        # users missing -> one begin() to create users; re-inspect still shows
        # users missing -> sessions creation skipped (no second begin) and the
        # function returns before seeding the admin user
        mock_engine.begin.assert_called_once()
        mock_seed.assert_not_called()

    def test_handles_recoverable_errors(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            # inspect() raises a RECOVERABLE_ERRORS member -> swallowed, no raise
            ensure_postgresql_auth_bootstrap(mock_engine)
        # error hit before any DDL or seeding ran
        mock_engine.begin.assert_not_called()
        mock_seed.assert_not_called()


# ========================= ensure_sessions_market_access_token_column - deep


class TestEnsureSessionsMarketAccessTokenColumnDeep:
    def test_no_engine_no_url_returns(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        with (
            patch("app.db._create_engine_for_url", side_effect=RuntimeError("no url")),
            patch("app.db._get_engine", side_effect=ImportError("no engine")) as mock_get,
        ):
            # No url and no engine -> falls back to _get_engine which raises a
            # RECOVERABLE_ERRORS member -> function returns without raising
            result = ensure_sessions_market_access_token_column(None, database_url=None)
        assert result is None
        # confirms we actually reached the _get_engine fallback (not short-circuited)
        mock_get.assert_called_once()

    def test_column_already_exists(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = ["sessions"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "session_id"},
            {"name": "market_access_token"},  # already exists
        ]

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ensure_sessions_market_access_token_column(None, database_url="sqlite:///test.db")
            # Should not call begin() since column exists
            mock_engine.begin.assert_not_called()

    def test_sessions_table_missing(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = []  # no sessions table

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ensure_sessions_market_access_token_column(None, database_url="sqlite:///test.db")
            mock_engine.begin.assert_not_called()

    def test_adds_column_postgresql(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        # First inspect (add): column missing; Second inspect (verify): column present
        mock_insp_1 = Mock()
        mock_insp_1.get_table_names.return_value = ["sessions"]
        mock_insp_1.get_columns.return_value = [{"name": "id"}, {"name": "session_id"}]
        mock_insp_2 = Mock()
        mock_insp_2.get_table_names.return_value = ["sessions"]
        mock_insp_2.get_columns.return_value = [
            {"name": "id"},
            {"name": "session_id"},
            {"name": "market_access_token"},
        ]

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[mock_insp_1, mock_insp_2]),
        ):
            ensure_sessions_market_access_token_column(None, database_url="postgresql://test")
            mock_engine.begin.assert_called()

    def test_adds_column_sqlite(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        # First inspect (add): column missing; Second inspect (verify): column present
        mock_insp_1 = Mock()
        mock_insp_1.get_table_names.return_value = ["sessions"]
        mock_insp_1.get_columns.return_value = [{"name": "id"}]
        mock_insp_2 = Mock()
        mock_insp_2.get_table_names.return_value = ["sessions"]
        mock_insp_2.get_columns.return_value = [
            {"name": "id"},
            {"name": "market_access_token"},
        ]

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[mock_insp_1, mock_insp_2]),
        ):
            ensure_sessions_market_access_token_column(None, database_url="sqlite:///test.db")
            mock_engine.begin.assert_called()

    def test_verify_raises_when_column_still_missing(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        # First inspect for add: column missing, second for verify: still missing
        mock_insp_1 = Mock()
        mock_insp_1.get_table_names.return_value = ["sessions"]
        mock_insp_1.get_columns.return_value = [{"name": "id"}]
        mock_insp_2 = Mock()
        mock_insp_2.get_table_names.return_value = ["sessions"]
        mock_insp_2.get_columns.return_value = [{"name": "id"}]  # still missing

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[mock_insp_1, mock_insp_2]),
        ):
            with pytest.raises(RuntimeError, match="缺少 market_access_token"):
                ensure_sessions_market_access_token_column(None, database_url="sqlite:///test.db")

    def test_verify_skips_when_sessions_missing(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp_1 = Mock()
        mock_insp_1.get_table_names.return_value = ["sessions"]
        mock_insp_1.get_columns.return_value = [{"name": "id"}]
        mock_insp_2 = Mock()
        mock_insp_2.get_table_names.return_value = []  # sessions gone

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[mock_insp_1, mock_insp_2]),
        ):
            # add step runs (column missing); verify step sees sessions table gone
            # and returns instead of raising the "缺少 market_access_token" error
            ensure_sessions_market_access_token_column(None, database_url="sqlite:///test.db")
        # exactly one begin() for the ALTER; verify step does no further DDL
        mock_engine.begin.assert_called_once()

    def test_engine_from_explicit_param(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = ["sessions"]
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "market_access_token"}]

        with patch("sqlalchemy.inspect", return_value=mock_insp):
            ensure_sessions_market_access_token_column(mock_engine, database_url=None)
        # explicit engine used directly; column already present -> no ALTER (begin)
        mock_engine.begin.assert_not_called()

    def test_add_column_failure_logs(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_engine.begin.side_effect = RuntimeError("begin failed")
        # First inspect (add): column missing; Second inspect (verify): column present
        # so verify step doesn't raise RuntimeError
        mock_insp_1 = Mock()
        mock_insp_1.get_table_names.return_value = ["sessions"]
        mock_insp_1.get_columns.return_value = [{"name": "id"}]
        mock_insp_2 = Mock()
        mock_insp_2.get_table_names.return_value = ["sessions"]
        mock_insp_2.get_columns.return_value = [
            {"name": "id"},
            {"name": "market_access_token"},
        ]

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[mock_insp_1, mock_insp_2]),
        ):
            # ALTER (begin) raises a RECOVERABLE_ERRORS member -> swallowed/logged;
            # verify step then sees the column present -> no RuntimeError raised
            ensure_sessions_market_access_token_column(None, database_url="sqlite:///test.db")
        # the add path was actually entered (begin attempted) before the error was swallowed
        mock_engine.begin.assert_called_once()


# ========================= ensure_sessions_market_refresh_token_column ====


class TestEnsureSessionsMarketRefreshTokenColumnDeep:
    def test_column_already_exists(self):
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = ["sessions"]
        mock_insp.get_columns.return_value = [{"name": "market_refresh_token"}]

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ensure_sessions_market_refresh_token_column(None, database_url="sqlite:///test.db")
            mock_engine.begin.assert_not_called()

    def test_adds_column(self):
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = ["sessions"]
        mock_insp.get_columns.return_value = [{"name": "id"}]

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ensure_sessions_market_refresh_token_column(None, database_url="postgresql://test")
            mock_engine.begin.assert_called()

    def test_no_engine_returns(self):
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        with (
            patch("app.db._create_engine_for_url", side_effect=RuntimeError("no url")),
            patch("app.db._get_engine", side_effect=ImportError("no engine")) as mock_get,
        ):
            # No url and no engine -> _get_engine fallback raises a recoverable
            # error -> function returns without raising
            result = ensure_sessions_market_refresh_token_column(None, database_url=None)
        assert result is None
        mock_get.assert_called_once()


# ========================= ensure_sessions_enterprise_entitlement_columns ==


class TestEnsureSessionsEnterpriseEntitlementColumnsDeep:
    def test_both_columns_missing(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = ["sessions"]
        mock_insp.get_columns.return_value = [{"name": "id"}]

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ensure_sessions_enterprise_entitlement_columns(None, database_url="postgresql://test")
            mock_engine.begin.assert_called_once()

    def test_one_column_present(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = ["sessions"]
        mock_insp.get_columns.return_value = [{"name": "id"}, {"name": "market_user_id"}]

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ensure_sessions_enterprise_entitlement_columns(None, database_url="sqlite:///test.db")
            mock_engine.begin.assert_called_once()

    def test_no_sessions_table(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = []

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ensure_sessions_enterprise_entitlement_columns(None, database_url="sqlite:///test.db")
            mock_engine.begin.assert_not_called()


# ========================= ensure_sessions_account_meta_columns ============


class TestEnsureSessionsAccountMetaColumnsDeep:
    def test_adds_missing_columns_postgresql(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = ["sessions"]
        mock_insp.get_columns.return_value = [{"name": "id"}]

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ensure_sessions_account_meta_columns(None, database_url="postgresql://test")
            mock_engine.begin.assert_called_once()

    def test_all_columns_present(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = ["sessions"]
        mock_insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "account_kind"},
            {"name": "company_brand"},
            {"name": "market_is_admin"},
            {"name": "market_is_enterprise"},
            {"name": "impersonating_market_user_id"},
            {"name": "impersonating_username"},
            {"name": "tenant_id"},
            {"name": "market_membership_tier"},
        ]

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ensure_sessions_account_meta_columns(None, database_url="sqlite:///test.db")
            # begin() is called (the with block is entered) but no ALTER TABLE executes
            # because all columns are present (the `continue` skips them)
            mock_engine.begin.assert_called_once()
            # Verify no execute calls were made on the connection
            conn = mock_engine.begin.return_value.__enter__.return_value
            conn.execute.assert_not_called()

    def test_no_sessions_table(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = []

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
        ):
            ensure_sessions_account_meta_columns(None, database_url="sqlite:///test.db")
            mock_engine.begin.assert_not_called()


# ========================= ensure_user_preferences_bootstrap ==============


class TestEnsureUserPreferencesBootstrapDeep:
    def test_non_sqlite_skipped(self):
        # NOTE: ensure_user_preferences_bootstrap has NO dialect gate (unlike
        # ensure_sqlite_*). With a non-None engine and the table missing it
        # creates user_preferences regardless of dialect. Assert that real
        # behavior: create_all IS invoked (would fail if a skip were added).
        from app.db.init_db import ensure_user_preferences_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = []
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_user_preferences_bootstrap(None)
        mock_create.assert_called_once()

    def test_none_engine_skipped(self):
        from app.db.init_db import ensure_user_preferences_bootstrap

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=None),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_user_preferences_bootstrap(None)
        # No engine resolved -> early return before any table creation
        mock_create.assert_not_called()

    def test_creates_table_when_missing(self):
        from app.db.init_db import ensure_user_preferences_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = []

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_user_preferences_bootstrap(mock_engine)
        # table absent -> create_all invoked for UserPreference table
        mock_create.assert_called_once()

    def test_table_already_exists(self):
        from app.db.init_db import ensure_user_preferences_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_insp = Mock()
        mock_insp.get_table_names.return_value = ["user_preferences"]

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=mock_insp),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_user_preferences_bootstrap(mock_engine)
        # table already present -> no create_all
        mock_create.assert_not_called()

    def test_swallow_errors_true(self):
        from app.db.init_db import ensure_user_preferences_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            # inspect() raises a RECOVERABLE_ERRORS member -> swallowed, no raise
            ensure_user_preferences_bootstrap(None, swallow_errors=True)
        # error happened before reaching create_all
        mock_create.assert_not_called()

    def test_swallow_errors_false(self):
        from app.db.init_db import ensure_user_preferences_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
        ):
            with pytest.raises(RuntimeError, match="inspect failed"):
                ensure_user_preferences_bootstrap(None, swallow_errors=False)


# ========================= ensure_runtime_auth_bootstrap =================


class TestEnsureRuntimeAuthBootstrapDeep:
    def test_empty_url_returns(self):
        from app.db.init_db import ensure_runtime_auth_bootstrap

        with (
            patch("app.fastapi_app.sqlite_paths.resolve_effective_database_url", return_value=""),
            patch("app.db.init_db.ensure_sqlite_auth_bootstrap") as mock_sqlite,
            patch("app.db.init_db.ensure_postgresql_auth_bootstrap") as mock_pg,
        ):
            ensure_runtime_auth_bootstrap(None)
        # empty resolved url -> early return, neither dialect branch runs
        mock_sqlite.assert_not_called()
        mock_pg.assert_not_called()

    def test_sqlite_url_calls_sqlite_bootstraps(self):
        from app.db.init_db import ensure_runtime_auth_bootstrap

        with (
            patch(
                "app.fastapi_app.sqlite_paths.resolve_effective_database_url",
                return_value="sqlite:///test.db",
            ),
            patch("app.fastapi_app.sqlite_paths.is_sqlite_url", return_value=True),
            patch("app.db.init_db.ensure_sqlite_auth_bootstrap") as mock_auth,
            patch("app.db.init_db.ensure_sqlite_rbac_bootstrap") as mock_rbac,
            patch("app.db.init_db.ensure_sqlite_inventory_bootstrap") as mock_inv,
            patch("app.db.init_db.ensure_user_preferences_bootstrap") as mock_pref,
        ):
            ensure_runtime_auth_bootstrap(None)
            mock_auth.assert_called_once()
            mock_rbac.assert_called_once()
            mock_inv.assert_called_once()
            mock_pref.assert_called_once()

    def test_postgresql_url_calls_pg_bootstrap(self):
        from app.db.init_db import ensure_runtime_auth_bootstrap

        # The postgres branch fans out to three helpers (see init_db.py
        # ensure_runtime_auth_bootstrap else-branch): ensure_postgresql_auth_bootstrap
        # + ensure_user_preferences_bootstrap + ensure_neuro_event_log_bootstrap.
        # Mock ALL of them so no real PostgreSQL connection (port 5432) is attempted
        # on machines without a local PG — previously ensure_neuro_event_log_bootstrap
        # was left unpatched and tried to connect, failing only off-CI.
        with (
            patch(
                "app.fastapi_app.sqlite_paths.resolve_effective_database_url",
                return_value="postgresql://test",
            ),
            patch("app.fastapi_app.sqlite_paths.is_sqlite_url", return_value=False),
            patch("app.db.init_db.ensure_postgresql_auth_bootstrap") as mock_pg,
            patch("app.db.init_db.ensure_user_preferences_bootstrap") as mock_pref,
            patch("app.db.init_db.ensure_neuro_event_log_bootstrap") as mock_neuro,
        ):
            ensure_runtime_auth_bootstrap(None)
            mock_pg.assert_called_once()
            mock_pref.assert_called_once()
            mock_neuro.assert_called_once()


# ========================= _seed_sqlite_rbac_defaults ====================


class TestSeedSqliteRbacDefaultsDeep:
    def test_existing_permissions_skips(self):
        from app.db.init_db import _seed_sqlite_rbac_defaults

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE permissions (id INTEGER PRIMARY KEY, name TEXT, code TEXT, description TEXT, module TEXT)"
                )
            )
            conn.execute(text("INSERT INTO permissions (name, code) VALUES ('test', 'test')"))

        with patch("app.db.models.permission.DEFAULT_PERMISSIONS", []):
            _seed_sqlite_rbac_defaults(engine)

        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM permissions")).scalar()
        assert count == 1


# ========================= init_im_tables ================================


class TestInitImTablesDeep:
    def test_creates_tables(self):
        from app.db.init_db import init_im_tables

        engine = create_engine("sqlite:///:memory:")
        init_im_tables(engine)

        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = {row[0] for row in result}
        assert "im_conversations" in tables
        assert "im_conversation_members" in tables
        assert "im_messages" in tables

    def test_idempotent(self):
        from app.db.init_db import init_im_tables

        engine = create_engine("sqlite:///:memory:")
        init_im_tables(engine)
        init_im_tables(engine)  # second call must not raise (checkfirst=True)

        # tables remain present and intact after the repeated call
        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = {row[0] for row in result}
        assert "im_conversations" in tables
        assert "im_conversation_members" in tables
        assert "im_messages" in tables


# ========================= init_approval_tables ==========================


class TestInitApprovalTablesDeep:
    def test_creates_tables(self):
        from app.db.init_db import init_approval_tables

        engine = create_engine("sqlite:///:memory:")
        with patch("app.db._get_engine", return_value=engine):
            init_approval_tables(engine)

        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = {row[0] for row in result}
        assert "approval_flows" in tables
        assert "approval_requests" in tables

    def test_adds_business_type_column_when_missing(self):
        from app.db.init_db import init_approval_tables

        engine = create_engine("sqlite:///:memory:")
        # Create approval_flows without business_type
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE approval_flows (id INTEGER PRIMARY KEY, name TEXT)"))

        with patch("app.db._get_engine", return_value=engine):
            init_approval_tables(engine)

        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(approval_flows)"))
            cols = {row[1] for row in result}
        assert "business_type" in cols


# ========================= ensure_product_query_indexes ===================


class TestEnsureProductQueryIndexesDeep:
    def test_no_products_table_skips(self):
        from app.db.init_db import ensure_product_query_indexes

        engine = create_engine("sqlite:///:memory:")
        # No products table -> function returns early, creates no indexes
        ensure_product_query_indexes(engine)

        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
            indexes = {row[0] for row in result}
        assert "ix_products_unit" not in indexes
        assert "ix_products_model_number" not in indexes

    def test_creates_indexes(self):
        from app.db.init_db import ensure_product_query_indexes

        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE products (id INTEGER PRIMARY KEY, unit TEXT, model_number TEXT)")
            )

        ensure_product_query_indexes(engine)

        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
            indexes = {row[0] for row in result}
        assert "ix_products_unit" in indexes
        assert "ix_products_model_number" in indexes


# ========================= init_service_bridge_tables ====================


class TestInitServiceBridgeTablesDeep:
    def test_creates_tables(self):
        from app.db.init_db import init_service_bridge_tables

        engine = create_engine("sqlite:///:memory:")
        with patch("app.db._get_engine", return_value=engine):
            init_service_bridge_tables(engine)

        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = {row[0] for row in result}
        assert "service_requests" in tables
        assert "service_bridge_config" in tables


# ========================= _resolve_auth_bootstrap_engine edge cases =====


class TestResolveAuthBootstrapEngineEdgeCases:
    def test_url_provided_engine_is_not_real_engine(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        # When database_url is provided but _create_engine_for_url fails,
        # and engine param is not a real Engine, should fall through to _get_engine
        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db._create_engine_for_url", side_effect=RuntimeError("bad url")),
            patch("app.db._get_engine", return_value=mock_engine),
        ):
            result = _resolve_auth_bootstrap_engine("not_an_engine", database_url="bad://url")
        assert result is mock_engine

    def test_url_provided_engine_is_real_engine(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        real_engine = create_engine("sqlite:///:memory:")
        with (
            patch("app.db._create_engine_for_url", side_effect=RuntimeError("bad url")),
        ):
            result = _resolve_auth_bootstrap_engine(real_engine, database_url="bad://url")
        assert result is real_engine


# ========================= build_mod_database_seed_plan edge cases ========


class TestBuildModDatabaseSeedPlanEdgeCases:
    def test_mod_with_seed_files(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

        mock_meta = Mock()
        mock_meta.id = "test_mod"
        mock_meta.mod_path = str(tmp_path / "test_mod")

        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        # Create a seed file
        seed_file = mod_dir / "seed.sql"
        seed_file.write_text("-- seed sql")
        manifest = {
            "id": "test_mod",
            "database": {
                "notes_zh": "测试库",
                "seed_files": ["data.db"],
                "seed_sql": "seed.sql",
            },
        }
        (mod_dir / "manifest.json").write_text(json.dumps(manifest))
        (mod_dir / "data.db").write_bytes(b"")

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch(
                "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
                side_effect=lambda n, m: f"products__{m}.db",
            ),
        ):
            mock_mm.return_value.list_loaded_mods.return_value = [mock_meta]
            result = build_mod_database_seed_plan()
        assert len(result["mods"]) == 1
        seeds = result["mods"][0]["seeds"]
        # Should have mother, per_mod, and extra seeds
        assert len(seeds) >= 2

    def test_mod_with_invalid_manifest(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

        mock_meta = Mock()
        mock_meta.id = "test_mod"
        mock_meta.mod_path = str(tmp_path / "test_mod")

        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("not valid json{{")

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch(
                "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
                side_effect=lambda n, m: f"products__{m}.db",
            ),
        ):
            mock_mm.return_value.list_loaded_mods.return_value = [mock_meta]
            result = build_mod_database_seed_plan()
        assert len(result["mods"]) == 1

    def test_mod_with_empty_id_skipped(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

        mock_meta = Mock()
        mock_meta.id = ""
        mock_meta.mod_path = ""

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch(
                "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
                side_effect=lambda n, m: f"products__{m}.db",
            ),
        ):
            mock_mm.return_value.list_loaded_mods.return_value = [mock_meta]
            result = build_mod_database_seed_plan()
        assert len(result["mods"]) == 0

    def test_mod_with_database_seed_files_as_non_list(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

        mock_meta = Mock()
        mock_meta.id = "test_mod"
        mock_meta.mod_path = str(tmp_path / "test_mod")

        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        manifest = {
            "id": "test_mod",
            "database": {
                "seed_files": "not_a_list",  # invalid type
            },
        }
        (mod_dir / "manifest.json").write_text(json.dumps(manifest))

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch(
                "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
                side_effect=lambda n, m: f"products__{m}.db",
            ),
        ):
            mock_mm.return_value.list_loaded_mods.return_value = [mock_meta]
            result = build_mod_database_seed_plan()
        assert len(result["mods"]) == 1

    def test_top_level_database_seed_files(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

        mock_meta = Mock()
        mock_meta.id = "test_mod"
        mock_meta.mod_path = str(tmp_path / "test_mod")

        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        manifest = {
            "id": "test_mod",
            "database_seed_files": ["data.db"],
            "database_notes_zh": "top level notes",
        }
        (mod_dir / "manifest.json").write_text(json.dumps(manifest))
        (mod_dir / "data.db").write_bytes(b"")

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch(
                "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
                side_effect=lambda n, m: f"products__{m}.db",
            ),
        ):
            mock_mm.return_value.list_loaded_mods.return_value = [mock_meta]
            result = build_mod_database_seed_plan()
        assert len(result["mods"]) == 1
        assert result["mods"][0]["database_notes"] == "top level notes"


# ========================= ensure_sqlite_rbac_bootstrap deep =============


class TestEnsureSqliteRbacBootstrapCreatesTables:
    def test_creates_tables_when_missing(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        engine = create_engine("sqlite:///:memory:")
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=engine),
            patch("app.db.init_db._seed_sqlite_rbac_defaults"),
        ):
            ensure_sqlite_rbac_bootstrap(engine)

        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = {row[0] for row in result}
        assert "permissions" in tables
        assert "roles" in tables

    def test_swallow_errors_true(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
            patch("app.db.init_db._seed_sqlite_rbac_defaults") as mock_seed,
        ):
            # inspect() raises a RECOVERABLE_ERRORS member -> swallowed, no raise
            ensure_sqlite_rbac_bootstrap(None, swallow_errors=True)
        # error hit during inspect, before the RBAC seeding step
        mock_seed.assert_not_called()

    def test_swallow_errors_false(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
        ):
            with pytest.raises(RuntimeError, match="inspect failed"):
                ensure_sqlite_rbac_bootstrap(None, swallow_errors=False)


# ========================= ensure_sqlite_inventory_bootstrap deep ========


class TestEnsureSqliteInventoryBootstrapCreatesTables:
    def test_creates_tables_when_missing(self):
        from app.db.init_db import ensure_sqlite_inventory_bootstrap

        engine = create_engine("sqlite:///:memory:")
        with patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=engine):
            ensure_sqlite_inventory_bootstrap(engine)

        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = {row[0] for row in result}
        assert "warehouses" in tables

    def test_swallow_errors_true(self):
        from app.db.init_db import ensure_sqlite_inventory_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            # inspect() raises a RECOVERABLE_ERRORS member -> swallowed, no raise
            ensure_sqlite_inventory_bootstrap(None, swallow_errors=True)
        # error hit during inspect, before any table creation
        mock_create.assert_not_called()

    def test_swallow_errors_false(self):
        from app.db.init_db import ensure_sqlite_inventory_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
        ):
            with pytest.raises(RuntimeError, match="inspect failed"):
                ensure_sqlite_inventory_bootstrap(None, swallow_errors=False)


# ========================= ensure_sqlite_auth_bootstrap creates ===========


class TestEnsureSqliteAuthBootstrapCreatesTables:
    def test_tables_already_exist(self):
        from app.db.init_db import ensure_sqlite_auth_bootstrap

        engine = create_engine("sqlite:///:memory:")
        # Pre-create users and sessions tables
        from app.db.base import Base
        from app.db.models.user import Session, User

        Base.metadata.create_all(
            engine, tables=[User.__table__, Session.__table__], checkfirst=True
        )

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=engine),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            ensure_sqlite_auth_bootstrap(engine)

        # tables were already present (no recreate error) and the seed step was
        # still reached
        mock_seed.assert_called_once()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = {row[0] for row in result}
        assert "users" in tables
        assert "sessions" in tables
