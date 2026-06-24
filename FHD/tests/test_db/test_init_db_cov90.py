"""Targeted branch-coverage tests for app.db.init_db.

Focus: the still-uncovered *error / fallback* paths of the ``ensure_*`` column
helpers and the ``init_*`` table helpers — specifically:

* the ``_create_engine_for_url`` failure branch (logs a warning, engine stays None),
* the no-url / no-engine ``_get_engine`` fallback (raises a recoverable error → return),
* the trailing ``except RECOVERABLE_ERRORS`` warning branch around the DDL block,
* ``ensure_neuro_event_log_bootstrap`` (untested), ``ensure_sqlite_enterprise_business_bootstrap``
  swallow=False re-raise, ``init_im_tables`` engine resolution, ``ensure_product_query_indexes``
  inspect failure + per-stmt failure, and ``init_persona_tables`` create_all failure.

All DB/engine access is mocked — nothing connects to a real database. Functions
import ``_create_engine_for_url`` / ``_get_engine`` from ``app.db`` *inside their
bodies*, so we patch the attributes on the ``app.db`` module (the real import site).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text


def _sqlite_engine_with_sessions(extra_cols: str = "") -> object:
    """Real in-memory SQLite engine with a minimal ``sessions`` table."""
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id VARCHAR NOT NULL,
                    user_id INTEGER NOT NULL,
                    expires_at TIMESTAMP NOT NULL{extra_cols}
                )
                """
            )
        )
    return eng


# ===========================================================================
# _create_engine_for_url failure branch  (url given but engine creation raises)
# Then no engine arg + _get_engine fallback also raises -> early return.
# ===========================================================================


class TestCreateEngineFailureFallbacks:
    """When DATABASE_URL is given but _create_engine_for_url raises, and no engine
    arg is supplied and _get_engine() also raises, the helper returns silently."""

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
    def test_create_engine_error_then_get_engine_fallback_returns(self, func_name):
        import app.db.init_db as init_db

        func = getattr(init_db, func_name)
        get_engine_mock = MagicMock(side_effect=ImportError("no real engine"))
        with (
            patch("app.db._create_engine_for_url", side_effect=RuntimeError("bad url")),
            patch("app.db._get_engine", get_engine_mock),
        ):
            # url is non-empty -> _create_engine_for_url branch runs and fails (logs);
            # engine is None -> falls through to _get_engine which raises a recoverable
            # error -> function returns None without raising.
            result = func(None, database_url="postgresql://bad")
        assert result is None
        # confirms the no-engine fallback path was actually reached
        get_engine_mock.assert_called_once()


# ===========================================================================
# ensure_sessions_market_refresh_token_column — trailing except branch
# ===========================================================================


class TestMarketRefreshTokenColumn:
    def test_alter_failure_swallowed(self):
        """ALTER raises a recoverable error -> warning logged, no raise (1253-1254)."""
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        eng.begin.side_effect = RuntimeError("alter boom")
        insp = MagicMock()
        insp.get_table_names.return_value = ["sessions"]
        insp.get_columns.return_value = [{"name": "id"}]  # column missing -> enter ALTER

        with (
            patch("app.db._create_engine_for_url", return_value=eng),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            ensure_sessions_market_refresh_token_column(None, database_url="sqlite:///x")
        eng.begin.assert_called_once()


# ===========================================================================
# ensure_sessions_enterprise_entitlement_columns — _get_engine fallback success
# + trailing except branch
# ===========================================================================


class TestEnterpriseEntitlementColumns:
    def test_get_engine_fallback_used_when_no_url_no_engine(self):
        """No url + no engine -> _get_engine() supplies a real engine (1280-1285)."""
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = _sqlite_engine_with_sessions()
        with patch("app.db._get_engine", return_value=eng):
            ensure_sessions_enterprise_entitlement_columns(None, database_url=None)
        with eng.connect() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(sessions)"))}
        assert "market_user_id" in cols
        assert "entitled_mod_ids_json" in cols

    def test_inspect_failure_swallowed(self):
        """inspect raises recoverable error -> warning, no raise (1313-1314)."""
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        with (
            patch("app.db._create_engine_for_url", return_value=eng),
            patch("sqlalchemy.inspect", side_effect=OSError("disk gone")),
        ):
            ensure_sessions_enterprise_entitlement_columns(None, database_url="sqlite:///x")
        eng.begin.assert_not_called()


# ===========================================================================
# ensure_sessions_account_meta_columns — _get_engine fallback + trailing except
# ===========================================================================


class TestSessionsAccountMetaColumns:
    def test_get_engine_fallback_adds_columns(self):
        """No url + no engine -> _get_engine fallback (1340-1345) adds the meta columns."""
        from app.db.init_db import ensure_sessions_account_meta_columns

        eng = _sqlite_engine_with_sessions()
        with patch("app.db._get_engine", return_value=eng):
            ensure_sessions_account_meta_columns(None, database_url=None)
        with eng.connect() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(sessions)"))}
        assert "account_kind" in cols
        assert "market_membership_tier" in cols

    def test_alter_failure_swallowed(self):
        """ALTER raises recoverable error -> warning, no raise (1381-1382)."""
        from app.db.init_db import ensure_sessions_account_meta_columns

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        eng.begin.side_effect = RuntimeError("alter boom")
        insp = MagicMock()
        insp.get_table_names.return_value = ["sessions"]
        insp.get_columns.return_value = [{"name": "id"}]  # all meta cols missing
        with (
            patch("app.db._create_engine_for_url", return_value=eng),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            ensure_sessions_account_meta_columns(None, database_url="sqlite:///x")
        eng.begin.assert_called_once()


# ===========================================================================
# ensure_users_tenant_id_column — _get_engine fallback + trailing except
# ===========================================================================


class TestUsersTenantIdColumn:
    def test_get_engine_fallback_adds_column(self):
        """No url + no engine -> _get_engine fallback (1405-1410) adds users.tenant_id."""
        from app.db.init_db import ensure_users_tenant_id_column

        eng = create_engine("sqlite:///:memory:")
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR)"))
        with patch("app.db._get_engine", return_value=eng):
            ensure_users_tenant_id_column(None, database_url=None)
        with eng.connect() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        assert "tenant_id" in cols

    def test_alter_failure_swallowed(self):
        """ALTER raises recoverable error -> warning, no raise (1427-1428)."""
        from app.db.init_db import ensure_users_tenant_id_column

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        eng.begin.side_effect = RuntimeError("alter boom")
        insp = MagicMock()
        insp.get_table_names.return_value = ["users"]
        insp.get_columns.return_value = [{"name": "id"}]  # tenant_id missing
        with (
            patch("app.db._create_engine_for_url", return_value=eng),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            ensure_users_tenant_id_column(None, database_url="sqlite:///x")
        eng.begin.assert_called_once()


# ===========================================================================
# ensure_business_tenant_id_columns — _get_engine fallback success
# ===========================================================================


class TestBusinessTenantIdColumns:
    def test_get_engine_fallback_adds_columns(self):
        """No url + no engine -> _get_engine fallback (1454-1459) adds tenant_id to products."""
        from app.db.init_db import ensure_business_tenant_id_columns

        eng = create_engine("sqlite:///:memory:")
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, name VARCHAR)"))
        with patch("app.db._get_engine", return_value=eng):
            ensure_business_tenant_id_columns(None, database_url=None)
        with eng.connect() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(products)"))}
        assert "tenant_id" in cols


# ===========================================================================
# ensure_user_profile_columns — _get_engine fallback + trailing except
# ===========================================================================


class TestUserProfileColumns:
    def test_get_engine_fallback_adds_columns(self):
        """No url + no engine -> _get_engine fallback (1519-1524) adds tier/industry_id."""
        from app.db.init_db import ensure_user_profile_columns

        eng = create_engine("sqlite:///:memory:")
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR)"))
        with patch("app.db._get_engine", return_value=eng):
            ensure_user_profile_columns(None, database_url=None)
        with eng.connect() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        assert "tier" in cols
        assert "industry_id" in cols
        assert "email_verified" in cols

    def test_alter_failure_swallowed(self):
        """ALTER raises recoverable error -> warning, no raise (1562-1563)."""
        from app.db.init_db import ensure_user_profile_columns

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        eng.begin.side_effect = RuntimeError("alter boom")
        insp = MagicMock()
        insp.get_table_names.return_value = ["users"]
        insp.get_columns.return_value = [{"name": "id"}]  # all profile cols missing
        with (
            patch("app.db._create_engine_for_url", return_value=eng),
            patch("sqlalchemy.inspect", return_value=insp),
        ):
            ensure_user_profile_columns(None, database_url="sqlite:///x")
        eng.begin.assert_called_once()


# ===========================================================================
# ensure_neuro_event_log_bootstrap  (entirely untested)
# ===========================================================================


class TestEnsureNeuroEventLogBootstrap:
    def test_none_engine_returns(self):
        """No resolvable engine -> early return (967), no table creation."""
        from app.db.init_db import ensure_neuro_event_log_bootstrap

        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=None),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_neuro_event_log_bootstrap(None)
        mock_create.assert_not_called()

    def test_creates_table_when_missing(self):
        """Table absent -> create_all invoked for NeuroEventLog."""
        from app.db.init_db import ensure_neuro_event_log_bootstrap

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        insp = MagicMock()
        insp.get_table_names.return_value = []
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("sqlalchemy.inspect", return_value=insp),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_neuro_event_log_bootstrap(eng)
        mock_create.assert_called_once()

    def test_skips_when_table_present(self):
        from app.db.init_db import ensure_neuro_event_log_bootstrap

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        insp = MagicMock()
        insp.get_table_names.return_value = ["neuro_event_log"]
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("sqlalchemy.inspect", return_value=insp),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_neuro_event_log_bootstrap(eng)
        mock_create.assert_not_called()

    def test_swallow_errors_false_reraises(self):
        """inspect raises recoverable error + swallow_errors=False -> re-raise (982)."""
        from app.db.init_db import ensure_neuro_event_log_bootstrap

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
        ):
            with pytest.raises(RuntimeError, match="inspect failed"):
                ensure_neuro_event_log_bootstrap(eng, swallow_errors=False)

    def test_swallow_errors_true_swallows(self):
        from app.db.init_db import ensure_neuro_event_log_bootstrap

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_neuro_event_log_bootstrap(eng, swallow_errors=True)
        mock_create.assert_not_called()


# ===========================================================================
# ensure_sqlite_enterprise_business_bootstrap  (912-918 re-raise branch + 859)
# ===========================================================================


class TestEnsureSqliteEnterpriseBusinessBootstrap:
    def test_non_sqlite_skipped(self):
        """Non-sqlite dialect -> early return (859-860), no table creation."""
        from app.db.init_db import ensure_sqlite_enterprise_business_bootstrap

        eng = MagicMock()
        eng.dialect.name = "postgresql"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("app.db.base.Base.metadata.create_all") as mock_create,
        ):
            ensure_sqlite_enterprise_business_bootstrap(eng)
        mock_create.assert_not_called()

    def test_creates_tables_when_missing(self):
        from app.db.init_db import ensure_sqlite_enterprise_business_bootstrap

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng):
            ensure_sqlite_enterprise_business_bootstrap(eng)
        with eng.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
        assert {"tenants", "customers", "products"}.issubset(tables)

    def test_swallow_errors_false_reraises(self):
        """inspect raises recoverable error + swallow_errors=False -> re-raise (917-918)."""
        from app.db.init_db import ensure_sqlite_enterprise_business_bootstrap

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        with (
            patch("app.db.init_db._resolve_auth_bootstrap_engine", return_value=eng),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")),
        ):
            with pytest.raises(RuntimeError, match="inspect failed"):
                ensure_sqlite_enterprise_business_bootstrap(eng, swallow_errors=False)


# ===========================================================================
# init_im_tables — engine resolution branches (1569-1576)
# ===========================================================================


class TestInitImTablesEngineResolution:
    def test_resolves_engine_from_database_url(self):
        """engine=None + database_url -> _create_engine_for_url branch (1569-1572)."""
        from app.db.init_db import init_im_tables

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db._create_engine_for_url", return_value=eng) as mock_create:
            init_im_tables(None, database_url="sqlite:///x")
        mock_create.assert_called_once_with("sqlite:///x")
        with eng.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
        assert "im_conversations" in tables

    def test_resolves_engine_from_get_engine(self):
        """engine=None + no url -> _get_engine branch (1574-1576)."""
        from app.db.init_db import init_im_tables

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db._get_engine", return_value=eng) as mock_get:
            init_im_tables(None, database_url=None)
        mock_get.assert_called_once()
        with eng.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
        assert "im_messages" in tables


# ===========================================================================
# ensure_product_query_indexes — inspect failure + per-stmt failure
# ===========================================================================


class TestEnsureProductQueryIndexesErrors:
    def test_inspect_failure_treated_as_no_products(self):
        """inspect raises recoverable error -> names=set() -> early return (1675-1676)."""
        from app.db.init_db import ensure_product_query_indexes

        eng = MagicMock()
        with patch("sqlalchemy.inspect", side_effect=OSError("inspect down")):
            ensure_product_query_indexes(eng)
        # products absent (names empty) -> never opened a transaction to build indexes
        eng.begin.assert_not_called()

    def test_per_stmt_failure_is_swallowed(self):
        """Each CREATE INDEX failure is caught individually (1689-1690), no raise."""
        from app.db.init_db import ensure_product_query_indexes

        eng = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]
        conn = eng.begin.return_value.__enter__.return_value
        conn.execute.side_effect = RuntimeError("index boom")
        with patch("sqlalchemy.inspect", return_value=insp):
            ensure_product_query_indexes(eng)
        # both index statements were attempted despite each one failing
        assert conn.execute.call_count == 2


# ===========================================================================
# init_approval_tables — trailing except branch (1661-1662)
# ===========================================================================


class TestInitApprovalTablesAlterError:
    def test_inspect_failure_swallowed(self):
        """inspect raises recoverable error after create_all -> warning, no raise (1661-1662)."""
        from app.db.init_db import init_approval_tables

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        with (
            patch("app.db._get_engine", return_value=eng),
            patch("app.db.base.Base.metadata.create_all"),
            patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect down")),
        ):
            init_approval_tables(eng)  # must not raise


# ===========================================================================
# init_persona_tables — create_all failure (1749-1750) + _get_engine fallback (1743)
# ===========================================================================


class TestInitPersonaTables:
    def test_creates_tables(self):
        from app.db.init_db import init_persona_tables

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db._get_engine", return_value=eng):
            init_persona_tables(eng)
        with eng.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
        assert "persona_profile" in tables
        assert "persona_event_log" in tables

    def test_get_engine_failure_falls_back_to_passed_engine(self):
        """_get_engine raises -> keep the passed engine (1743) and still create tables."""
        from app.db.init_db import init_persona_tables

        eng = create_engine("sqlite:///:memory:")
        with patch("app.db._get_engine", side_effect=RuntimeError("no real engine")):
            init_persona_tables(eng)
        with eng.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            }
        assert "persona_profile" in tables

    def test_create_all_failure_swallowed(self):
        """create_all raises recoverable error -> warning, no raise (1749-1750)."""
        from app.db.init_db import init_persona_tables

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        with (
            patch("app.db._get_engine", return_value=eng),
            patch(
                "app.db.base.Base.metadata.create_all",
                side_effect=RuntimeError("create boom"),
            ),
        ):
            init_persona_tables(eng)  # must not raise


# ===========================================================================
# init_service_bridge_tables — create_all failure (1717-1718)
# ===========================================================================


class TestInitServiceBridgeTablesError:
    def test_create_all_failure_swallowed(self):
        """create_all raises recoverable error -> warning, no raise (1717-1718)."""
        from app.db.init_db import init_service_bridge_tables

        eng = MagicMock()
        eng.dialect.name = "sqlite"
        with (
            patch("app.db._get_engine", return_value=eng),
            patch(
                "app.db.base.Base.metadata.create_all",
                side_effect=RuntimeError("create boom"),
            ),
        ):
            init_service_bridge_tables(eng)  # must not raise
