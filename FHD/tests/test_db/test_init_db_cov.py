"""Branch-coverage tests for app.db.init_db.

Mocks all SQLAlchemy / DB / filesystem deps — never connects to a real DB.
Targets missing branches from coverage_new.json.

Key insight: init_db functions use `from app.db import _create_engine_for_url` /
`from app.db import _get_engine` inside their bodies. We must patch
`app.db._create_engine_for_url` (the attribute on the app.db module), not
`app.db.init_db._create_engine_for_url` which does not exist at module scope.
"""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# pre-import so patch.object can refer to the module object
import app.db as _app_db_module

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_mock_engine(dialect_name: str = "sqlite") -> MagicMock:
    """Build a fully-featured mock SQLAlchemy engine."""
    eng = MagicMock()
    eng.dialect.name = dialect_name
    conn_ctx = MagicMock()
    conn_mock = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_mock)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    eng.begin.return_value = conn_ctx
    return eng


@contextmanager
def _patch_engine(eng: MagicMock):
    """Patch both the create-engine and get-engine callables inside app.db."""
    with (
        patch.object(_app_db_module, "_create_engine_for_url", return_value=eng, create=True),
        patch.object(_app_db_module, "_get_engine", return_value=eng, create=True),
    ):
        yield eng


def _make_inspector(tables: list[str], col_map: dict[str, list[str]] | None = None) -> MagicMock:
    insp = MagicMock()
    insp.get_table_names.return_value = tables
    col_map = col_map or {}

    def _get_cols(tbl):
        return [{"name": c} for c in col_map.get(tbl, [])]

    insp.get_columns.side_effect = _get_cols
    return insp


# ---------------------------------------------------------------------------
# refresh_config_database_urls
# ---------------------------------------------------------------------------


class TestRefreshConfigDatabaseUrls:
    def test_noop_when_none(self):
        from app.db.init_db import refresh_config_database_urls

        refresh_config_database_urls(None)  # must not raise

    def test_sets_database_url_from_env(self):
        from app.db.init_db import refresh_config_database_urls

        class FakeConfig:
            DATABASE_URL = ""
            VECTOR_DB_URL = ""
            DATABASE_PATH = ""

        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///foo.db"}):
            refresh_config_database_urls(FakeConfig)
        assert FakeConfig.DATABASE_URL == "sqlite:///foo.db"

    def test_skips_env_when_not_set(self):
        from app.db.init_db import refresh_config_database_urls

        class FakeConfig:
            DATABASE_URL = "existing"

        with patch.dict(os.environ, {}, clear=True):
            # Remove DATABASE_URL if present
            os.environ.pop("DATABASE_URL", None)
            refresh_config_database_urls(FakeConfig)
        assert FakeConfig.DATABASE_URL == "existing"


# ---------------------------------------------------------------------------
# ensure_runtime_database_environment
# ---------------------------------------------------------------------------


class TestEnsureRuntimeDatabaseEnvironment:
    def test_non_desktop_returns_env_url(self):
        from app.db.init_db import ensure_runtime_database_environment

        with patch.dict(os.environ, {"XCAGI_DESKTOP_MODE": "", "DATABASE_URL": "postgresql://x"}):
            url = ensure_runtime_database_environment()
        assert url == "postgresql://x"

    def test_desktop_mode_sets_sqlite_url(self, tmp_path):
        from app.db.init_db import ensure_runtime_database_environment

        with (
            patch.dict(os.environ, {"XCAGI_DESKTOP_MODE": "1"}, clear=False),
            patch("app.db.init_db._desktop_data_root", return_value=tmp_path),
            patch("app.db.init_db.ensure_desktop_sqlite_business_tables_all_files"),
        ):
            url = ensure_runtime_database_environment()
        assert url.startswith("sqlite:///")

    def test_desktop_mode_truthy_values(self, tmp_path):
        from app.db.init_db import ensure_runtime_database_environment

        for val in ("1", "true", "yes", "on"):
            with (
                patch.dict(os.environ, {"XCAGI_DESKTOP_MODE": val}, clear=False),
                patch("app.db.init_db._desktop_data_root", return_value=tmp_path),
                patch("app.db.init_db.ensure_desktop_sqlite_business_tables_all_files"),
            ):
                url = ensure_runtime_database_environment()
            assert "sqlite" in url, f"failed for XCAGI_DESKTOP_MODE={val!r}"


# ---------------------------------------------------------------------------
# _resolve_auth_bootstrap_engine
# ---------------------------------------------------------------------------


class TestResolveAuthBootstrapEngine:
    def test_returns_none_when_all_fail(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        with (
            patch.object(
                _app_db_module, "_create_engine_for_url", side_effect=ImportError, create=True
            ),
            patch.object(_app_db_module, "_get_engine", side_effect=RuntimeError, create=True),
        ):
            result = _resolve_auth_bootstrap_engine()
        assert result is None

    def test_uses_database_url_arg(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        eng = _make_mock_engine()
        with patch.object(_app_db_module, "_create_engine_for_url", return_value=eng, create=True):
            result = _resolve_auth_bootstrap_engine(database_url="sqlite:///x")
        assert result is eng

    def test_uses_provided_engine_directly(self):
        from sqlalchemy import create_engine

        from app.db.init_db import _resolve_auth_bootstrap_engine

        # Need a real Engine object so isinstance(engine, _Engine) check passes
        real_eng = create_engine("sqlite:///:memory:")
        result = _resolve_auth_bootstrap_engine(engine=real_eng)
        assert result is real_eng

    def test_falls_back_to_get_engine(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        eng = _make_mock_engine()
        with (
            patch.object(
                _app_db_module, "_create_engine_for_url", side_effect=Exception, create=True
            ),
            patch.object(_app_db_module, "_get_engine", return_value=eng, create=True),
        ):
            result = _resolve_auth_bootstrap_engine()
        assert result is eng


# ---------------------------------------------------------------------------
# ensure_sqlite_rbac_bootstrap
# ---------------------------------------------------------------------------


class TestEnsureSqliteRbacBootstrap:
    def test_skips_non_sqlite_engine(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        eng = _make_mock_engine("postgresql")
        with patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng):
            ensure_sqlite_rbac_bootstrap(engine=eng)  # should return early

    def test_skips_when_engine_none(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        with patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=None):
            ensure_sqlite_rbac_bootstrap()  # must not raise

    def test_swallows_errors_when_flag_true(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        eng = _make_mock_engine("sqlite")
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("app.db.init_db._seed_sqlite_rbac_defaults", side_effect=RuntimeError("boom")),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["permissions", "roles", "role_permissions"]),
            ),
        ):
            ensure_sqlite_rbac_bootstrap(engine=eng, swallow_errors=True)  # must not raise

    def test_raises_when_flag_false(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        eng = _make_mock_engine("sqlite")
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("app.db.init_db._seed_sqlite_rbac_defaults", side_effect=RuntimeError("boom")),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["permissions", "roles", "role_permissions"]),
            ),
        ):
            with pytest.raises(RuntimeError):
                ensure_sqlite_rbac_bootstrap(engine=eng, swallow_errors=False)


# ---------------------------------------------------------------------------
# ensure_sessions_market_access_token_column
# ---------------------------------------------------------------------------


class TestEnsureSessionsMarketAccessTokenColumn:
    def test_skips_when_sessions_table_missing(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector([])),
        ):
            ensure_sessions_market_access_token_column(database_url="sqlite:///x")

    def test_skips_when_column_already_present(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["sessions"], {"sessions": ["market_access_token"]}),
            ),
        ):
            ensure_sessions_market_access_token_column(database_url="sqlite:///x")
        eng.begin.assert_not_called()

    def test_adds_column_on_postgresql(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        eng = _make_mock_engine("postgresql")
        # First call: column missing (trigger ALTER). Second call: column present (verify passes).
        insp_before = _make_inspector(["sessions"], {"sessions": []})
        insp_after = _make_inspector(["sessions"], {"sessions": ["market_access_token"]})
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", side_effect=[insp_before, insp_after]),
        ):
            ensure_sessions_market_access_token_column(database_url="postgresql://x")
        eng.begin.assert_called()

    def test_adds_column_on_sqlite(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        eng = _make_mock_engine("sqlite")
        insp_before = _make_inspector(["sessions"], {"sessions": []})
        insp_after = _make_inspector(["sessions"], {"sessions": ["market_access_token"]})
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", side_effect=[insp_before, insp_after]),
        ):
            ensure_sessions_market_access_token_column(database_url="sqlite:///x")
        eng.begin.assert_called()


# ---------------------------------------------------------------------------
# ensure_sessions_enterprise_entitlement_columns
# ---------------------------------------------------------------------------


class TestEnsureSessionsEnterpriseEntitlementColumns:
    def test_skips_when_sessions_missing(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector([])),
        ):
            ensure_sessions_enterprise_entitlement_columns(database_url="sqlite:///x")

    def test_adds_columns_sqlite(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect", return_value=_make_inspector(["sessions"], {"sessions": []})
            ),
        ):
            ensure_sessions_enterprise_entitlement_columns(database_url="sqlite:///x")
        eng.begin.assert_called()

    def test_adds_columns_postgresql(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect", return_value=_make_inspector(["sessions"], {"sessions": []})
            ),
        ):
            ensure_sessions_enterprise_entitlement_columns(database_url="postgresql://x")
        eng.begin.assert_called()


# ---------------------------------------------------------------------------
# ensure_user_profile_columns
# ---------------------------------------------------------------------------


class TestEnsureUserProfileColumns:
    def test_skips_when_users_table_missing(self):
        from app.db.init_db import ensure_user_profile_columns

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector([])),
        ):
            ensure_user_profile_columns(database_url="sqlite:///x")

    def test_adds_columns_sqlite(self):
        from app.db.init_db import ensure_user_profile_columns

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector(["users"], {"users": []})),
        ):
            ensure_user_profile_columns(database_url="sqlite:///x")
        eng.begin.assert_called()

    def test_adds_columns_postgresql_jsonb(self):
        from app.db.init_db import ensure_user_profile_columns

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector(["users"], {"users": []})),
        ):
            ensure_user_profile_columns(database_url="postgresql://x")
        eng.begin.assert_called()

    def test_skips_existing_columns(self):
        from app.db.init_db import ensure_user_profile_columns

        existing_cols = [
            "tier",
            "industry_id",
            "account_tier",
            "budget_range",
            "entitled_industries",
            "failed_login_attempts",
            "locked_until",
            "email_verified",
        ]
        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["users"], {"users": existing_cols}),
            ),
        ):
            ensure_user_profile_columns(database_url="sqlite:///x")
        conn_mock = eng.begin.return_value.__enter__.return_value
        assert conn_mock.execute.call_count == 0


# ---------------------------------------------------------------------------
# ensure_business_tenant_id_columns
# ---------------------------------------------------------------------------


class TestEnsureBusinessTenantIdColumns:
    def test_adds_tenant_id_to_products_sqlite(self):
        from app.db.init_db import ensure_business_tenant_id_columns

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["products"], {"products": ["id", "name"]}),
            ),
        ):
            ensure_business_tenant_id_columns(database_url="sqlite:///x")
        eng.begin.assert_called()

    def test_skips_existing_tenant_id(self):
        from app.db.init_db import ensure_business_tenant_id_columns

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["products"], {"products": ["tenant_id"]}),
            ),
        ):
            ensure_business_tenant_id_columns(database_url="sqlite:///x")
        conn_mock = eng.begin.return_value.__enter__.return_value
        assert conn_mock.execute.call_count == 0

    def test_adds_tenant_id_postgresql(self):
        from app.db.init_db import ensure_business_tenant_id_columns

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["products"], {"products": ["id"]}),
            ),
        ):
            ensure_business_tenant_id_columns(database_url="postgresql://x")
        eng.begin.assert_called()

    def test_swallows_recoverable_error(self):
        from app.db.init_db import ensure_business_tenant_id_columns

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", side_effect=OSError("disk")),
        ):
            ensure_business_tenant_id_columns(database_url="sqlite:///x")  # must not raise


# ---------------------------------------------------------------------------
# ensure_users_tenant_id_column
# ---------------------------------------------------------------------------


class TestEnsureUsersTenantIdColumn:
    def test_skips_when_users_missing(self):
        from app.db.init_db import ensure_users_tenant_id_column

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector([])),
        ):
            ensure_users_tenant_id_column(database_url="sqlite:///x")

    def test_skips_when_column_exists(self):
        from app.db.init_db import ensure_users_tenant_id_column

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["users"], {"users": ["tenant_id"]}),
            ),
        ):
            ensure_users_tenant_id_column(database_url="sqlite:///x")
        conn_mock = eng.begin.return_value.__enter__.return_value
        assert conn_mock.execute.call_count == 0

    def test_adds_column_sqlite(self):
        from app.db.init_db import ensure_users_tenant_id_column

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector(["users"], {"users": []})),
        ):
            ensure_users_tenant_id_column(database_url="sqlite:///x")
        eng.begin.assert_called()

    def test_adds_column_postgresql(self):
        from app.db.init_db import ensure_users_tenant_id_column

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector(["users"], {"users": []})),
        ):
            ensure_users_tenant_id_column(database_url="postgresql://x")
        eng.begin.assert_called()


# ---------------------------------------------------------------------------
# init_approval_tables
# ---------------------------------------------------------------------------


class TestInitApprovalTables:
    def test_adds_business_type_column_postgresql(self):
        from app.db.init_db import init_approval_tables

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch("app.db.base.Base.metadata.create_all"),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(
                    ["approval_flows"], {"approval_flows": ["id", "name"]}
                ),
            ),
        ):
            init_approval_tables(eng)
        eng.begin.assert_called()

    def test_adds_business_type_column_sqlite(self):
        from app.db.init_db import init_approval_tables

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch("app.db.base.Base.metadata.create_all"),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["approval_flows"], {"approval_flows": []}),
            ),
        ):
            init_approval_tables(eng)

    def test_skips_column_if_already_present(self):
        from app.db.init_db import init_approval_tables

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch("app.db.base.Base.metadata.create_all"),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(
                    ["approval_flows"], {"approval_flows": ["business_type"]}
                ),
            ),
        ):
            init_approval_tables(eng)
        conn_mock = eng.begin.return_value.__enter__.return_value
        assert conn_mock.execute.call_count == 0

    def test_create_all_error_continues_to_alter(self):
        from app.db.init_db import init_approval_tables

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch("app.db.base.Base.metadata.create_all", side_effect=OSError("fail")),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["approval_flows"], {"approval_flows": []}),
            ),
        ):
            init_approval_tables(eng)  # must not raise


# ---------------------------------------------------------------------------
# init_template_tables_for_engine
# ---------------------------------------------------------------------------


class TestInitTemplateTablesForEngine:
    def test_skips_non_postgresql(self):
        from app.db.init_db import init_template_tables_for_engine

        eng = _make_mock_engine("sqlite")
        with patch("sqlalchemy.inspect", return_value=_make_inspector([])):
            init_template_tables_for_engine(eng)
        eng.begin.assert_not_called()

    def test_creates_tables_when_missing_postgresql(self):
        from app.db.init_db import init_template_tables_for_engine

        eng = _make_mock_engine("postgresql")
        with patch("sqlalchemy.inspect", return_value=_make_inspector([])):
            init_template_tables_for_engine(eng)
        eng.begin.assert_called()

    def test_skips_existing_tables(self):
        from app.db.init_db import init_template_tables_for_engine

        eng = _make_mock_engine("postgresql")
        with patch(
            "sqlalchemy.inspect", return_value=_make_inspector(["templates", "template_usage_log"])
        ):
            init_template_tables_for_engine(eng)
        # execute called for CREATE INDEX only (2 indexes)
        conn_mock = eng.begin.return_value.__enter__.return_value
        assert conn_mock.execute.call_count == 2


# ---------------------------------------------------------------------------
# _iter_seed_dirs
# ---------------------------------------------------------------------------


class TestIterSeedDirs:
    def test_yields_resource_and_base(self):
        from app.db.init_db import _iter_seed_dirs

        with (
            patch("app.db.init_db.get_resource_path", return_value="/r/db_seed"),
            patch("app.db.init_db.get_base_dir", return_value="/base"),
        ):
            result = list(_iter_seed_dirs())
        assert "/r/db_seed" in result
        assert "/base" in result

    def test_includes_meipass_when_present(self, monkeypatch):
        from app.db.init_db import _iter_seed_dirs

        monkeypatch.setattr(sys, "_MEIPASS", "/meipass", raising=False)
        with (
            patch("app.db.init_db.get_resource_path", return_value="/r"),
            patch("app.db.init_db.get_base_dir", return_value="/b"),
        ):
            result = list(_iter_seed_dirs())
        assert "/meipass" in result

    def test_excludes_meipass_when_absent(self, monkeypatch):
        if hasattr(sys, "_MEIPASS"):
            monkeypatch.delattr(sys, "_MEIPASS")
        from app.db.init_db import _iter_seed_dirs

        with (
            patch("app.db.init_db.get_resource_path", return_value="/r"),
            patch("app.db.init_db.get_base_dir", return_value="/b"),
        ):
            result = list(_iter_seed_dirs())
        assert "/meipass" not in result


# ---------------------------------------------------------------------------
# ensure_sessions_account_meta_columns
# ---------------------------------------------------------------------------


class TestEnsureSessionsAccountMetaColumns:
    def test_skips_when_sessions_missing(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector([])),
        ):
            ensure_sessions_account_meta_columns(database_url="sqlite:///x")

    def test_adds_columns_sqlite(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect", return_value=_make_inspector(["sessions"], {"sessions": []})
            ),
        ):
            ensure_sessions_account_meta_columns(database_url="sqlite:///x")
        eng.begin.assert_called()

    def test_adds_columns_postgresql(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect", return_value=_make_inspector(["sessions"], {"sessions": []})
            ),
        ):
            ensure_sessions_account_meta_columns(database_url="postgresql://x")
        eng.begin.assert_called()

    def test_skips_existing_columns(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        existing = [
            "account_kind",
            "company_brand",
            "market_is_admin",
            "market_is_enterprise",
            "impersonating_market_user_id",
            "impersonating_username",
            "tenant_id",
            "market_membership_tier",
        ]
        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["sessions"], {"sessions": existing}),
            ),
        ):
            ensure_sessions_account_meta_columns(database_url="sqlite:///x")
        conn_mock = eng.begin.return_value.__enter__.return_value
        assert conn_mock.execute.call_count == 0
