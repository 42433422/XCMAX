"""Behavioral tests for app.db.init_db bootstrap/DDL helpers.

These tests favour real in-memory SQLite engines and assert on the *resulting*
schema (tables, columns, seeded rows) rather than only that a mock ``begin()``
was called. For PostgreSQL-only branches (the DDL is dialect gated and cannot
run on SQLite) we capture the exact SQL emitted on the connection and assert on
the statement text so the dialect-specific behaviour and the "skip when present"
short-circuits are pinned down.

Covers: _iter_seed_dirs, ensure_postgresql_auth_bootstrap,
ensure_sessions_market_access_token_column / _refresh_token_column,
ensure_sessions_enterprise_entitlement_columns, ensure_sessions_account_meta_columns,
ensure_user_preferences_bootstrap, ensure_runtime_auth_bootstrap,
_seed_sqlite_rbac_defaults, ensure_sqlite_*_bootstrap, init_im_tables,
init_approval_tables, ensure_product_query_indexes, init_service_bridge_tables,
_resolve_auth_bootstrap_engine, build_mod_database_seed_plan.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

# Use MagicMock for all mocks to support context manager protocol
Mock = MagicMock  # type: ignore[assignment,misc]  # noqa: F811

import pytest
from sqlalchemy import create_engine, inspect, text


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _sqlite_engine():
    return create_engine("sqlite:///:memory:")


def _make_sessions_table(engine, columns="id INTEGER PRIMARY KEY, session_id TEXT"):
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE sessions ({columns})"))


def _table_names(engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        return {r[0] for r in rows}


def _index_names(engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
        return {r[0] for r in rows}


def _column_names(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _capture_pg_ddl(mock_engine):
    """Wire a MagicMock engine so every conn.execute(stmt) appends the SQL text."""
    captured: list[str] = []
    conn = mock_engine.begin.return_value.__enter__.return_value
    conn.execute.side_effect = lambda stmt, *a, **k: captured.append(str(stmt))
    return captured


# ========================= _iter_seed_dirs ================================= #


class TestIterSeedDirs:
    def test_yields_resource_then_base_in_priority_order(self):
        from app.db.init_db import _iter_seed_dirs

        with (
            patch("app.db.init_db.get_resource_path", return_value="/r/db_seed"),
            patch("app.db.init_db.get_base_dir", return_value="/base"),
        ):
            if hasattr(sys, "_MEIPASS"):
                del sys._MEIPASS
            result = list(_iter_seed_dirs())
        # Exactly two entries in documented priority order when not packaged.
        assert result == ["/r/db_seed", "/base"]

    def test_appends_meipass_last_when_packaged(self):
        from app.db.init_db import _iter_seed_dirs

        with (
            patch("app.db.init_db.get_resource_path", return_value="/r/db_seed"),
            patch("app.db.init_db.get_base_dir", return_value="/base"),
            patch.object(sys, "_MEIPASS", "/tmp/meipass", create=True),
        ):
            result = list(_iter_seed_dirs())
        # _MEIPASS is yielded last (lowest priority) and only when present.
        assert result == ["/r/db_seed", "/base", "/tmp/meipass"]

    def test_no_meipass_attribute_yields_only_two(self):
        from app.db.init_db import _iter_seed_dirs

        original = getattr(sys, "_MEIPASS", None)
        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS
        try:
            with (
                patch("app.db.init_db.get_resource_path", return_value="/r/db_seed"),
                patch("app.db.init_db.get_base_dir", return_value="/base"),
            ):
                result = list(_iter_seed_dirs())
            assert result == ["/r/db_seed", "/base"]
            assert "/tmp/meipass" not in result
        finally:
            if original is not None:
                sys._MEIPASS = original


# ========================= ensure_postgresql_auth_bootstrap ================ #


class TestEnsurePostgresqlAuthBootstrap:
    def test_non_postgresql_dialect_is_a_noop(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            ensure_postgresql_auth_bootstrap(None)
        # SQLite dialect -> early return: no DDL and no admin seeding.
        mock_engine.begin.assert_not_called()
        mock_seed.assert_not_called()

    def test_none_engine_is_a_noop(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=None),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            ensure_postgresql_auth_bootstrap(None)
        mock_seed.assert_not_called()

    def test_creates_users_and_sessions_then_seeds_admin(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        # 1st inspect: empty; 2nd inspect (after users DDL): users exists, sessions missing.
        insp_empty = Mock()
        insp_empty.get_table_names.return_value = []
        insp_users = Mock()
        insp_users.get_table_names.return_value = ["users"]
        captured = _capture_pg_ddl(mock_engine)

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[insp_empty, insp_users]),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            ensure_postgresql_auth_bootstrap(mock_engine)

        joined = "\n".join(captured)
        assert "CREATE TABLE users" in joined
        assert "CREATE TABLE sessions" in joined
        # session table carries the market token columns inline.
        assert "market_access_token TEXT" in joined
        assert "market_refresh_token TEXT" in joined
        # admin seeded once both tables exist.
        mock_seed.assert_called_once_with(mock_engine)

    def test_skips_users_ddl_when_users_already_present(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        insp_users = Mock()
        insp_users.get_table_names.return_value = ["users"]
        insp_users2 = Mock()
        insp_users2.get_table_names.return_value = ["users"]  # sessions still missing
        captured = _capture_pg_ddl(mock_engine)

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[insp_users, insp_users2]),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            ensure_postgresql_auth_bootstrap(mock_engine)

        joined = "\n".join(captured)
        # users already there -> no users DDL; only the sessions table is created.
        assert "CREATE TABLE users" not in joined
        assert "CREATE TABLE sessions" in joined
        mock_seed.assert_called_once()

    def test_sessions_skipped_and_no_seed_when_users_creation_failed(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        # users missing at first; re-inspect *still* shows users missing
        # (simulating a CREATE that did not take effect).
        insp_empty1 = Mock()
        insp_empty1.get_table_names.return_value = []
        insp_empty2 = Mock()
        insp_empty2.get_table_names.return_value = []
        captured = _capture_pg_ddl(mock_engine)

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[insp_empty1, insp_empty2]),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            ensure_postgresql_auth_bootstrap(mock_engine)

        joined = "\n".join(captured)
        # users DDL attempted, but sessions creation is skipped and the function
        # returns before seeding the admin (guard against a session FK to a
        # non-existent users table).
        assert "CREATE TABLE users" in joined
        assert "CREATE TABLE sessions" not in joined
        mock_seed.assert_not_called()

    def test_recoverable_inspect_error_is_swallowed_before_any_ddl(self):
        from app.db.init_db import ensure_postgresql_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            # RuntimeError is a RECOVERABLE_ERRORS member -> swallowed, no re-raise.
            ensure_postgresql_auth_bootstrap(mock_engine)
        mock_engine.begin.assert_not_called()
        mock_seed.assert_not_called()


# ===== ensure_sessions_market_access_token_column ========================== #


class TestEnsureSessionsMarketAccessTokenColumn:
    def test_no_engine_no_url_falls_back_to_get_engine_and_returns_none(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        with (
            patch("app.db._create_engine_for_url", side_effect=RuntimeError("no url")),
            patch("app.db._get_engine", side_effect=ImportError("no engine")) as mock_get,
        ):
            result = ensure_sessions_market_access_token_column(None, database_url=None)
        assert result is None
        # Confirms we reached the _get_engine fallback (not short-circuited earlier).
        mock_get.assert_called_once()

    def test_real_sqlite_adds_column_and_is_idempotent(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        engine = _sqlite_engine()
        _make_sessions_table(engine)
        assert "market_access_token" not in _column_names(engine, "sessions")

        ensure_sessions_market_access_token_column(engine)
        assert "market_access_token" in _column_names(engine, "sessions")

        # Second call: column already present -> no error, schema unchanged.
        ensure_sessions_market_access_token_column(engine)
        cols = _column_names(engine, "sessions")
        assert "market_access_token" in cols

    def test_real_sqlite_no_sessions_table_is_noop(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        engine = _sqlite_engine()  # no sessions table at all
        ensure_sessions_market_access_token_column(engine)
        assert "sessions" not in _table_names(engine)

    def test_postgresql_emits_if_not_exists_alter(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        insp_missing = Mock()
        insp_missing.get_table_names.return_value = ["sessions"]
        insp_missing.get_columns.return_value = [{"name": "id"}, {"name": "session_id"}]
        insp_present = Mock()
        insp_present.get_table_names.return_value = ["sessions"]
        insp_present.get_columns.return_value = [
            {"name": "id"},
            {"name": "session_id"},
            {"name": "market_access_token"},
        ]
        captured = _capture_pg_ddl(mock_engine)

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[insp_missing, insp_present]),
        ):
            ensure_sessions_market_access_token_column(None, database_url="postgresql://test")

        assert captured == [
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_access_token TEXT"
        ]

    def test_verify_raises_when_column_still_missing(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        # The ALTER is swallowed (begin raises a recoverable error), so verify
        # re-inspects, finds the column absent and raises the actionable error.
        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        mock_engine.begin.side_effect = RuntimeError("alter blew up")
        insp = Mock()
        insp.get_table_names.return_value = ["sessions"]
        insp.get_columns.return_value = [{"name": "id"}]  # never present

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            with pytest.raises(RuntimeError, match="缺少 market_access_token"):
                ensure_sessions_market_access_token_column(None, database_url="sqlite:///test.db")

    def test_verify_skips_when_sessions_table_vanished(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        insp_1 = Mock()
        insp_1.get_table_names.return_value = ["sessions"]
        insp_1.get_columns.return_value = [{"name": "id"}]
        insp_2 = Mock()
        insp_2.get_table_names.return_value = []  # sessions gone before verify
        captured = _capture_pg_ddl(mock_engine)

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=[insp_1, insp_2]),
        ):
            # add step runs; verify sees the table gone and returns instead of raising.
            ensure_sessions_market_access_token_column(None, database_url="sqlite:///test.db")

        # exactly one ALTER attempted, sqlite form (no IF NOT EXISTS).
        assert captured == ["ALTER TABLE sessions ADD COLUMN market_access_token TEXT"]

    def test_explicit_engine_used_directly_when_column_present(self):
        from app.db.init_db import ensure_sessions_market_access_token_column

        engine = _sqlite_engine()
        _make_sessions_table(engine, "id INTEGER PRIMARY KEY, market_access_token TEXT")
        # Pass the real engine directly (no url). Column present -> no ALTER, no raise.
        ensure_sessions_market_access_token_column(engine, database_url=None)
        assert _column_names(engine, "sessions") == {"id", "market_access_token"}


# ===== ensure_sessions_market_refresh_token_column ========================= #


class TestEnsureSessionsMarketRefreshTokenColumn:
    def test_column_already_present_no_alter(self):
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        engine = _sqlite_engine()
        _make_sessions_table(engine, "id INTEGER PRIMARY KEY, market_refresh_token TEXT")
        ensure_sessions_market_refresh_token_column(engine)
        assert _column_names(engine, "sessions") == {"id", "market_refresh_token"}

    def test_real_sqlite_adds_column(self):
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        engine = _sqlite_engine()
        _make_sessions_table(engine)
        ensure_sessions_market_refresh_token_column(engine)
        assert "market_refresh_token" in _column_names(engine, "sessions")

    def test_postgresql_emits_if_not_exists_alter(self):
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        insp = Mock()
        insp.get_table_names.return_value = ["sessions"]
        insp.get_columns.return_value = [{"name": "id"}]
        captured = _capture_pg_ddl(mock_engine)

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            ensure_sessions_market_refresh_token_column(None, database_url="postgresql://test")

        assert captured == [
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_refresh_token TEXT"
        ]

    def test_no_engine_returns_none(self):
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        with (
            patch("app.db._create_engine_for_url", side_effect=RuntimeError("no url")),
            patch("app.db._get_engine", side_effect=ImportError("no engine")) as mock_get,
        ):
            result = ensure_sessions_market_refresh_token_column(None, database_url=None)
        assert result is None
        mock_get.assert_called_once()


# ===== ensure_sessions_enterprise_entitlement_columns ====================== #


class TestEnsureSessionsEnterpriseEntitlementColumns:
    def test_real_sqlite_adds_both_columns(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        engine = _sqlite_engine()
        _make_sessions_table(engine, "id INTEGER PRIMARY KEY")
        ensure_sessions_enterprise_entitlement_columns(engine)
        cols = _column_names(engine, "sessions")
        assert "market_user_id" in cols
        assert "entitled_mod_ids_json" in cols

    def test_real_sqlite_adds_only_the_missing_column(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        engine = _sqlite_engine()
        _make_sessions_table(engine, "id INTEGER PRIMARY KEY, market_user_id INTEGER")
        ensure_sessions_enterprise_entitlement_columns(engine)
        cols = _column_names(engine, "sessions")
        # market_user_id stayed; only entitled_mod_ids_json was added.
        assert "market_user_id" in cols
        assert "entitled_mod_ids_json" in cols

    def test_postgresql_emits_if_not_exists_for_both(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        insp = Mock()
        insp.get_table_names.return_value = ["sessions"]
        insp.get_columns.return_value = [{"name": "id"}]
        captured = _capture_pg_ddl(mock_engine)

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            ensure_sessions_enterprise_entitlement_columns(None, database_url="postgresql://test")

        assert captured == [
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS market_user_id INTEGER",
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS entitled_mod_ids_json TEXT",
        ]

    def test_no_sessions_table_is_noop(self):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        engine = _sqlite_engine()
        ensure_sessions_enterprise_entitlement_columns(engine)
        assert "sessions" not in _table_names(engine)


# ===== ensure_sessions_account_meta_columns ================================ #

# Order/type of the 8 account-meta columns added by init_db.py.
_ACCOUNT_META_COLS = [
    "account_kind",
    "company_brand",
    "market_is_admin",
    "market_is_enterprise",
    "impersonating_market_user_id",
    "impersonating_username",
    "tenant_id",
    "market_membership_tier",
]


class TestEnsureSessionsAccountMetaColumns:
    def test_real_sqlite_adds_all_eight_columns_with_defaults(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        engine = _sqlite_engine()
        _make_sessions_table(engine, "id INTEGER PRIMARY KEY")
        ensure_sessions_account_meta_columns(engine)
        cols = _column_names(engine, "sessions")
        for name in _ACCOUNT_META_COLS:
            assert name in cols, f"{name} should have been added"

        # Defaults are applied: a freshly inserted row gets account_kind='enterprise'.
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO sessions (id) VALUES (1)"))
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT account_kind, market_is_admin FROM sessions WHERE id=1")
            ).fetchone()
        assert row[0] == "enterprise"

    def test_postgresql_skips_present_columns_and_uses_if_not_exists(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        insp = Mock()
        insp.get_table_names.return_value = ["sessions"]
        # account_kind already present -> must be skipped via `continue`.
        insp.get_columns.return_value = [{"name": "id"}, {"name": "account_kind"}]
        captured = _capture_pg_ddl(mock_engine)

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            ensure_sessions_account_meta_columns(None, database_url="postgresql://test")

        # 7 of 8 ALTERs emitted (account_kind skipped), all IF NOT EXISTS form.
        assert len(captured) == 7
        assert all(s.startswith("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS") for s in captured)
        assert not any("account_kind" in s for s in captured)
        assert (
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS company_brand VARCHAR(256) DEFAULT ''"
            in captured
        )

    def test_all_columns_present_emits_no_alter(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        insp = Mock()
        insp.get_table_names.return_value = ["sessions"]
        insp.get_columns.return_value = [{"name": "id"}] + [{"name": n} for n in _ACCOUNT_META_COLS]
        captured = _capture_pg_ddl(mock_engine)

        with (
            patch("app.db._create_engine_for_url", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            ensure_sessions_account_meta_columns(None, database_url="sqlite:///test.db")

        # begin() entered but every column is skipped -> zero execute() statements.
        assert captured == []

    def test_no_sessions_table_is_noop(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        engine = _sqlite_engine()
        ensure_sessions_account_meta_columns(engine)
        assert "sessions" not in _table_names(engine)


# ===== ensure_user_preferences_bootstrap =================================== #


class TestEnsureUserPreferencesBootstrap:
    def test_creates_real_table_when_missing_regardless_of_dialect(self):
        # This helper has NO dialect gate: with a non-None engine and the table
        # absent it always creates user_preferences. Use a real SQLite engine
        # and assert the table actually materialises.
        from app.db.init_db import ensure_user_preferences_bootstrap

        engine = _sqlite_engine()
        with patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=engine):
            ensure_user_preferences_bootstrap(engine)
        assert "user_preferences" in _table_names(engine)

    def test_table_already_exists_no_recreate(self):
        from app.db.init_db import ensure_user_preferences_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        insp = Mock()
        insp.get_table_names.return_value = ["user_preferences"]
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", return_value=insp),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_user_preferences_bootstrap(mock_engine)
        mock_create.assert_not_called()

    def test_none_engine_is_noop(self):
        from app.db.init_db import ensure_user_preferences_bootstrap

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=None),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_user_preferences_bootstrap(None)
        mock_create.assert_not_called()

    def test_swallow_errors_true_suppresses_recoverable_error(self):
        from app.db.init_db import ensure_user_preferences_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_user_preferences_bootstrap(None, swallow_errors=True)
        mock_create.assert_not_called()

    def test_swallow_errors_false_propagates(self):
        from app.db.init_db import ensure_user_preferences_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
        ):
            with pytest.raises(RuntimeError, match="inspect failed"):
                ensure_user_preferences_bootstrap(None, swallow_errors=False)


# ===== ensure_runtime_auth_bootstrap ====================================== #


class TestEnsureRuntimeAuthBootstrap:
    def test_empty_url_runs_no_branch(self):
        from app.db.init_db import ensure_runtime_auth_bootstrap

        with (
            patch("app.fastapi_app.sqlite_paths.resolve_effective_database_url", return_value=""),
            patch("app.db.init_db.ensure_sqlite_auth_bootstrap") as mock_sqlite,
            patch("app.db.init_db.ensure_postgresql_auth_bootstrap") as mock_pg,
        ):
            ensure_runtime_auth_bootstrap(None)
        mock_sqlite.assert_not_called()
        mock_pg.assert_not_called()

    def test_sqlite_url_fans_out_to_six_sqlite_helpers(self):
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
            patch("app.db.init_db.ensure_sqlite_enterprise_business_bootstrap") as mock_ent,
            patch("app.db.init_db.ensure_user_preferences_bootstrap") as mock_pref,
            patch("app.db.init_db.ensure_neuro_event_log_bootstrap") as mock_neuro,
            # postgres helper must NOT be reached on a sqlite url.
            patch("app.db.init_db.ensure_postgresql_auth_bootstrap") as mock_pg,
        ):
            ensure_runtime_auth_bootstrap(None)
        mock_auth.assert_called_once()
        mock_rbac.assert_called_once()
        mock_inv.assert_called_once()
        mock_ent.assert_called_once()
        mock_pref.assert_called_once()
        mock_neuro.assert_called_once()
        mock_pg.assert_not_called()
        # The resolved sqlite url is threaded through to each helper.
        assert mock_auth.call_args.kwargs["database_url"] == "sqlite:///test.db"

    def test_postgresql_url_fans_out_to_three_pg_helpers(self):
        from app.db.init_db import ensure_runtime_auth_bootstrap

        with (
            patch(
                "app.fastapi_app.sqlite_paths.resolve_effective_database_url",
                return_value="postgresql://test",
            ),
            patch("app.fastapi_app.sqlite_paths.is_sqlite_url", return_value=False),
            patch("app.db.init_db.ensure_postgresql_auth_bootstrap") as mock_pg,
            patch("app.db.init_db.ensure_user_preferences_bootstrap") as mock_pref,
            patch("app.db.init_db.ensure_neuro_event_log_bootstrap") as mock_neuro,
            patch("app.db.init_db.ensure_sqlite_auth_bootstrap") as mock_sqlite,
        ):
            ensure_runtime_auth_bootstrap(None)
        mock_pg.assert_called_once()
        mock_pref.assert_called_once()
        mock_neuro.assert_called_once()
        # sqlite helper must NOT be reached on a postgres url.
        mock_sqlite.assert_not_called()


# ===== _seed_sqlite_rbac_defaults ========================================= #


class TestSeedSqliteRbacDefaults:
    def test_existing_permissions_short_circuit_no_seed(self):
        from app.db.init_db import _seed_sqlite_rbac_defaults

        engine = _sqlite_engine()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE permissions (id INTEGER PRIMARY KEY, name TEXT, code TEXT, "
                    "description TEXT, module TEXT)"
                )
            )
            conn.execute(text("INSERT INTO permissions (name, code) VALUES ('test', 'test')"))

        # Even though DEFAULT_PERMISSIONS is non-empty, an existing row means the
        # seeding is skipped entirely.
        _seed_sqlite_rbac_defaults(engine)

        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM permissions")).scalar()
            codes = [r[0] for r in conn.execute(text("SELECT code FROM permissions")).fetchall()]
        assert count == 1
        assert codes == ["test"]  # the pre-existing row, untouched

    def test_full_bootstrap_seeds_default_permissions_and_roles(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap
        from app.db.models.permission import DEFAULT_PERMISSIONS, DEFAULT_ROLES

        engine = _sqlite_engine()
        with patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=engine):
            ensure_sqlite_rbac_bootstrap(engine)

        with engine.connect() as conn:
            perm_count = conn.execute(text("SELECT COUNT(*) FROM permissions")).scalar()
            role_count = conn.execute(text("SELECT COUNT(*) FROM roles")).scalar()
            codes = {r[0] for r in conn.execute(text("SELECT code FROM permissions")).fetchall()}
            role_names = {r[0] for r in conn.execute(text("SELECT name FROM roles")).fetchall()}
        assert perm_count == len(DEFAULT_PERMISSIONS)
        assert role_count == len(DEFAULT_ROLES)
        assert "customer.view" in codes
        assert {"viewer", "operator", "admin"}.issubset(role_names)


# ===== init_im_tables ===================================================== #


class TestInitImTables:
    def test_creates_all_three_im_tables(self):
        from app.db.init_db import init_im_tables

        engine = _sqlite_engine()
        init_im_tables(engine)
        tables = _table_names(engine)
        assert {"im_conversations", "im_conversation_members", "im_messages"}.issubset(tables)
        # message table carries the expected core columns.
        msg_cols = _column_names(engine, "im_messages")
        assert {"conversation_id", "sender_user_id", "body"}.issubset(msg_cols)

    def test_idempotent_second_call_keeps_tables(self):
        from app.db.init_db import init_im_tables

        engine = _sqlite_engine()
        init_im_tables(engine)
        init_im_tables(engine)  # checkfirst=True -> no raise
        tables = _table_names(engine)
        assert {"im_conversations", "im_conversation_members", "im_messages"}.issubset(tables)


# ===== init_approval_tables =============================================== #


class TestInitApprovalTables:
    def test_creates_approval_tables_with_business_type_column(self):
        from app.db.init_db import init_approval_tables

        engine = _sqlite_engine()
        with patch("app.db._get_engine", return_value=engine):
            init_approval_tables(engine)
        tables = _table_names(engine)
        assert {"approval_flows", "approval_requests"}.issubset(tables)
        # fresh ORM-created table already has business_type.
        assert "business_type" in _column_names(engine, "approval_flows")

    def test_adds_business_type_column_to_legacy_table(self):
        from app.db.init_db import init_approval_tables

        engine = _sqlite_engine()
        # legacy approval_flows without business_type.
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE approval_flows (id INTEGER PRIMARY KEY, name TEXT)"))

        with patch("app.db._get_engine", return_value=engine):
            init_approval_tables(engine)

        cols = _column_names(engine, "approval_flows")
        assert "business_type" in cols
        # default applied for new rows.
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO approval_flows (id, name) VALUES (1, 'x')"))
        with engine.connect() as conn:
            bt = conn.execute(text("SELECT business_type FROM approval_flows WHERE id=1")).scalar()
        assert bt == "general"


# ===== ensure_product_query_indexes ====================================== #


class TestEnsureProductQueryIndexes:
    def test_no_products_table_creates_no_indexes(self):
        from app.db.init_db import ensure_product_query_indexes

        engine = _sqlite_engine()
        ensure_product_query_indexes(engine)
        indexes = _index_names(engine)
        assert "ix_products_unit" not in indexes
        assert "ix_products_model_number" not in indexes

    def test_creates_both_query_indexes(self):
        from app.db.init_db import ensure_product_query_indexes

        engine = _sqlite_engine()
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE products (id INTEGER PRIMARY KEY, unit TEXT, model_number TEXT)")
            )
        ensure_product_query_indexes(engine)
        indexes = _index_names(engine)
        assert "ix_products_unit" in indexes
        assert "ix_products_model_number" in indexes

    def test_idempotent_when_indexes_exist(self):
        from app.db.init_db import ensure_product_query_indexes

        engine = _sqlite_engine()
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE products (id INTEGER PRIMARY KEY, unit TEXT, model_number TEXT)")
            )
        ensure_product_query_indexes(engine)
        # second call uses IF NOT EXISTS -> no error, both indexes still present.
        ensure_product_query_indexes(engine)
        indexes = _index_names(engine)
        assert {"ix_products_unit", "ix_products_model_number"}.issubset(indexes)


# ===== init_service_bridge_tables ======================================== #


class TestInitServiceBridgeTables:
    def test_creates_service_bridge_tables(self):
        from app.db.init_db import init_service_bridge_tables

        engine = _sqlite_engine()
        with patch("app.db._get_engine", return_value=engine):
            init_service_bridge_tables(engine)
        tables = _table_names(engine)
        assert "service_requests" in tables
        assert "service_bridge_config" in tables


# ===== _resolve_auth_bootstrap_engine ==================================== #


class TestResolveAuthBootstrapEngine:
    def test_url_creation_failure_with_non_engine_falls_back_to_get_engine(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db._create_engine_for_url", side_effect=RuntimeError("bad url")),
            patch("app.db._get_engine", return_value=mock_engine) as mock_get,
        ):
            result = _resolve_auth_bootstrap_engine("not_an_engine", database_url="bad://url")
        assert result is mock_engine
        mock_get.assert_called_once()

    def test_real_engine_param_is_used_when_url_creation_fails(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        real_engine = _sqlite_engine()
        with patch("app.db._create_engine_for_url", side_effect=RuntimeError("bad url")):
            result = _resolve_auth_bootstrap_engine(real_engine, database_url="bad://url")
        # A real Engine instance is accepted directly without consulting _get_engine.
        assert result is real_engine

    def test_url_wins_over_engine_param(self):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        url_engine = _sqlite_engine()
        other_engine = _sqlite_engine()
        with patch("app.db._create_engine_for_url", return_value=url_engine) as mock_create:
            result = _resolve_auth_bootstrap_engine(other_engine, database_url="sqlite:///x.db")
        assert result is url_engine
        mock_create.assert_called_once_with("sqlite:///x.db")


# ===== build_mod_database_seed_plan ====================================== #


class TestBuildModDatabaseSeedPlan:
    def _meta(self, mod_id, mod_path):
        m = Mock()
        m.id = mod_id
        m.mod_path = mod_path
        return m

    def test_mod_with_seed_files_yields_mother_per_mod_and_extra_seeds(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        (mod_dir / "seed.sql").write_text("-- seed sql")
        (mod_dir / "data.db").write_bytes(b"")
        manifest = {
            "id": "test_mod",
            "database": {
                "notes_zh": "测试库",
                "seed_files": ["data.db"],
                "seed_sql": "seed.sql",
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
            mock_mm.return_value.list_loaded_mods.return_value = [
                self._meta("test_mod", str(mod_dir))
            ]
            result = build_mod_database_seed_plan()

        assert len(result["mods"]) == 1
        entry = result["mods"][0]
        assert entry["mod_id"] == "test_mod"
        assert entry["database_notes"] == "测试库"
        roles = [s.get("role") for s in entry["seeds"]]
        assert "sqlite_mother_products" in roles
        assert "sqlite_per_mod_products" in roles
        # data.db + seed.sql appended as extra seeds (role-less path entries).
        seed_paths = [s["path"] for s in entry["seeds"]]
        assert any(p.endswith("data.db") for p in seed_paths)
        assert any(p.endswith("seed.sql") for p in seed_paths)

    def test_invalid_manifest_json_swallowed_notes_empty(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

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
            mock_mm.return_value.list_loaded_mods.return_value = [
                self._meta("test_mod", str(mod_dir))
            ]
            result = build_mod_database_seed_plan()

        # JSON decode error is swallowed -> mod still listed but with empty notes
        # and only the two default (mother/per-mod) seeds.
        assert len(result["mods"]) == 1
        entry = result["mods"][0]
        assert entry["database_notes"] == ""
        assert len(entry["seeds"]) == 2

    def test_empty_mod_id_is_skipped(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch(
                "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
                side_effect=lambda n, m: f"products__{m}.db",
            ),
        ):
            mock_mm.return_value.list_loaded_mods.return_value = [self._meta("", "")]
            result = build_mod_database_seed_plan()
        assert result["mods"] == []
        # architecture note is always present.
        assert "architecture_note_zh" in result

    def test_non_list_seed_files_ignored(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        manifest = {"id": "test_mod", "database": {"seed_files": "not_a_list"}}
        (mod_dir / "manifest.json").write_text(json.dumps(manifest))

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch("app.infrastructure.mods.mod_manager.get_mod_manager") as mock_mm,
            patch(
                "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
                side_effect=lambda n, m: f"products__{m}.db",
            ),
        ):
            mock_mm.return_value.list_loaded_mods.return_value = [
                self._meta("test_mod", str(mod_dir))
            ]
            result = build_mod_database_seed_plan()

        # invalid seed_files type -> no extra seeds, only the two defaults.
        assert len(result["mods"]) == 1
        assert len(result["mods"][0]["seeds"]) == 2

    def test_top_level_database_keys_used_as_fallback(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

        mod_dir = tmp_path / "test_mod"
        mod_dir.mkdir()
        (mod_dir / "data.db").write_bytes(b"")
        manifest = {
            "id": "test_mod",
            "database_seed_files": ["data.db"],
            "database_notes_zh": "top level notes",
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
            mock_mm.return_value.list_loaded_mods.return_value = [
                self._meta("test_mod", str(mod_dir))
            ]
            result = build_mod_database_seed_plan()

        assert len(result["mods"]) == 1
        entry = result["mods"][0]
        # top-level database_notes_zh / database_seed_files honoured.
        assert entry["database_notes"] == "top level notes"
        assert any(s["path"].endswith("data.db") for s in entry["seeds"])

    def test_mod_manager_failure_yields_no_mods(self, tmp_path):
        from app.db.init_db import build_mod_database_seed_plan

        with (
            patch("app.db.init_db.get_app_data_dir", return_value=str(tmp_path)),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=RuntimeError("mod manager down"),
            ),
        ):
            result = build_mod_database_seed_plan()
        # recoverable error -> metas defaults to [] -> no mods, note still present.
        assert result["mods"] == []
        assert result["architecture_note_zh"]


# ===== ensure_sqlite_rbac_bootstrap ====================================== #


class TestEnsureSqliteRbacBootstrap:
    def test_creates_rbac_tables_when_missing(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        engine = _sqlite_engine()
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=engine),
            # isolate table creation from the seeding step.
            patch("app.db.init_db._seed_sqlite_rbac_defaults"),
        ):
            ensure_sqlite_rbac_bootstrap(engine)
        tables = _table_names(engine)
        assert {"permissions", "roles", "role_permissions"}.issubset(tables)

    def test_swallow_errors_true_skips_seeding(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
            patch("app.db.init_db._seed_sqlite_rbac_defaults") as mock_seed,
        ):
            ensure_sqlite_rbac_bootstrap(None, swallow_errors=True)
        mock_seed.assert_not_called()

    def test_swallow_errors_false_propagates(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
        ):
            with pytest.raises(RuntimeError, match="inspect failed"):
                ensure_sqlite_rbac_bootstrap(None, swallow_errors=False)

    def test_non_sqlite_dialect_is_noop(self):
        from app.db.init_db import ensure_sqlite_rbac_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("app.db.init_db._seed_sqlite_rbac_defaults") as mock_seed,
        ):
            ensure_sqlite_rbac_bootstrap(mock_engine)
        # dialect gate: postgres -> nothing seeded by the sqlite-only helper.
        mock_seed.assert_not_called()


# ===== ensure_sqlite_inventory_bootstrap ================================= #


class TestEnsureSqliteInventoryBootstrap:
    def test_creates_inventory_tables_when_missing(self):
        from app.db.init_db import ensure_sqlite_inventory_bootstrap

        engine = _sqlite_engine()
        with patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=engine):
            ensure_sqlite_inventory_bootstrap(engine)
        assert "warehouses" in _table_names(engine)

    def test_swallow_errors_true_no_create(self):
        from app.db.init_db import ensure_sqlite_inventory_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_sqlite_inventory_bootstrap(None, swallow_errors=True)
        mock_create.assert_not_called()

    def test_swallow_errors_false_propagates(self):
        from app.db.init_db import ensure_sqlite_inventory_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
        ):
            with pytest.raises(RuntimeError, match="inspect failed"):
                ensure_sqlite_inventory_bootstrap(None, swallow_errors=False)


# ===== ensure_sqlite_auth_bootstrap ====================================== #


class TestEnsureSqliteAuthBootstrap:
    def test_creates_users_sessions_and_seeds_admin_on_empty_db(self):
        from app.db.init_db import ensure_sqlite_auth_bootstrap

        engine = _sqlite_engine()
        with patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=engine):
            ensure_sqlite_auth_bootstrap(engine)

        tables = _table_names(engine)
        assert {"users", "sessions"}.issubset(tables)
        # real admin row seeded with the documented defaults.
        with engine.connect() as conn:
            row = conn.execute(text("SELECT username, role, tier, is_active FROM users")).fetchone()
        assert row[0] == "admin"
        assert row[1] == "admin"
        assert row[2] == "admin"
        assert bool(row[3]) is True

    def test_seeds_only_once_when_users_already_populated(self):
        from app.db.init_db import ensure_sqlite_auth_bootstrap

        engine = _sqlite_engine()
        # First call seeds admin.
        with patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=engine):
            ensure_sqlite_auth_bootstrap(engine)
            # Second call: tables exist and users non-empty -> no duplicate admin.
            ensure_sqlite_auth_bootstrap(engine)

        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM users WHERE username='admin'")).scalar()
        assert count == 1

    def test_non_sqlite_dialect_is_noop(self):
        from app.db.init_db import ensure_sqlite_auth_bootstrap

        mock_engine = Mock()
        mock_engine.dialect.name = "postgresql"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=mock_engine),
            patch("app.db.init_db._seed_default_admin_user") as mock_seed,
        ):
            ensure_sqlite_auth_bootstrap(mock_engine)
        mock_seed.assert_not_called()
