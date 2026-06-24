"""Behavioral tests for app.db.init_db schema-bootstrap / column-ensure helpers.

These exercise the ``ensure_*`` column helpers, the ``init_*`` table helpers, the
engine-resolution branches (``_create_engine_for_url`` / ``_get_engine`` /
``_resolve_auth_bootstrap_engine``) and the trailing ``except RECOVERABLE_ERRORS``
swallow paths.

Design principles (behavioral, not smoke):

* **Success paths use a real in-memory SQLite engine** and assert the *exact*
  resulting schema (column names + the concrete ``DEFAULT`` values the ALTER
  statements stamp onto existing rows). The observable behavior under test is the
  DDL the helper emits — we read it back from the real database.
* **Swallow paths use a real engine pointed at an unwritable path** so a genuine
  ``sqlite3.OperationalError`` (a member of ``RECOVERABLE_ERRORS``) is raised by
  the real driver — not a mocked ``inspect``/``begin``. We assert the helper
  returns ``None`` without propagating, and (where the helper exposes
  ``swallow_errors``) that ``swallow_errors=False`` re-raises the *same* real error.
* Engine-resolution branches are the only place we mock ``app.db._create_engine_for_url``
  / ``app.db._get_engine`` — that is the genuine external "where do I get an engine"
  dependency. We still assert on the *resulting schema*, not on the mock.

Nothing connects to a real server database; everything is in-memory SQLite.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

# A path under a directory that does not exist -> sqlite3 "unable to open
# database file" the moment any connection is attempted. This drives the real
# RECOVERABLE_ERRORS swallow branch without mocking inspect()/begin().
_UNWRITABLE_URL = "sqlite:////nonexistent_dir_init_db_cov90/db.sqlite"


def _broken_engine() -> object:
    """Real engine whose every connection attempt raises OperationalError."""
    return create_engine(_UNWRITABLE_URL)


def _sqlite_engine_with_sessions() -> object:
    """Real in-memory SQLite engine with a minimal (legacy) ``sessions`` table."""
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id VARCHAR NOT NULL,
                    user_id INTEGER NOT NULL,
                    expires_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        # one row, so DEFAULT clauses on added columns are observable.
        conn.execute(
            text(
                "INSERT INTO sessions (session_id, user_id, expires_at) "
                "VALUES ('s1', 1, '2020-01-01')"
            )
        )
    return eng


def _sqlite_engine_with_users() -> object:
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR)"))
        conn.execute(text("INSERT INTO users (username) VALUES ('alice')"))
    return eng


def _columns(eng: object, table: str) -> set[str]:
    with eng.connect() as conn:  # type: ignore[attr-defined]
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def _table_names(eng: object) -> set[str]:
    with eng.connect() as conn:  # type: ignore[attr-defined]
        return {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }


def _index_names(eng: object) -> set[str]:
    with eng.connect() as conn:  # type: ignore[attr-defined]
        return {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
        }


# ===========================================================================
# _create_engine_for_url failure -> _get_engine fallback also raises -> return
# ===========================================================================


class TestCreateEngineFailureFallbacks:
    """url given but _create_engine_for_url raises, no engine arg, and _get_engine
    also raises -> the helper returns None silently (recoverable-error fallback)."""

    @pytest.mark.parametrize(
        "func_name",
        [
            "ensure_sessions_market_refresh_token_column",
            "ensure_sessions_enterprise_entitlement_columns",
            "ensure_sessions_account_meta_columns",
            "ensure_users_tenant_id_column",
            "ensure_business_tenant_id_columns",
            "ensure_user_profile_columns",
        ],
    )
    def test_create_engine_error_then_get_engine_fallback_returns_none(self, func_name):
        import app.db.init_db as init_db

        func = getattr(init_db, func_name)
        get_engine_mock = MagicMock(side_effect=ImportError("no real engine"))
        with (
            patch("app.db._create_engine_for_url", side_effect=RuntimeError("bad url")),
            patch("app.db._get_engine", get_engine_mock),
        ):
            result = func(None, database_url="postgresql://bad")

        # contract: no engine resolvable -> silent None return, no propagation.
        assert result is None
        # the no-engine fallback was actually reached (it raised -> early return).
        get_engine_mock.assert_called_once()


# ===========================================================================
# ensure_sessions_market_refresh_token_column
# ===========================================================================


class TestMarketRefreshTokenColumn:
    def test_adds_refresh_token_column_via_database_url(self):
        """url branch -> _create_engine_for_url(url) -> column actually appended."""
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        eng = _sqlite_engine_with_sessions()
        with patch("app.db._create_engine_for_url", return_value=eng) as mock_create:
            ensure_sessions_market_refresh_token_column(None, database_url="sqlite:///x")

        mock_create.assert_called_once_with("sqlite:///x")
        assert "market_refresh_token" in _columns(eng, "sessions")

    def test_idempotent_when_column_present(self):
        """Column already present -> early return, table left exactly as-is."""
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        eng = _sqlite_engine_with_sessions()
        with eng.begin() as conn:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN market_refresh_token TEXT"))
        before = _columns(eng, "sessions")

        ensure_sessions_market_refresh_token_column(eng)

        assert _columns(eng, "sessions") == before  # unchanged

    def test_no_sessions_table_returns_without_creating(self):
        """sessions table absent -> early return, nothing created."""
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        eng = create_engine("sqlite:///:memory:")  # empty db, no sessions table
        ensure_sessions_market_refresh_token_column(eng)
        assert "sessions" not in _table_names(eng)

    def test_alter_failure_emits_correct_ddl_then_swallows(self):
        """ALTER raises recoverable error -> the correct DDL was attempted, then swallowed."""
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        captured: list[str] = []
        conn = eng.begin.return_value.__enter__.return_value

        def _exec(stmt, *a, **k):
            captured.append(str(stmt))
            raise OperationalError("ALTER", {}, Exception("alter boom"))

        conn.execute.side_effect = _exec
        insp = MagicMock()
        insp.get_table_names.return_value = ["sessions"]
        insp.get_columns.return_value = [{"name": "id"}]  # column missing -> ALTER

        with (
            patch("app.db._create_engine_for_url", return_value=eng),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            result = ensure_sessions_market_refresh_token_column(None, database_url="sqlite:///x")

        # behavior under test: the exact DDL the helper generates, and the swallow.
        assert captured == ["ALTER TABLE sessions ADD COLUMN market_refresh_token TEXT"]
        assert result is None


# ===========================================================================
# ensure_sessions_enterprise_entitlement_columns
# ===========================================================================


class TestEnterpriseEntitlementColumns:
    def test_get_engine_fallback_adds_exact_columns(self):
        """No url + no engine -> _get_engine() supplies the engine; two columns added."""
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = _sqlite_engine_with_sessions()
        with patch("app.db._get_engine", return_value=eng) as mock_get:
            ensure_sessions_enterprise_entitlement_columns(None, database_url=None)

        mock_get.assert_called_once()
        cols = _columns(eng, "sessions")
        assert {"market_user_id", "entitled_mod_ids_json"}.issubset(cols)

    def test_only_missing_column_added(self):
        """One of the two columns already present -> only the other is appended."""
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = _sqlite_engine_with_sessions()
        with eng.begin() as conn:
            conn.execute(text("ALTER TABLE sessions ADD COLUMN market_user_id INTEGER"))

        ensure_sessions_enterprise_entitlement_columns(eng)

        cols = _columns(eng, "sessions")
        assert "entitled_mod_ids_json" in cols
        assert "market_user_id" in cols

    def test_unwritable_engine_failure_is_swallowed(self):
        """Real driver OperationalError (inspect) -> swallowed, returns None."""
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        assert ensure_sessions_enterprise_entitlement_columns(_broken_engine()) is None


# ===========================================================================
# ensure_sessions_account_meta_columns
# ===========================================================================


class TestSessionsAccountMetaColumns:
    def test_get_engine_fallback_adds_all_meta_columns_with_defaults(self):
        """Fallback engine -> all 8 meta columns added, with the documented DEFAULTs."""
        from app.db.init_db import ensure_sessions_account_meta_columns

        eng = _sqlite_engine_with_sessions()
        with patch("app.db._get_engine", return_value=eng):
            ensure_sessions_account_meta_columns(None, database_url=None)

        cols = _columns(eng, "sessions")
        expected = {
            "account_kind",
            "company_brand",
            "market_is_admin",
            "market_is_enterprise",
            "impersonating_market_user_id",
            "impersonating_username",
            "tenant_id",
            "market_membership_tier",
        }
        assert expected.issubset(cols)

        # DEFAULT clauses are stamped onto the pre-existing row.
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT account_kind, company_brand, market_membership_tier FROM sessions")
            ).fetchone()
        assert row[0] == "enterprise"  # account_kind DEFAULT 'enterprise'
        assert row[1] == ""  # company_brand DEFAULT ''
        assert row[2] is None  # market_membership_tier has no default

    def test_unwritable_engine_failure_is_swallowed(self):
        from app.db.init_db import ensure_sessions_account_meta_columns

        assert ensure_sessions_account_meta_columns(_broken_engine()) is None


# ===========================================================================
# ensure_users_tenant_id_column
# ===========================================================================


class TestUsersTenantIdColumn:
    def test_get_engine_fallback_adds_column(self):
        from app.db.init_db import ensure_users_tenant_id_column

        eng = _sqlite_engine_with_users()
        with patch("app.db._get_engine", return_value=eng) as mock_get:
            ensure_users_tenant_id_column(None, database_url=None)

        mock_get.assert_called_once()
        assert "tenant_id" in _columns(eng, "users")

    def test_no_users_table_returns_without_alter(self):
        """users table absent -> early return, nothing created."""
        from app.db.init_db import ensure_users_tenant_id_column

        eng = create_engine("sqlite:///:memory:")  # empty db, no `users`
        ensure_users_tenant_id_column(eng)
        assert "users" not in _table_names(eng)

    def test_unwritable_engine_failure_is_swallowed(self):
        from app.db.init_db import ensure_users_tenant_id_column

        assert ensure_users_tenant_id_column(_broken_engine()) is None


# ===========================================================================
# ensure_business_tenant_id_columns
# ===========================================================================


class TestBusinessTenantIdColumns:
    def test_get_engine_fallback_adds_tenant_id_only_to_existing_tables(self):
        """Only business tables that exist get tenant_id; absent ones are skipped."""
        from app.db.init_db import ensure_business_tenant_id_columns

        eng = create_engine("sqlite:///:memory:")
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, name VARCHAR)"))
            conn.execute(text("CREATE TABLE materials (id INTEGER PRIMARY KEY)"))
            # suppliers intentionally absent

        with patch("app.db._get_engine", return_value=eng):
            ensure_business_tenant_id_columns(None, database_url=None)

        assert "tenant_id" in _columns(eng, "products")
        assert "tenant_id" in _columns(eng, "materials")
        assert "suppliers" not in _table_names(eng)  # not auto-created

    def test_skips_table_that_already_has_tenant_id(self):
        """products already has tenant_id -> no duplicate-column error, stays valid."""
        from app.db.init_db import ensure_business_tenant_id_columns

        eng = create_engine("sqlite:///:memory:")
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, tenant_id INTEGER)"))

        ensure_business_tenant_id_columns(eng)  # must not raise on existing column

        # PRAGMA returns each column once; tenant_id must not be duplicated.
        with eng.connect() as conn:
            names = [row[1] for row in conn.execute(text("PRAGMA table_info(products)"))]
        assert names.count("tenant_id") == 1

    def test_unwritable_engine_failure_is_swallowed(self):
        from app.db.init_db import ensure_business_tenant_id_columns

        assert ensure_business_tenant_id_columns(_broken_engine()) is None


# ===========================================================================
# ensure_user_profile_columns
# ===========================================================================


class TestUserProfileColumns:
    def test_get_engine_fallback_adds_all_profile_columns_with_defaults(self):
        from app.db.init_db import ensure_user_profile_columns

        eng = _sqlite_engine_with_users()
        with patch("app.db._get_engine", return_value=eng):
            ensure_user_profile_columns(None, database_url=None)

        cols = _columns(eng, "users")
        expected = {
            "tier",
            "industry_id",
            "account_tier",
            "budget_range",
            "entitled_industries",
            "failed_login_attempts",
            "locked_until",
            "email_verified",
        }
        assert expected.issubset(cols)

        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT tier, industry_id, failed_login_attempts FROM users")
            ).fetchone()
        assert row[0] == "personal"  # tier DEFAULT 'personal'
        assert row[1] == "通用"  # industry_id DEFAULT '通用'
        assert row[2] == 0  # failed_login_attempts DEFAULT 0

    def test_unwritable_engine_failure_is_swallowed(self):
        from app.db.init_db import ensure_user_profile_columns

        assert ensure_user_profile_columns(_broken_engine()) is None


# ===========================================================================
# ensure_neuro_event_log_bootstrap
# ===========================================================================


class TestEnsureNeuroEventLogBootstrap:
    def test_none_engine_returns_without_creating(self):
        """No resolvable engine -> early return; create_all never invoked."""
        from app.db.init_db import ensure_neuro_event_log_bootstrap

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=None),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            result = ensure_neuro_event_log_bootstrap(None)

        assert result is None
        mock_create.assert_not_called()

    def test_creates_table_on_real_engine_when_missing(self):
        """Real empty engine -> neuro_event_log table is actually created."""
        from app.db.init_db import ensure_neuro_event_log_bootstrap

        eng = create_engine("sqlite:///:memory:")
        ensure_neuro_event_log_bootstrap(eng)
        assert "neuro_event_log" in _table_names(eng)

    def test_idempotent_when_table_already_present(self):
        """Second call is a no-op create_all (checkfirst) and does not error."""
        from app.db.init_db import ensure_neuro_event_log_bootstrap

        eng = create_engine("sqlite:///:memory:")
        ensure_neuro_event_log_bootstrap(eng)
        before = _table_names(eng)

        ensure_neuro_event_log_bootstrap(eng)  # again

        assert _table_names(eng) == before
        assert "neuro_event_log" in before

    def test_swallow_errors_false_reraises_real_operational_error(self):
        """Real driver error + swallow_errors=False -> propagates OperationalError."""
        from app.db.init_db import ensure_neuro_event_log_bootstrap

        with pytest.raises(OperationalError):
            ensure_neuro_event_log_bootstrap(_broken_engine(), swallow_errors=False)

    def test_swallow_errors_true_swallows_real_operational_error(self):
        from app.db.init_db import ensure_neuro_event_log_bootstrap

        assert ensure_neuro_event_log_bootstrap(_broken_engine(), swallow_errors=True) is None


# ===========================================================================
# ensure_sqlite_enterprise_business_bootstrap
# ===========================================================================


class TestEnsureSqliteEnterpriseBusinessBootstrap:
    def test_non_sqlite_dialect_is_skipped(self):
        """Non-sqlite dialect -> early return; no ORM create_all."""
        from app.db.init_db import ensure_sqlite_enterprise_business_bootstrap

        eng = MagicMock()
        eng.dialect.name = "postgresql"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            result = ensure_sqlite_enterprise_business_bootstrap(eng)

        assert result is None
        mock_create.assert_not_called()

    def test_creates_business_tables_on_real_engine(self):
        from app.db.init_db import ensure_sqlite_enterprise_business_bootstrap

        eng = create_engine("sqlite:///:memory:")
        ensure_sqlite_enterprise_business_bootstrap(eng)
        assert {"tenants", "customers", "products"}.issubset(_table_names(eng))

    def test_swallow_errors_false_reraises_real_operational_error(self):
        from app.db.init_db import ensure_sqlite_enterprise_business_bootstrap

        with pytest.raises(OperationalError):
            ensure_sqlite_enterprise_business_bootstrap(_broken_engine(), swallow_errors=False)

    def test_swallow_errors_true_swallows_real_operational_error(self):
        from app.db.init_db import ensure_sqlite_enterprise_business_bootstrap

        assert (
            ensure_sqlite_enterprise_business_bootstrap(_broken_engine(), swallow_errors=True)
            is None
        )


# ===========================================================================
# init_im_tables — engine resolution branches
# ===========================================================================


class TestInitImTablesEngineResolution:
    def test_resolves_engine_from_database_url(self):
        """engine=None + database_url -> _create_engine_for_url(url) branch; tables made."""
        from app.db.init_db import init_im_tables

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db._create_engine_for_url", return_value=eng) as mock_create:
            init_im_tables(None, database_url="sqlite:///x")

        mock_create.assert_called_once_with("sqlite:///x")
        assert {
            "im_conversations",
            "im_conversation_members",
            "im_messages",
        }.issubset(_table_names(eng))

    def test_resolves_engine_from_get_engine(self):
        """engine=None + no url -> _get_engine() branch; tables made."""
        from app.db.init_db import init_im_tables

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db._get_engine", return_value=eng) as mock_get:
            init_im_tables(None, database_url=None)

        mock_get.assert_called_once()
        assert {
            "im_conversations",
            "im_conversation_members",
            "im_messages",
        }.issubset(_table_names(eng))

    def test_uses_passed_engine_without_resolution(self):
        """engine given -> neither resolver is consulted; tables still created."""
        from app.db.init_db import init_im_tables

        eng = create_engine("sqlite:///:memory:")
        with (
            patch("app.db._create_engine_for_url") as mock_create,
            patch("app.db._get_engine") as mock_get,
        ):
            init_im_tables(eng)

        mock_create.assert_not_called()
        mock_get.assert_not_called()
        assert "im_messages" in _table_names(eng)


# ===========================================================================
# ensure_product_query_indexes
# ===========================================================================


class TestEnsureProductQueryIndexes:
    def test_creates_both_indexes_on_real_products_table(self):
        from app.db.init_db import ensure_product_query_indexes

        eng = create_engine("sqlite:///:memory:")
        with eng.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE products (id INTEGER PRIMARY KEY, unit VARCHAR, "
                    "model_number VARCHAR)"
                )
            )

        ensure_product_query_indexes(eng)

        assert {"ix_products_unit", "ix_products_model_number"}.issubset(_index_names(eng))

    def test_no_products_table_creates_no_indexes(self):
        """products absent -> early return, no transaction, no indexes created."""
        from app.db.init_db import ensure_product_query_indexes

        eng = create_engine("sqlite:///:memory:")  # no products table
        ensure_product_query_indexes(eng)
        assert not any(i.startswith("ix_products_") for i in _index_names(eng))

    def test_inspect_failure_treated_as_no_products(self):
        """inspect raises recoverable error -> names=set() -> early return, no begin()."""
        from app.db.init_db import ensure_product_query_indexes

        eng = MagicMock()
        with patch("sqlalchemy.inspect", side_effect=OSError("inspect down")):
            result = ensure_product_query_indexes(eng)

        assert result is None
        eng.begin.assert_not_called()  # never opened a tx to build indexes

    def test_per_stmt_failure_attempts_both_then_swallows(self):
        """Each CREATE INDEX failure is caught individually; both DDLs attempted, no raise."""
        from app.db.init_db import ensure_product_query_indexes

        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]
        conn = eng.begin.return_value.__enter__.return_value
        executed: list[str] = []

        def _exec(stmt, *a, **k):
            executed.append(str(stmt))
            raise OperationalError("CREATE INDEX", {}, Exception("index boom"))

        conn.execute.side_effect = _exec
        with patch("sqlalchemy.inspect", return_value=insp):
            result = ensure_product_query_indexes(eng)

        assert result is None
        assert executed == [
            "CREATE INDEX IF NOT EXISTS ix_products_unit ON products (unit)",
            "CREATE INDEX IF NOT EXISTS ix_products_model_number ON products (model_number)",
        ]


# ===========================================================================
# init_approval_tables
# ===========================================================================


class TestInitApprovalTables:
    def test_creates_approval_tables_on_real_engine(self):
        from app.db.init_db import init_approval_tables

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db._get_engine", return_value=eng):
            init_approval_tables(eng)

        tables = _table_names(eng)
        assert {
            "approval_flows",
            "approval_flow_nodes",
            "approval_requests",
            "approval_records",
            "approval_delegations",
        }.issubset(tables)
        # business_type compat column is present on the freshly-created flow table.
        assert "business_type" in _columns(eng, "approval_flows")

    def test_post_create_inspect_failure_is_swallowed(self):
        """create_all succeeds, then inspect raises recoverable error -> no raise."""
        from app.db.init_db import init_approval_tables

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        with (
            patch("app.db._get_engine", return_value=eng),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect down")),
        ):
            result = init_approval_tables(eng)

        assert result is None
        mock_create.assert_called_once()  # create_all ran before the swallowed inspect


# ===========================================================================
# init_service_bridge_tables
# ===========================================================================


class TestInitServiceBridgeTables:
    def test_creates_service_tables_on_real_engine(self):
        from app.db.init_db import init_service_bridge_tables

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db._get_engine", return_value=eng):
            init_service_bridge_tables(eng)

        assert {"service_requests", "service_bridge_config"}.issubset(_table_names(eng))

    def test_create_all_failure_is_swallowed(self):
        """create_all raises recoverable error -> warning, no raise, returns None."""
        from app.db.init_db import init_service_bridge_tables

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        with (
            patch("app.db._get_engine", return_value=eng),
            patch(
                "app.db.base.Base.metadata.create_all",
                side_effect=OperationalError("create", {}, Exception("create boom")),
            ),
        ):
            result = init_service_bridge_tables(eng)

        assert result is None


# ===========================================================================
# init_persona_tables
# ===========================================================================


class TestInitPersonaTables:
    def test_creates_persona_tables_on_real_engine(self):
        from app.db.init_db import init_persona_tables

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db._get_engine", return_value=eng):
            init_persona_tables(eng)

        assert {"persona_profile", "persona_event_log"}.issubset(_table_names(eng))

    def test_get_engine_failure_falls_back_to_passed_engine(self):
        """_get_engine raises -> keep the passed engine and still create the tables."""
        from app.db.init_db import init_persona_tables

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db._get_engine", side_effect=RuntimeError("no real engine")):
            init_persona_tables(eng)

        assert "persona_profile" in _table_names(eng)

    def test_create_all_failure_is_swallowed(self):
        """create_all raises recoverable error -> warning, no raise, returns None."""
        from app.db.init_db import init_persona_tables

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        with (
            patch("app.db._get_engine", return_value=eng),
            patch(
                "app.db.base.Base.metadata.create_all",
                side_effect=OperationalError("create", {}, Exception("create boom")),
            ),
        ):
            result = init_persona_tables(eng)

        assert result is None
