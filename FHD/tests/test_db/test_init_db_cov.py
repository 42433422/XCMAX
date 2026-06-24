"""Behaviour tests for app.db.init_db.

These exercise the startup "ensure column / ensure table" helpers without a real
DB. SQLAlchemy / inspect / engine are mocked, but assertions land on the
*observable behaviour of the code under test* — the exact DDL emitted, the
dialect-specific SQL variants, the early-return short circuits, and the
error-swallowing contract — not merely on whether a mock was called.

Patching note: the helpers do ``from app.db import _create_engine_for_url`` /
``from app.db import _get_engine`` inside their bodies, so we patch those
attributes on the ``app.db`` module object (``_app_db_module``), not on
``app.db.init_db``.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# pre-import so patch.object can refer to the module object
import app.db as _app_db_module

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_mock_engine(dialect_name: str = "sqlite") -> MagicMock:
    """Build a mock SQLAlchemy engine whose ``begin()`` yields a conn we can read."""
    eng = MagicMock()
    eng.dialect.name = dialect_name
    conn_ctx = MagicMock()
    conn_mock = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_mock)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    eng.begin.return_value = conn_ctx
    return eng


def _conn_of(eng: MagicMock) -> MagicMock:
    """The connection object yielded by ``with eng.begin() as conn``."""
    return eng.begin.return_value.__enter__.return_value


def _executed_sql(eng: MagicMock) -> list[str]:
    """Return the stringified SQL of every ``conn.execute(text(...))`` call.

    Works whether the helper passed a ``text()`` clause or a raw string as the
    first positional arg.
    """
    conn = _conn_of(eng)
    out: list[str] = []
    for c in conn.execute.call_args_list:
        if not c.args:
            continue
        clause = c.args[0]
        out.append(str(getattr(clause, "text", clause)))
    return out


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
    def test_noop_when_config_none(self):
        from app.db.init_db import refresh_config_database_urls

        # No object to mutate -> returns None without touching environment.
        assert refresh_config_database_urls(None) is None

    def test_copies_all_three_url_fields_from_env(self):
        from app.db.init_db import refresh_config_database_urls

        class FakeConfig:
            DATABASE_URL = "old-db"
            VECTOR_DB_URL = "old-vec"
            DATABASE_PATH = "old-path"

        env = {
            "DATABASE_URL": "sqlite:///foo.db",
            "VECTOR_DB_URL": "postgresql://vec",
            "DATABASE_PATH": "/data/x",
        }
        with patch.dict(os.environ, env, clear=False):
            refresh_config_database_urls(FakeConfig)

        assert FakeConfig.DATABASE_URL == "sqlite:///foo.db"
        assert FakeConfig.VECTOR_DB_URL == "postgresql://vec"
        assert FakeConfig.DATABASE_PATH == "/data/x"

    def test_keeps_existing_value_when_env_var_absent(self):
        from app.db.init_db import refresh_config_database_urls

        class FakeConfig:
            DATABASE_URL = "existing"
            VECTOR_DB_URL = "keep-vec"
            DATABASE_PATH = "keep-path"

        with patch.dict(os.environ, {}, clear=True):
            refresh_config_database_urls(FakeConfig)

        # No env vars present -> all originals preserved unchanged.
        assert FakeConfig.DATABASE_URL == "existing"
        assert FakeConfig.VECTOR_DB_URL == "keep-vec"
        assert FakeConfig.DATABASE_PATH == "keep-path"

    def test_empty_env_value_does_not_overwrite(self):
        from app.db.init_db import refresh_config_database_urls

        class FakeConfig:
            DATABASE_URL = "existing"

        # Empty string is falsy -> the `if value:` guard skips the setattr.
        with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=False):
            refresh_config_database_urls(FakeConfig)

        assert FakeConfig.DATABASE_URL == "existing"


# ---------------------------------------------------------------------------
# ensure_runtime_database_environment
# ---------------------------------------------------------------------------


class TestEnsureRuntimeDatabaseEnvironment:
    def test_non_desktop_returns_env_database_url_verbatim(self):
        from app.db.init_db import ensure_runtime_database_environment

        with patch.dict(
            os.environ, {"XCAGI_DESKTOP_MODE": "", "DATABASE_URL": "postgresql://x"}, clear=False
        ):
            url = ensure_runtime_database_environment()
        assert url == "postgresql://x"

    def test_non_desktop_returns_empty_string_when_unset(self):
        from app.db.init_db import ensure_runtime_database_environment

        with patch.dict(os.environ, {}, clear=True):
            url = ensure_runtime_database_environment()
        # os.environ.get("DATABASE_URL", "") default branch.
        assert url == ""

    def test_desktop_mode_points_db_url_and_path_at_sqlite_under_data_root(self, tmp_path):
        from app.db.init_db import ensure_runtime_database_environment

        ensure_tables = MagicMock()
        with (
            patch.dict(os.environ, {"XCAGI_DESKTOP_MODE": "1"}, clear=False),
            patch("app.db.init_db._desktop_data_root", return_value=tmp_path),
            patch("app.db.init_db.ensure_desktop_sqlite_business_tables_all_files", ensure_tables),
        ):
            url = ensure_runtime_database_environment()
            # Assert env side effects inside the patch.dict scope (they are rolled
            # back on exit). DATABASE_URL/DATABASE_PATH are rewritten in place.
            assert os.environ["DATABASE_URL"] == url
            assert os.environ["DATABASE_PATH"] == str(tmp_path / "data")

        expected_db = tmp_path / "data" / "xcagi.db"
        assert url == f"sqlite:///{expected_db}"
        assert (tmp_path / "data").is_dir()
        # Business-table bootstrap is invoked against the desktop root.
        ensure_tables.assert_called_once_with(str(tmp_path))

    def test_desktop_mode_accepts_each_truthy_spelling(self, tmp_path):
        from app.db.init_db import ensure_runtime_database_environment

        for val in ("1", "true", "yes", "on", "ON", "True", "  yes  "):
            with (
                patch.dict(os.environ, {"XCAGI_DESKTOP_MODE": val}, clear=False),
                patch("app.db.init_db._desktop_data_root", return_value=tmp_path),
                patch("app.db.init_db.ensure_desktop_sqlite_business_tables_all_files"),
            ):
                url = ensure_runtime_database_environment()
            assert url.startswith("sqlite:///"), f"expected sqlite for {val!r}, got {url!r}"

    def test_falsey_desktop_flag_is_treated_as_non_desktop(self, tmp_path):
        from app.db.init_db import ensure_runtime_database_environment

        for val in ("0", "false", "no", "off", "maybe"):
            with (
                patch.dict(
                    os.environ,
                    {"XCAGI_DESKTOP_MODE": val, "DATABASE_URL": "postgresql://prod"},
                    clear=False,
                ),
                patch("app.db.init_db._desktop_data_root", return_value=tmp_path),
            ):
                url = ensure_runtime_database_environment()
            assert url == "postgresql://prod", f"{val!r} must not flip into desktop mode"


# ---------------------------------------------------------------------------
# _resolve_auth_bootstrap_engine
# ---------------------------------------------------------------------------


class TestResolveAuthBootstrapEngine:
    def test_returns_none_when_every_path_fails(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        with (
            patch.object(
                _app_db_module, "_create_engine_for_url", side_effect=ImportError, create=True
            ),
            patch.object(_app_db_module, "_get_engine", side_effect=RuntimeError, create=True),
        ):
            assert _resolve_auth_bootstrap_engine() is None

    def test_database_url_takes_priority_over_fallback(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        from_url = _make_mock_engine()
        from_get = _make_mock_engine()
        with (
            patch.object(
                _app_db_module, "_create_engine_for_url", return_value=from_url, create=True
            ),
            patch.object(_app_db_module, "_get_engine", return_value=from_get, create=True),
        ):
            result = _resolve_auth_bootstrap_engine(database_url="sqlite:///x")
        # The URL-built engine wins; _get_engine fallback is never consulted.
        assert result is from_url

    def test_blank_database_url_is_ignored(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        from_get = _make_mock_engine()
        create = MagicMock()
        with (
            patch.object(_app_db_module, "_create_engine_for_url", create, create=True),
            patch.object(_app_db_module, "_get_engine", return_value=from_get, create=True),
        ):
            result = _resolve_auth_bootstrap_engine(database_url="   ")
        # Whitespace-only url is stripped to empty -> create_engine not called.
        create.assert_not_called()
        assert result is from_get

    def test_real_engine_instance_is_returned_directly(self):
        from sqlalchemy import create_engine

        from app.db.init_db import _resolve_auth_bootstrap_engine

        real_eng = create_engine("sqlite:///:memory:")
        # A genuine Engine passes the isinstance check and is used as-is, even
        # without _create_engine_for_url being available.
        result = _resolve_auth_bootstrap_engine(engine=real_eng)
        assert result is real_eng

    def test_non_engine_arg_triggers_get_engine_fallback(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        not_an_engine = _make_mock_engine()  # MagicMock, not a real Engine
        from_get = _make_mock_engine()
        with (
            patch.object(
                _app_db_module, "_create_engine_for_url", side_effect=Exception, create=True
            ),
            patch.object(_app_db_module, "_get_engine", return_value=from_get, create=True),
        ):
            result = _resolve_auth_bootstrap_engine(engine=not_an_engine)
        # The passed object is not an Engine -> code falls through to _get_engine.
        assert result is from_get

    def test_falls_back_to_get_engine_when_no_args(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        from_get = _make_mock_engine()
        with (
            patch.object(
                _app_db_module, "_create_engine_for_url", side_effect=Exception, create=True
            ),
            patch.object(_app_db_module, "_get_engine", return_value=from_get, create=True),
        ):
            result = _resolve_auth_bootstrap_engine()
        assert result is from_get


# ---------------------------------------------------------------------------
# ensure_sqlite_rbac_bootstrap
# ---------------------------------------------------------------------------


class TestEnsureSqliteRbacBootstrap:
    def test_non_sqlite_engine_short_circuits_before_inspect(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        eng = _make_mock_engine("postgresql")
        seed = MagicMock()
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("app.db.init_db._seed_sqlite_rbac_defaults", seed),
        ):
            ensure_sqlite_rbac_bootstrap(engine=eng)
        # postgresql dialect -> the function returns before seeding RBAC defaults.
        seed.assert_not_called()

    def test_none_engine_short_circuits(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        seed = MagicMock()
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=None),
            patch("app.db.init_db._seed_sqlite_rbac_defaults", seed),
        ):
            ensure_sqlite_rbac_bootstrap()
        seed.assert_not_called()

    def test_creates_missing_tables_then_seeds(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        eng = _make_mock_engine("sqlite")
        seed = MagicMock()
        create_all = MagicMock()
        # Only one of the three RBAC tables present -> needed.issubset is False.
        insp = _make_inspector(["permissions"])
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("app.db.init_db._seed_sqlite_rbac_defaults", seed),
            patch("app.db.base.Base.metadata.create_all", create_all),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            ensure_sqlite_rbac_bootstrap(engine=eng)
        # Tables were created (subset check failed) and seeding ran.
        create_all.assert_called_once()
        seed.assert_called_once_with(eng)

    def test_skips_create_all_when_all_tables_present(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        eng = _make_mock_engine("sqlite")
        seed = MagicMock()
        create_all = MagicMock()
        insp = _make_inspector(["permissions", "roles", "role_permissions"])
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("app.db.init_db._seed_sqlite_rbac_defaults", seed),
            patch("app.db.base.Base.metadata.create_all", create_all),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            ensure_sqlite_rbac_bootstrap(engine=eng)
        # All three tables already exist -> ORM create_all is skipped, seed still runs.
        create_all.assert_not_called()
        seed.assert_called_once_with(eng)

    def test_swallow_errors_true_suppresses_seed_failure(self):
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
            # swallow_errors=True (default) -> returns normally despite RuntimeError.
            assert ensure_sqlite_rbac_bootstrap(engine=eng, swallow_errors=True) is None

    def test_swallow_errors_false_reraises_seed_failure(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        eng = _make_mock_engine("sqlite")
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch(
                "app.db.init_db._seed_sqlite_rbac_defaults",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["permissions", "roles", "role_permissions"]),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            ensure_sqlite_rbac_bootstrap(engine=eng, swallow_errors=False)


# ---------------------------------------------------------------------------
# ensure_sessions_market_access_token_column
# ---------------------------------------------------------------------------


class TestEnsureSessionsMarketAccessTokenColumn:
    def test_returns_early_when_sessions_table_absent(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector([])),
        ):
            ensure_sessions_market_access_token_column(database_url="sqlite:///x")
        # No sessions table -> no DDL transaction opened.
        eng.begin.assert_not_called()

    def test_no_alter_when_column_already_present(self):
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

    def test_postgresql_uses_if_not_exists_variant(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        eng = _make_mock_engine("postgresql")
        insp_before = _make_inspector(["sessions"], {"sessions": []})
        insp_after = _make_inspector(["sessions"], {"sessions": ["market_access_token"]})
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", side_effect=[insp_before, insp_after]),
        ):
            ensure_sessions_market_access_token_column(database_url="postgresql://x")
        sql = _executed_sql(eng)
        assert sql == ["ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_access_token TEXT"]

    def test_sqlite_uses_plain_add_column(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        eng = _make_mock_engine("sqlite")
        insp_before = _make_inspector(["sessions"], {"sessions": []})
        insp_after = _make_inspector(["sessions"], {"sessions": ["market_access_token"]})
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", side_effect=[insp_before, insp_after]),
        ):
            ensure_sessions_market_access_token_column(database_url="sqlite:///x")
        sql = _executed_sql(eng)
        # sqlite branch: no "IF NOT EXISTS".
        assert sql == ["ALTER TABLE sessions ADD COLUMN market_access_token TEXT"]

    def test_post_alter_verification_failure_raises_runtime_error(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        eng = _make_mock_engine("sqlite")
        # ALTER runs, but the verify re-inspect still shows the column missing
        # -> the function escalates with a RuntimeError pointing at alembic.
        insp_before = _make_inspector(["sessions"], {"sessions": []})
        insp_verify = _make_inspector(["sessions"], {"sessions": []})
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", side_effect=[insp_before, insp_verify]),
            pytest.raises(RuntimeError, match="market_access_token"),
        ):
            ensure_sessions_market_access_token_column(database_url="sqlite:///x")


# ---------------------------------------------------------------------------
# ensure_sessions_enterprise_entitlement_columns
# ---------------------------------------------------------------------------


class TestEnsureSessionsEnterpriseEntitlementColumns:
    def test_returns_early_when_sessions_absent(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector([])),
        ):
            ensure_sessions_enterprise_entitlement_columns(database_url="sqlite:///x")
        eng.begin.assert_not_called()

    def test_sqlite_adds_both_columns_plain(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect", return_value=_make_inspector(["sessions"], {"sessions": []})
            ),
        ):
            ensure_sessions_enterprise_entitlement_columns(database_url="sqlite:///x")
        sql = _executed_sql(eng)
        assert sql == [
            "ALTER TABLE sessions ADD COLUMN market_user_id INTEGER",
            "ALTER TABLE sessions ADD COLUMN entitled_mod_ids_json TEXT",
        ]

    def test_postgresql_adds_both_columns_if_not_exists(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect", return_value=_make_inspector(["sessions"], {"sessions": []})
            ),
        ):
            ensure_sessions_enterprise_entitlement_columns(database_url="postgresql://x")
        sql = _executed_sql(eng)
        assert sql == [
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_user_id INTEGER",
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS entitled_mod_ids_json TEXT",
        ]

    def test_only_missing_column_is_added(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = _make_mock_engine("sqlite")
        # market_user_id already present -> only entitled_mod_ids_json is added.
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(["sessions"], {"sessions": ["market_user_id"]}),
            ),
        ):
            ensure_sessions_enterprise_entitlement_columns(database_url="sqlite:///x")
        sql = _executed_sql(eng)
        assert sql == ["ALTER TABLE sessions ADD COLUMN entitled_mod_ids_json TEXT"]


# ---------------------------------------------------------------------------
# ensure_user_profile_columns
# ---------------------------------------------------------------------------


class TestEnsureUserProfileColumns:
    def test_returns_early_when_users_table_absent(self):
        from app.db.init_db import ensure_user_profile_columns

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector([])),
        ):
            ensure_user_profile_columns(database_url="sqlite:///x")
        eng.begin.assert_not_called()

    def test_sqlite_adds_all_eight_profile_columns(self):
        from app.db.init_db import ensure_user_profile_columns

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector(["users"], {"users": []})),
        ):
            ensure_user_profile_columns(database_url="sqlite:///x")
        sql = _executed_sql(eng)
        assert sql == [
            "ALTER TABLE users ADD COLUMN tier VARCHAR(32) DEFAULT 'personal'",
            "ALTER TABLE users ADD COLUMN industry_id VARCHAR(32) DEFAULT '通用'",
            "ALTER TABLE users ADD COLUMN account_tier VARCHAR(32)",
            "ALTER TABLE users ADD COLUMN budget_range VARCHAR(32)",
            "ALTER TABLE users ADD COLUMN entitled_industries TEXT",
            "ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN locked_until TIMESTAMP",
            "ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE",
        ]

    def test_postgresql_uses_jsonb_for_entitled_industries_and_if_not_exists(self):
        from app.db.init_db import ensure_user_profile_columns

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector(["users"], {"users": []})),
        ):
            ensure_user_profile_columns(database_url="postgresql://x")
        sql = _executed_sql(eng)
        assert all(s.startswith("ALTER TABLE users ADD COLUMN IF NOT EXISTS ") for s in sql)
        # entitled_industries is JSONB on postgresql, TEXT elsewhere.
        assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS entitled_industries JSONB" in sql
        assert (
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS tier VARCHAR(32) DEFAULT 'personal'" in sql
        )

    def test_no_ddl_when_every_column_already_exists(self):
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
        # Transaction is still opened, but no column is altered.
        assert _executed_sql(eng) == []
        assert _conn_of(eng).execute.call_count == 0


# ---------------------------------------------------------------------------
# ensure_business_tenant_id_columns
# ---------------------------------------------------------------------------


class TestEnsureBusinessTenantIdColumns:
    def test_sqlite_adds_tenant_id_to_present_business_table(self):
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
        # Only `products` exists among the business tables -> single ALTER.
        assert _executed_sql(eng) == ["ALTER TABLE products ADD COLUMN tenant_id INTEGER"]

    def test_skips_table_that_already_has_tenant_id(self):
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
        assert _executed_sql(eng) == []

    def test_postgresql_uses_if_not_exists(self):
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
        assert _executed_sql(eng) == [
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS tenant_id INTEGER"
        ]

    def test_adds_tenant_id_to_each_present_business_table(self):
        from app.db.init_db import ensure_business_tenant_id_columns

        eng = _make_mock_engine("sqlite")
        present = ["products", "suppliers", "warehouses", "not_a_business_table"]
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(present, {t: [] for t in present}),
            ),
        ):
            ensure_business_tenant_id_columns(database_url="sqlite:///x")
        sql = _executed_sql(eng)
        # Each recognised business table gets exactly one ALTER, the stray table
        # is ignored, and ordering follows the helper's business_tables tuple.
        assert sql == [
            "ALTER TABLE products ADD COLUMN tenant_id INTEGER",
            "ALTER TABLE suppliers ADD COLUMN tenant_id INTEGER",
            "ALTER TABLE warehouses ADD COLUMN tenant_id INTEGER",
        ]

    def test_swallows_recoverable_inspect_error(self):
        from app.db.init_db import ensure_business_tenant_id_columns

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", side_effect=OSError("disk")),
        ):
            # OSError is in RECOVERABLE_ERRORS -> swallowed, returns None.
            assert ensure_business_tenant_id_columns(database_url="sqlite:///x") is None


# ---------------------------------------------------------------------------
# ensure_users_tenant_id_column
# ---------------------------------------------------------------------------


class TestEnsureUsersTenantIdColumn:
    def test_returns_early_when_users_absent(self):
        from app.db.init_db import ensure_users_tenant_id_column

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector([])),
        ):
            ensure_users_tenant_id_column(database_url="sqlite:///x")
        eng.begin.assert_not_called()

    def test_no_alter_when_column_exists(self):
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
        eng.begin.assert_not_called()

    def test_sqlite_emits_plain_alter(self):
        from app.db.init_db import ensure_users_tenant_id_column

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector(["users"], {"users": []})),
        ):
            ensure_users_tenant_id_column(database_url="sqlite:///x")
        assert _executed_sql(eng) == ["ALTER TABLE users ADD COLUMN tenant_id INTEGER"]

    def test_postgresql_emits_if_not_exists_alter(self):
        from app.db.init_db import ensure_users_tenant_id_column

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector(["users"], {"users": []})),
        ):
            ensure_users_tenant_id_column(database_url="postgresql://x")
        assert _executed_sql(eng) == [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id INTEGER"
        ]


# ---------------------------------------------------------------------------
# init_approval_tables
# ---------------------------------------------------------------------------


class TestInitApprovalTables:
    def test_postgresql_missing_column_adds_column_and_index(self):
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
        sql = _executed_sql(eng)
        # postgresql path: ALTER (IF NOT EXISTS) plus a backing index.
        assert any("ADD COLUMN IF NOT EXISTS business_type" in s for s in sql)
        assert any("CREATE INDEX IF NOT EXISTS ix_approval_flows_business_type" in s for s in sql)

    def test_sqlite_missing_column_adds_column_without_index(self):
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
        sql = _executed_sql(eng)
        # sqlite path: plain ALTER, and no CREATE INDEX.
        assert sql == [
            "ALTER TABLE approval_flows ADD COLUMN business_type VARCHAR(64) DEFAULT 'general'"
        ]
        assert not any("CREATE INDEX" in s for s in sql)

    def test_existing_business_type_column_yields_no_ddl(self):
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
        assert _executed_sql(eng) == []

    def test_create_all_failure_does_not_block_alter(self):
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
            init_approval_tables(eng)
        # create_all raised a recoverable error but the ALTER compat path still ran.
        assert _executed_sql(eng) == [
            "ALTER TABLE approval_flows ADD COLUMN business_type VARCHAR(64) DEFAULT 'general'"
        ]


# ---------------------------------------------------------------------------
# init_template_tables_for_engine
# ---------------------------------------------------------------------------


class TestInitTemplateTablesForEngine:
    def test_non_postgresql_is_a_noop(self):
        from app.db.init_db import init_template_tables_for_engine

        eng = _make_mock_engine("sqlite")
        with patch("sqlalchemy.inspect", return_value=_make_inspector([])):
            init_template_tables_for_engine(eng)
        # Guard: sqlite returns before opening any transaction.
        eng.begin.assert_not_called()

    def test_creates_both_tables_and_indexes_when_missing(self):
        from app.db.init_db import init_template_tables_for_engine

        eng = _make_mock_engine("postgresql")
        with patch("sqlalchemy.inspect", return_value=_make_inspector([])):
            init_template_tables_for_engine(eng)
        sql = _executed_sql(eng)
        # 2 CREATE TABLE + 2 CREATE INDEX.
        assert len(sql) == 4
        assert any("CREATE TABLE templates" in s for s in sql)
        assert any("CREATE TABLE template_usage_log" in s for s in sql)
        assert sum("CREATE INDEX IF NOT EXISTS" in s for s in sql) == 2

    def test_existing_tables_only_create_indexes(self):
        from app.db.init_db import init_template_tables_for_engine

        eng = _make_mock_engine("postgresql")
        with patch(
            "sqlalchemy.inspect", return_value=_make_inspector(["templates", "template_usage_log"])
        ):
            init_template_tables_for_engine(eng)
        sql = _executed_sql(eng)
        # Tables already exist -> only the two idempotent CREATE INDEX statements.
        assert len(sql) == 2
        assert all(s.startswith("CREATE INDEX IF NOT EXISTS") for s in sql)
        assert not any("CREATE TABLE" in s for s in sql)


# ---------------------------------------------------------------------------
# _iter_seed_dirs
# ---------------------------------------------------------------------------


class TestIterSeedDirs:
    def test_yields_resource_dir_then_base_dir_in_order(self, monkeypatch):
        from app.db.init_db import _iter_seed_dirs

        if hasattr(sys, "_MEIPASS"):
            monkeypatch.delattr(sys, "_MEIPASS")
        with (
            patch("app.db.init_db.get_resource_path", return_value="/r/db_seed"),
            patch("app.db.init_db.get_base_dir", return_value="/base"),
        ):
            result = list(_iter_seed_dirs())
        # Priority order is contractually resource dir first, then base dir.
        assert result == ["/r/db_seed", "/base"]

    def test_appends_meipass_when_frozen(self, monkeypatch):
        from app.db.init_db import _iter_seed_dirs

        monkeypatch.setattr(sys, "_MEIPASS", "/meipass", raising=False)
        with (
            patch("app.db.init_db.get_resource_path", return_value="/r"),
            patch("app.db.init_db.get_base_dir", return_value="/b"),
        ):
            result = list(_iter_seed_dirs())
        # _MEIPASS present (PyInstaller) -> appended last.
        assert result == ["/r", "/b", "/meipass"]

    def test_omits_meipass_when_not_frozen(self, monkeypatch):
        if hasattr(sys, "_MEIPASS"):
            monkeypatch.delattr(sys, "_MEIPASS")
        from app.db.init_db import _iter_seed_dirs

        with (
            patch("app.db.init_db.get_resource_path", return_value="/r"),
            patch("app.db.init_db.get_base_dir", return_value="/b"),
        ):
            result = list(_iter_seed_dirs())
        assert result == ["/r", "/b"]
        assert "/meipass" not in result


# ---------------------------------------------------------------------------
# ensure_sessions_account_meta_columns
# ---------------------------------------------------------------------------


class TestEnsureSessionsAccountMetaColumns:
    def test_returns_early_when_sessions_absent(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        eng = _make_mock_engine()
        with (
            _patch_engine(eng),
            patch("sqlalchemy.inspect", return_value=_make_inspector([])),
        ):
            ensure_sessions_account_meta_columns(database_url="sqlite:///x")
        eng.begin.assert_not_called()

    def test_sqlite_adds_all_account_meta_columns(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        eng = _make_mock_engine("sqlite")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect", return_value=_make_inspector(["sessions"], {"sessions": []})
            ),
        ):
            ensure_sessions_account_meta_columns(database_url="sqlite:///x")
        sql = _executed_sql(eng)
        assert sql == [
            "ALTER TABLE sessions ADD COLUMN account_kind VARCHAR(32) DEFAULT 'enterprise'",
            "ALTER TABLE sessions ADD COLUMN company_brand VARCHAR(256) DEFAULT ''",
            "ALTER TABLE sessions ADD COLUMN market_is_admin BOOLEAN DEFAULT FALSE",
            "ALTER TABLE sessions ADD COLUMN market_is_enterprise BOOLEAN DEFAULT FALSE",
            "ALTER TABLE sessions ADD COLUMN impersonating_market_user_id INTEGER",
            "ALTER TABLE sessions ADD COLUMN impersonating_username VARCHAR(128) DEFAULT ''",
            "ALTER TABLE sessions ADD COLUMN tenant_id INTEGER",
            "ALTER TABLE sessions ADD COLUMN market_membership_tier VARCHAR(32)",
        ]

    def test_postgresql_adds_columns_with_if_not_exists(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        eng = _make_mock_engine("postgresql")
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect", return_value=_make_inspector(["sessions"], {"sessions": []})
            ),
        ):
            ensure_sessions_account_meta_columns(database_url="postgresql://x")
        sql = _executed_sql(eng)
        assert len(sql) == 8
        assert all("ADD COLUMN IF NOT EXISTS" in s for s in sql)
        assert (
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS account_kind VARCHAR(32) "
            "DEFAULT 'enterprise'" in sql
        )
        # Columns whose default_sql is None get no DEFAULT clause.
        assert (
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS impersonating_market_user_id INTEGER"
            in sql
        )

    def test_only_missing_columns_added(self):
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
        # All eight already present -> the transaction opens but no DDL is run.
        assert _executed_sql(eng) == []

    def test_partial_existing_adds_only_the_gaps(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        eng = _make_mock_engine("sqlite")
        # account_kind + tenant_id present -> the other six should be added.
        with (
            _patch_engine(eng),
            patch(
                "sqlalchemy.inspect",
                return_value=_make_inspector(
                    ["sessions"], {"sessions": ["account_kind", "tenant_id"]}
                ),
            ),
        ):
            ensure_sessions_account_meta_columns(database_url="sqlite:///x")
        sql = _executed_sql(eng)
        assert sql == [
            "ALTER TABLE sessions ADD COLUMN company_brand VARCHAR(256) DEFAULT ''",
            "ALTER TABLE sessions ADD COLUMN market_is_admin BOOLEAN DEFAULT FALSE",
            "ALTER TABLE sessions ADD COLUMN market_is_enterprise BOOLEAN DEFAULT FALSE",
            "ALTER TABLE sessions ADD COLUMN impersonating_market_user_id INTEGER",
            "ALTER TABLE sessions ADD COLUMN impersonating_username VARCHAR(128) DEFAULT ''",
            "ALTER TABLE sessions ADD COLUMN market_membership_tier VARCHAR(32)",
        ]
