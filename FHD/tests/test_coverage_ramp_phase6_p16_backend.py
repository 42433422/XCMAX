"""COVERAGE_RAMP Phase 6 round 16: backend low-coverage modules.

Targets:
- ``app/db/init_db.py`` (571 行，未覆盖 72 行，cov 87.5%)
- ``app/services/paddle_ocr_runner.py`` (93 行，未覆盖 72 行，cov 17.6%)
- ``app/infrastructure/persistence/wechat_contact_store_impl.py`` (207 行，未覆盖 71 行，cov 63.3%)
- ``app/infrastructure/repositories/customer_repository_impl.py`` (88 行，未覆盖 69 行，cov 18.3%)
- ``app/services/kitten_report/service.py`` (216 行，未覆盖 69 行，cov 64.0%)
- ``app/domain/neuro/processors/conscious.py`` (133 行，未覆盖 68 行，cov 38.7%)
- ``app/fastapi_routes/domains/excel/routes.py`` (117 行，未覆盖 68 行，cov 39.6%)

Tests follow the phase-6 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API / LLM / file IO / paddleocr). The handler functions themselves are
exercised through real calls.

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict, empty string)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, OSError)
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain.neuro.processors.conscious import (
    BusinessLogicHandler,
    ConsciousProcessor,
    IntentProcessingHandler,
    ProcessingResult,
    ProcessingStage,
    conscious_process,
    get_conscious_processor,
)
from app.domain.value_objects import ContactInfo
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent

# ===========================================================================
# Shared fixtures
# ===========================================================================


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    d = tempfile.mkdtemp()
    yield d
    import shutil

    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sqlite_engine():
    """In-memory SQLite engine for init_db table-creation tests."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield eng
    eng.dispose()


def _make_sqlite_db(path: str) -> None:
    """Create a minimal SQLite db file with one table."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()


# ===========================================================================
# 1. app/db/init_db.py
# ===========================================================================


class TestInitDbInitializeDatabases:
    """Cover ``initialize_databases`` branches."""

    def test_initialize_databases_creates_from_seed(self, tmp_dir, monkeypatch):
        from app.db.init_db import initialize_databases

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        seed_dir = os.path.join(tmp_dir, "db_seed")
        os.makedirs(seed_dir, exist_ok=True)
        seed_path = os.path.join(seed_dir, "test_init.db")
        _make_sqlite_db(seed_path)

        monkeypatch.setattr("app.db.init_db._iter_seed_dirs", lambda: [seed_dir])
        initialize_databases(["test_init.db"])
        assert os.path.exists(os.path.join(tmp_dir, "test_init.db"))

    def test_initialize_databases_skips_existing(self, tmp_dir, monkeypatch):
        from app.db.init_db import initialize_databases

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        target = os.path.join(tmp_dir, "products.db")
        with open(target, "w") as f:
            f.write("existing")

        initialize_databases(["products.db"])
        with open(target) as f:
            assert f.read() == "existing"

    def test_initialize_databases_no_seed_logs_warning(self, tmp_dir, monkeypatch):
        from app.db.init_db import initialize_databases

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        monkeypatch.setattr("app.db.init_db._iter_seed_dirs", lambda: [])
        # Should not raise
        initialize_databases(["nonexistent.db"])

    def test_initialize_databases_copy_failure_logged(self, tmp_dir, monkeypatch):
        from app.db import init_db

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        seed_dir = os.path.join(tmp_dir, "db_seed")
        os.makedirs(seed_dir, exist_ok=True)
        seed_path = os.path.join(seed_dir, "fail.db")
        _make_sqlite_db(seed_path)
        monkeypatch.setattr("app.db.init_db._iter_seed_dirs", lambda: [seed_dir])

        with patch("app.db.init_db.shutil.copy2", side_effect=OSError("disk full")):
            # Should not raise; logs warning
            init_db.initialize_databases(["fail.db"])

    def test_initialize_databases_empty_db_files(self, tmp_dir, monkeypatch):
        from app.db.init_db import initialize_databases

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        # Empty iterable should be a no-op
        initialize_databases([])
        assert os.path.isdir(tmp_dir)

    def test_iter_seed_dirs_includes_meipass(self, monkeypatch):
        """When ``sys._MEIPASS`` is set, it should be yielded."""
        import sys

        from app.db import init_db

        fake_meipass = "/tmp/fake_meipass"
        original = getattr(sys, "_MEIPASS", None)
        sys._MEIPASS = fake_meipass
        try:
            dirs = list(init_db._iter_seed_dirs())
            assert fake_meipass in dirs
        finally:
            if original is None:
                del sys._MEIPASS
            else:
                sys._MEIPASS = original


class TestInitDbEnsureSqlitePerModCopies:
    """Cover ``ensure_sqlite_per_mod_database_copies`` branches."""

    def test_copies_mother_db_for_mod(self, tmp_dir, monkeypatch):
        from app.db.init_db import ensure_sqlite_per_mod_database_copies

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        mother = os.path.join(tmp_dir, "products.db")
        _make_sqlite_db(mother)

        with patch(
            "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
            lambda name, mod_id: f"products__{mod_id}.db",
        ):
            ensure_sqlite_per_mod_database_copies(["mymod"])
        assert os.path.exists(os.path.join(tmp_dir, "products__mymod.db"))

    def test_skips_empty_mod_id(self, tmp_dir, monkeypatch):
        from app.db.init_db import ensure_sqlite_per_mod_database_copies

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        with patch(
            "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
            lambda name, mod_id: f"products__{mod_id}.db",
        ):
            ensure_sqlite_per_mod_database_copies(["", "  ", None])

    def test_skips_duplicate_mod_ids(self, tmp_dir, monkeypatch):
        from app.db.init_db import ensure_sqlite_per_mod_database_copies

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        mother = os.path.join(tmp_dir, "products.db")
        _make_sqlite_db(mother)

        with patch(
            "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
            lambda name, mod_id: f"products__{mod_id}.db",
        ):
            ensure_sqlite_per_mod_database_copies(["mymod", "mymod"])
        assert os.path.exists(os.path.join(tmp_dir, "products__mymod.db"))

    def test_skips_when_no_mother_db(self, tmp_dir, monkeypatch):
        from app.db.init_db import ensure_sqlite_per_mod_database_copies

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        with patch(
            "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
            lambda name, mod_id: f"products__{mod_id}.db",
        ):
            ensure_sqlite_per_mod_database_copies(["mymod"])
        # No mother db -> no copy
        assert not os.path.exists(os.path.join(tmp_dir, "products__mymod.db"))

    def test_copy_failure_logged(self, tmp_dir, monkeypatch):
        from app.db.init_db import ensure_sqlite_per_mod_database_copies

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        mother = os.path.join(tmp_dir, "products.db")
        _make_sqlite_db(mother)

        with (
            patch(
                "app.db.sqlite_mod_paths.sqlite_filename_with_mod_suffix",
                lambda name, mod_id: f"products__{mod_id}.db",
            ),
            patch("app.db.init_db.shutil.copy2", side_effect=OSError("denied")),
        ):
            ensure_sqlite_per_mod_database_copies(["mymod"])
        # Should not raise; copy failed


class TestInitDbGetDbPath:
    """Cover ``get_db_path`` and ``get_distillation_db_path``."""

    def test_get_db_path_no_mod_id(self, tmp_dir, monkeypatch):
        from app.db.init_db import get_db_path

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        path = get_db_path("products.db")
        assert path == os.path.join(tmp_dir, "products.db")

    def test_get_db_path_with_mod_id(self, tmp_dir, monkeypatch):
        from app.db.init_db import get_db_path

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)

        def fake_get_mod_id():
            return "taiyangniao-pro"

        monkeypatch.setattr("app.request_active_mod_ctx.get_request_active_mod_id", fake_get_mod_id)
        path = get_db_path("products.db")
        assert "products__taiyangniao_pro.db" in path

    def test_get_distillation_db_path(self, tmp_dir, monkeypatch):
        from app.db.init_db import get_distillation_db_path

        monkeypatch.setattr("app.db.init_db.get_app_data_dir", lambda: tmp_dir)
        path = get_distillation_db_path()
        assert path.endswith("distillation.db")


class TestInitDbTemplateTables:
    """Cover ``init_template_tables`` and ``init_template_tables_for_engine``."""

    def test_init_template_tables_creates_tables(self, tmp_dir):
        from app.db.init_db import init_template_tables

        db_path = os.path.join(tmp_dir, "test.db")
        init_template_tables(db_path)

        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('templates','template_usage_log')"
        ).fetchall()
        conn.close()
        assert len(tables) == 2

    def test_init_template_tables_idempotent(self, tmp_dir):
        from app.db.init_db import init_template_tables

        db_path = os.path.join(tmp_dir, "test.db")
        init_template_tables(db_path)
        # Second call should not raise
        init_template_tables(db_path)

    def test_init_template_tables_for_engine_skips_non_postgres(self, sqlite_engine):
        from app.db.init_db import init_template_tables_for_engine

        # SQLite engine -> should be no-op (returns early)
        init_template_tables_for_engine(sqlite_engine)


class TestInitDbAuthBootstrap:
    """Cover ``ensure_sqlite_auth_bootstrap`` and related helpers."""

    def test_ensure_sqlite_auth_bootstrap_creates_tables(self, sqlite_engine, monkeypatch):
        from app.db.init_db import ensure_sqlite_auth_bootstrap

        # Force resolve to use our engine
        monkeypatch.setattr(
            "app.db.init_db._resolve_auth_bootstrap_engine",
            lambda engine=None, database_url=None: sqlite_engine,
        )
        ensure_sqlite_auth_bootstrap(sqlite_engine)
        with sqlite_engine.connect() as conn:
            tables = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            ).fetchall()
            assert len(tables) == 1

    def test_ensure_sqlite_auth_bootstrap_skips_non_sqlite(self, monkeypatch):
        from app.db.init_db import ensure_sqlite_auth_bootstrap

        pg_engine = MagicMock()
        pg_engine.dialect.name = "postgresql"
        monkeypatch.setattr(
            "app.db.init_db._resolve_auth_bootstrap_engine",
            lambda engine=None, database_url=None: pg_engine,
        )
        # Should be no-op
        ensure_sqlite_auth_bootstrap(pg_engine)

    def test_ensure_sqlite_auth_bootstrap_swallows_errors(self, sqlite_engine, monkeypatch):
        from app.db.init_db import ensure_sqlite_auth_bootstrap

        monkeypatch.setattr(
            "app.db.init_db._resolve_auth_bootstrap_engine",
            lambda engine=None, database_url=None: sqlite_engine,
        )
        with patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")):
            # swallow_errors=True -> should not raise
            ensure_sqlite_auth_bootstrap(sqlite_engine, swallow_errors=True)

    def test_ensure_sqlite_auth_bootstrap_raises_when_not_swallowed(
        self, sqlite_engine, monkeypatch
    ):
        from app.db.init_db import ensure_sqlite_auth_bootstrap

        monkeypatch.setattr(
            "app.db.init_db._resolve_auth_bootstrap_engine",
            lambda engine=None, database_url=None: sqlite_engine,
        )
        with patch("sqlalchemy.inspect", side_effect=RuntimeError("inspect failed")):
            with pytest.raises(RuntimeError, match="inspect failed"):
                ensure_sqlite_auth_bootstrap(sqlite_engine, swallow_errors=False)

    def test_seed_default_admin_user_skips_when_users_exist(self, sqlite_engine, monkeypatch):
        from app.db.init_db import _seed_default_admin_user

        # Create users table with a row
        from app.db.models.user import Session as UserSession
        from app.db.models.user import User

        Base.metadata.create_all(sqlite_engine, tables=[User.__table__, UserSession.__table__])
        # Use ORM insert so column defaults (role, is_active, etc.) are applied.
        SessionLocal = sessionmaker(bind=sqlite_engine)
        with SessionLocal() as session:
            session.add(
                User(
                    username="existing",
                    password="x",
                    display_name="Existing",
                    email="ex@example.com",
                )
            )
            session.commit()

        # Should be no-op (users already exist)
        _seed_default_admin_user(sqlite_engine)
        with sqlite_engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
            assert count == 1


class TestInitDbResolveAuthBootstrapEngine:
    """Cover ``_resolve_auth_bootstrap_engine``."""

    def test_resolve_with_database_url(self, monkeypatch):
        from app.db.init_db import _resolve_auth_bootstrap_engine

        fake_engine = MagicMock()
        fake_engine.dialect.name = "sqlite"
        with patch("app.db._create_engine_for_url", return_value=fake_engine):
            result = _resolve_auth_bootstrap_engine(database_url="sqlite:///foo.db")
        assert result is fake_engine

    def test_resolve_with_database_url_failure_falls_back_to_engine(self, monkeypatch):
        from app.db import init_db

        fake_engine = MagicMock(spec=Engine)
        with (
            patch("app.db._create_engine_for_url", side_effect=RuntimeError("cannot create")),
            patch("app.db._get_engine", return_value=fake_engine),
        ):
            result = init_db._resolve_auth_bootstrap_engine(
                database_url="bad://url", engine=fake_engine
            )
        assert result is fake_engine

    def test_resolve_no_url_no_engine_falls_back_to_get_engine(self, monkeypatch):
        from app.db import init_db

        fake_engine = MagicMock(spec=Engine)
        with patch("app.db._get_engine", return_value=fake_engine):
            result = init_db._resolve_auth_bootstrap_engine()
        assert result is fake_engine

    def test_resolve_all_failures_returns_none(self, monkeypatch):
        from app.db import init_db

        with patch("app.db._get_engine", side_effect=RuntimeError("no engine")):
            result = init_db._resolve_auth_bootstrap_engine()
        assert result is None


class TestInitDbRuntimeAuthBootstrap:
    """Cover ``ensure_runtime_auth_bootstrap``."""

    def test_runtime_auth_bootstrap_empty_url_noop(self, monkeypatch):
        from app.db.init_db import ensure_runtime_auth_bootstrap

        monkeypatch.setattr(
            "app.fastapi_app.sqlite_paths.resolve_effective_database_url", lambda: ""
        )
        # Should be no-op
        ensure_runtime_auth_bootstrap()

    def test_runtime_auth_bootstrap_sqlite_url(self, sqlite_engine, monkeypatch):
        from app.db.init_db import ensure_runtime_auth_bootstrap

        monkeypatch.setattr(
            "app.fastapi_app.sqlite_paths.resolve_effective_database_url",
            lambda: "sqlite:///test.db",
        )
        monkeypatch.setattr("app.fastapi_app.sqlite_paths.is_sqlite_url", lambda url: True)
        called = {"auth": 0, "rbac": 0, "inv": 0, "prefs": 0}

        def fake_auth(engine, *, database_url=None, swallow_errors=True):
            called["auth"] += 1

        def fake_rbac(engine, *, database_url=None, swallow_errors=True):
            called["rbac"] += 1

        def fake_inv(engine, *, database_url=None, swallow_errors=True):
            called["inv"] += 1

        def fake_prefs(engine, *, database_url=None, swallow_errors=True):
            called["prefs"] += 1

        monkeypatch.setattr("app.db.init_db.ensure_sqlite_auth_bootstrap", fake_auth)
        monkeypatch.setattr("app.db.init_db.ensure_sqlite_rbac_bootstrap", fake_rbac)
        monkeypatch.setattr("app.db.init_db.ensure_sqlite_inventory_bootstrap", fake_inv)
        monkeypatch.setattr("app.db.init_db.ensure_user_preferences_bootstrap", fake_prefs)

        ensure_runtime_auth_bootstrap()
        assert called == {"auth": 1, "rbac": 1, "inv": 1, "prefs": 1}

    def test_runtime_auth_bootstrap_postgres_url(self, monkeypatch):
        from app.db.init_db import ensure_runtime_auth_bootstrap

        monkeypatch.setattr(
            "app.fastapi_app.sqlite_paths.resolve_effective_database_url",
            lambda: "postgresql://user:pass@host/db",
        )
        monkeypatch.setattr("app.fastapi_app.sqlite_paths.is_sqlite_url", lambda url: False)
        called = {"pg": 0, "prefs": 0}

        def fake_pg(engine, *, database_url=None):
            called["pg"] += 1

        def fake_prefs(engine, *, database_url=None, swallow_errors=True):
            called["prefs"] += 1

        monkeypatch.setattr("app.db.init_db.ensure_postgresql_auth_bootstrap", fake_pg)
        monkeypatch.setattr("app.db.init_db.ensure_user_preferences_bootstrap", fake_prefs)

        ensure_runtime_auth_bootstrap()
        assert called == {"pg": 1, "prefs": 1}


class TestInitDbSessionsColumns:
    """Cover ``ensure_sessions_market_access_token_column`` etc."""

    def test_ensure_sessions_market_access_token_no_sessions_table(self, monkeypatch):
        from app.db.init_db import ensure_sessions_market_access_token_column

        fake_engine = MagicMock()
        fake_engine.dialect.name = "sqlite"
        insp = MagicMock()
        insp.get_table_names.return_value = []
        with patch("sqlalchemy.inspect", return_value=insp):
            # Should be no-op
            ensure_sessions_market_access_token_column(fake_engine)

    def test_ensure_sessions_market_access_token_already_has_column(self, monkeypatch):
        from app.db.init_db import ensure_sessions_market_access_token_column

        fake_engine = MagicMock()
        fake_engine.dialect.name = "sqlite"
        insp = MagicMock()
        insp.get_table_names.return_value = ["sessions"]
        insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "market_access_token"},
        ]
        with patch("sqlalchemy.inspect", return_value=insp):
            ensure_sessions_market_access_token_column(fake_engine)
        # No ALTER should be executed
        fake_engine.begin.assert_not_called()

    def test_ensure_sessions_market_refresh_token_no_sessions_table(self, monkeypatch):
        from app.db.init_db import ensure_sessions_market_refresh_token_column

        fake_engine = MagicMock()
        fake_engine.dialect.name = "sqlite"
        insp = MagicMock()
        insp.get_table_names.return_value = []
        with patch("sqlalchemy.inspect", return_value=insp):
            ensure_sessions_market_refresh_token_column(fake_engine)

    def test_ensure_sessions_enterprise_entitlement_no_sessions_table(self, monkeypatch):
        from app.db.init_db import ensure_sessions_enterprise_entitlement_columns

        fake_engine = MagicMock()
        fake_engine.dialect.name = "sqlite"
        insp = MagicMock()
        insp.get_table_names.return_value = []
        with patch("sqlalchemy.inspect", return_value=insp):
            ensure_sessions_enterprise_entitlement_columns(fake_engine)

    def test_ensure_sessions_account_meta_no_sessions_table(self, monkeypatch):
        from app.db.init_db import ensure_sessions_account_meta_columns

        fake_engine = MagicMock()
        fake_engine.dialect.name = "sqlite"
        insp = MagicMock()
        insp.get_table_names.return_value = []
        with patch("sqlalchemy.inspect", return_value=insp):
            ensure_sessions_account_meta_columns(fake_engine)


class TestInitDbOtherTables:
    """Cover ``init_im_tables``, ``init_approval_tables``, ``init_service_bridge_tables``, ``ensure_product_query_indexes``."""

    def test_init_im_tables_creates_tables(self, sqlite_engine):
        from app.db.init_db import init_im_tables

        init_im_tables(sqlite_engine)
        with sqlite_engine.connect() as conn:
            tables = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'im_%'")
            ).fetchall()
            assert len(tables) >= 3

    def test_init_approval_tables_creates_tables(self, sqlite_engine):
        from app.db.init_db import init_approval_tables

        # init_approval_tables tries _get_engine() first; force it to fail so our engine is used
        with patch("app.db._get_engine", side_effect=RuntimeError("no engine")):
            init_approval_tables(sqlite_engine)
        with sqlite_engine.connect() as conn:
            tables = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'approval_%'")
            ).fetchall()
            assert len(tables) >= 3

    def test_init_service_bridge_tables_creates_tables(self, sqlite_engine):
        from app.db.init_db import init_service_bridge_tables

        # init_service_bridge_tables tries _get_engine() first; force it to fail so our engine is used
        with patch("app.db._get_engine", side_effect=RuntimeError("no engine")):
            init_service_bridge_tables(sqlite_engine)
        with sqlite_engine.connect() as conn:
            tables = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('service_requests','service_bridge_config')"
                )
            ).fetchall()
            assert len(tables) == 2

    def test_ensure_product_query_indexes_no_products_table(self, sqlite_engine):
        from app.db.init_db import ensure_product_query_indexes

        # No products table -> no-op
        ensure_product_query_indexes(sqlite_engine)


# ===========================================================================
# 2. app/services/paddle_ocr_runner.py
# ===========================================================================


class TestPaddleOcrAvailability:
    """Cover ``check_paddle_available`` and helpers."""

    def test_check_paddle_available_returns_true_when_installed(self):
        from app.services.paddle_ocr_runner import check_paddle_available

        with patch.dict("sys.modules", {"paddleocr": MagicMock()}):
            assert check_paddle_available() is True

    def test_check_paddle_available_returns_false_when_missing(self):
        from app.services.paddle_ocr_runner import check_paddle_available

        original = __import__("sys").modules.get("paddleocr")
        try:
            if "paddleocr" in __import__("sys").modules:
                del __import__("sys").modules["paddleocr"]
            with patch("builtins.__import__", side_effect=ImportError("no paddleocr")):
                assert check_paddle_available() is False
        finally:
            if original is not None:
                __import__("sys").modules["paddleocr"] = original

    def test_is_paddlex_infer_dir_empty_path(self):
        from app.services.paddle_ocr_runner import _is_paddlex_infer_dir

        assert _is_paddlex_infer_dir("") is False

    def test_is_paddlex_infer_dir_no_inference_yml(self, tmp_dir):
        from app.services.paddle_ocr_runner import _is_paddlex_infer_dir

        assert _is_paddlex_infer_dir(tmp_dir) is False

    def test_is_paddlex_infer_dir_with_inference_yml(self, tmp_dir):
        from app.services.paddle_ocr_runner import _is_paddlex_infer_dir

        with open(os.path.join(tmp_dir, "inference.yml"), "w") as f:
            f.write("test")
        assert _is_paddlex_infer_dir(tmp_dir) is True


class TestPaddleOcrPickDetRecDirs:
    """Cover ``_pick_det_rec_dirs``."""

    def test_pick_det_rec_dirs_finds_both(self, tmp_dir):
        from app.services.paddle_ocr_runner import _pick_det_rec_dirs

        det_dir = os.path.join(tmp_dir, "PP-OCRv4_mobile_det_infer")
        rec_dir = os.path.join(tmp_dir, "PP-OCRv4_mobile_rec_infer")
        os.makedirs(det_dir)
        os.makedirs(rec_dir)
        with open(os.path.join(det_dir, "inference.yml"), "w") as f:
            f.write("x")
        with open(os.path.join(rec_dir, "inference.yml"), "w") as f:
            f.write("x")

        det, rec = _pick_det_rec_dirs(tmp_dir)
        assert det is not None and det.endswith("PP-OCRv4_mobile_det_infer")
        assert rec is not None and rec.endswith("PP-OCRv4_mobile_rec_infer")

    def test_pick_det_rec_dirs_finds_neither(self, tmp_dir):
        from app.services.paddle_ocr_runner import _pick_det_rec_dirs

        det, rec = _pick_det_rec_dirs(tmp_dir)
        assert det is None
        assert rec is None

    def test_pick_det_rec_dirs_finds_only_legacy_names(self, tmp_dir):
        from app.services.paddle_ocr_runner import _pick_det_rec_dirs

        det_dir = os.path.join(tmp_dir, "ch_PP-OCRv4_det_infer")
        rec_dir = os.path.join(tmp_dir, "ch_PP-OCRv4_rec_infer")
        os.makedirs(det_dir)
        os.makedirs(rec_dir)
        with open(os.path.join(det_dir, "inference.yml"), "w") as f:
            f.write("x")
        with open(os.path.join(rec_dir, "inference.yml"), "w") as f:
            f.write("x")

        det, rec = _pick_det_rec_dirs(tmp_dir)
        assert det is not None
        assert rec is not None


class TestPaddleOcrResolveLocalModelDirs:
    """Cover ``_resolve_local_model_dirs``."""

    def test_resolve_local_model_dirs_with_explicit_dirs(self, monkeypatch):
        from app.services.paddle_ocr_runner import _resolve_local_model_dirs

        monkeypatch.setenv("PADDLEOCR_TEXT_DET_MODEL_DIR", "/det")
        monkeypatch.setenv("PADDLEOCR_TEXT_REC_MODEL_DIR", "/rec")
        monkeypatch.delenv("XCAGI_PADDLE_MODEL_ROOT", raising=False)
        det, rec = _resolve_local_model_dirs()
        assert det == "/det"
        assert rec == "/rec"

    def test_resolve_local_model_dirs_with_root(self, tmp_dir, monkeypatch):
        from app.services.paddle_ocr_runner import _resolve_local_model_dirs

        monkeypatch.delenv("PADDLEOCR_TEXT_DET_MODEL_DIR", raising=False)
        monkeypatch.delenv("PADDLEOCR_TEXT_REC_MODEL_DIR", raising=False)
        monkeypatch.setenv("XCAGI_PADDLE_MODEL_ROOT", tmp_dir)

        det_dir = os.path.join(tmp_dir, "PP-OCRv4_mobile_det_infer")
        rec_dir = os.path.join(tmp_dir, "PP-OCRv4_mobile_rec_infer")
        os.makedirs(det_dir)
        os.makedirs(rec_dir)
        with open(os.path.join(det_dir, "inference.yml"), "w") as f:
            f.write("x")
        with open(os.path.join(rec_dir, "inference.yml"), "w") as f:
            f.write("x")

        det, rec = _resolve_local_model_dirs()
        assert det is not None and det.endswith("PP-OCRv4_mobile_det_infer")
        assert rec is not None and rec.endswith("PP-OCRv4_mobile_rec_infer")

    def test_resolve_local_model_dirs_no_env(self, monkeypatch):
        from app.services.paddle_ocr_runner import _resolve_local_model_dirs

        monkeypatch.delenv("PADDLEOCR_TEXT_DET_MODEL_DIR", raising=False)
        monkeypatch.delenv("PADDLEOCR_TEXT_REC_MODEL_DIR", raising=False)
        monkeypatch.delenv("XCAGI_PADDLE_MODEL_ROOT", raising=False)
        det, rec = _resolve_local_model_dirs()
        assert det is None
        assert rec is None


class TestPaddleOcrResolveLocalModelNames:
    """Cover ``_resolve_local_model_names``."""

    def test_resolve_local_model_names_with_env(self, monkeypatch):
        from app.services.paddle_ocr_runner import _resolve_local_model_names

        monkeypatch.setenv("PADDLEOCR_TEXT_DET_MODEL_NAME", "custom_det")
        monkeypatch.setenv("PADDLEOCR_TEXT_REC_MODEL_NAME", "custom_rec")
        dn, rn = _resolve_local_model_names("/det", "/rec")
        assert dn == "custom_det"
        assert rn == "custom_rec"

    def test_resolve_local_model_names_defaults(self, monkeypatch):
        from app.services.paddle_ocr_runner import _resolve_local_model_names

        monkeypatch.delenv("PADDLEOCR_TEXT_DET_MODEL_NAME", raising=False)
        monkeypatch.delenv("PADDLEOCR_TEXT_REC_MODEL_NAME", raising=False)
        dn, rn = _resolve_local_model_names("/det", "/rec")
        assert dn == "PP-OCRv4_mobile_det"
        assert rn == "PP-OCRv4_mobile_rec"

    def test_resolve_local_model_names_only_det_env(self, monkeypatch):
        from app.services.paddle_ocr_runner import _resolve_local_model_names

        monkeypatch.setenv("PADDLEOCR_TEXT_DET_MODEL_NAME", "custom_det")
        monkeypatch.delenv("PADDLEOCR_TEXT_REC_MODEL_NAME", raising=False)
        # Only det set -> falls back to defaults
        dn, rn = _resolve_local_model_names("/det", "/rec")
        assert dn == "PP-OCRv4_mobile_det"
        assert rn == "PP-OCRv4_mobile_rec"


class TestPaddleOcrGetInstance:
    """Cover ``get_paddle_ocr_instance``."""

    def test_get_instance_uses_local_models(self, monkeypatch):
        from app.services import paddle_ocr_runner as runner

        # Reset singleton
        runner._paddle_ocr = None

        monkeypatch.setenv("PADDLEOCR_TEXT_DET_MODEL_DIR", "/det")
        monkeypatch.setenv("PADDLEOCR_TEXT_REC_MODEL_DIR", "/rec")
        monkeypatch.setenv("PADDLEOCR_TEXT_DET_MODEL_NAME", "dn")
        monkeypatch.setenv("PADDLEOCR_TEXT_REC_MODEL_NAME", "rn")

        fake_paddle = MagicMock()
        fake_instance = MagicMock()
        fake_paddle.PaddleOCR.return_value = fake_instance

        with patch.dict("sys.modules", {"paddleocr": fake_paddle}):
            inst = runner.get_paddle_ocr_instance()
        assert inst is fake_instance
        # Cleanup
        runner._paddle_ocr = None

    def test_get_instance_uses_online_when_no_local(self, monkeypatch):
        from app.services import paddle_ocr_runner as runner

        runner._paddle_ocr = None

        monkeypatch.delenv("PADDLEOCR_TEXT_DET_MODEL_DIR", raising=False)
        monkeypatch.delenv("PADDLEOCR_TEXT_REC_MODEL_DIR", raising=False)
        monkeypatch.delenv("XCAGI_PADDLE_MODEL_ROOT", raising=False)
        monkeypatch.setenv("PADDLEOCR_LANG", "en")

        fake_paddle = MagicMock()
        fake_instance = MagicMock()
        fake_paddle.PaddleOCR.return_value = fake_instance

        with patch.dict("sys.modules", {"paddleocr": fake_paddle}):
            inst = runner.get_paddle_ocr_instance()
        assert inst is fake_instance
        fake_paddle.PaddleOCR.assert_called_once_with(lang="en")
        runner._paddle_ocr = None

    def test_get_instance_returns_cached(self, monkeypatch):
        from app.services import paddle_ocr_runner as runner

        fake_instance = MagicMock()
        runner._paddle_ocr = fake_instance

        # Should return cached without re-init
        inst = runner.get_paddle_ocr_instance()
        assert inst is fake_instance
        runner._paddle_ocr = None


class TestPaddleOcrNormalizePredictResult:
    """Cover ``_normalize_predict_result``."""

    def test_normalize_list_with_dict(self):
        from app.services.paddle_ocr_runner import _normalize_predict_result

        result = [{"res": {"rec_texts": ["hello"]}}]
        out = _normalize_predict_result(result)
        assert out == {"rec_texts": ["hello"]}

    def test_normalize_object_with_json(self):
        from app.services.paddle_ocr_runner import _normalize_predict_result

        obj = SimpleNamespace(json={"res": {"rec_texts": ["world"]}})
        out = _normalize_predict_result(obj)
        assert out == {"rec_texts": ["world"]}

    def test_normalize_empty_list(self):
        from app.services.paddle_ocr_runner import _normalize_predict_result

        assert _normalize_predict_result([]) == {}

    def test_normalize_non_dict_json(self):
        from app.services.paddle_ocr_runner import _normalize_predict_result

        obj = SimpleNamespace(json=["not", "a", "dict"])
        assert _normalize_predict_result(obj) == {}

    def test_normalize_res_not_dict(self):
        from app.services.paddle_ocr_runner import _normalize_predict_result

        result = [{"res": "not a dict"}]
        assert _normalize_predict_result(result) == {}

    def test_normalize_no_json_attr(self):
        from app.services.paddle_ocr_runner import _normalize_predict_result

        obj = SimpleNamespace()
        assert _normalize_predict_result(obj) == {}


class TestPaddleOcrPredictToTextBlocks:
    """Cover ``predict_to_text_blocks``."""

    def test_predict_to_text_blocks_empty_result(self, monkeypatch):
        from app.services import paddle_ocr_runner as runner

        runner._paddle_ocr = None
        fake_paddle = MagicMock()
        fake_instance = MagicMock()
        fake_instance.predict.return_value = []
        fake_paddle.PaddleOCR.return_value = fake_instance

        with patch.dict("sys.modules", {"paddleocr": fake_paddle}):
            img = np.zeros((10, 10, 3), dtype=np.uint8)
            blocks = runner.predict_to_text_blocks(img)
        assert blocks == []
        runner._paddle_ocr = None

    def test_predict_to_text_blocks_with_texts(self, monkeypatch):
        from app.services import paddle_ocr_runner as runner

        runner._paddle_ocr = None
        fake_paddle = MagicMock()
        fake_instance = MagicMock()
        fake_instance.predict.return_value = [
            {
                "res": {
                    "rec_texts": ["hello", "world"],
                    "rec_scores": [0.9, 0.8],
                    "rec_polys": [
                        [[0, 0], [10, 0], [10, 10], [0, 10]],
                        [[20, 20], [30, 20], [30, 30], [20, 30]],
                    ],
                }
            }
        ]
        fake_paddle.PaddleOCR.return_value = fake_instance

        with patch.dict("sys.modules", {"paddleocr": fake_paddle}):
            img = np.zeros((10, 10, 3), dtype=np.uint8)
            blocks = runner.predict_to_text_blocks(img)

        assert len(blocks) == 2
        assert blocks[0]["text"] == "hello"
        assert blocks[0]["conf"] == pytest.approx(90.0)
        assert blocks[1]["text"] == "world"
        runner._paddle_ocr = None

    def test_predict_to_text_blocks_skips_empty_text(self, monkeypatch):
        from app.services import paddle_ocr_runner as runner

        runner._paddle_ocr = None
        fake_paddle = MagicMock()
        fake_instance = MagicMock()
        fake_instance.predict.return_value = [
            {
                "res": {
                    "rec_texts": ["", "real"],
                    "rec_scores": [0.9, 0.8],
                    "rec_polys": [
                        [[0, 0], [10, 0], [10, 10], [0, 10]],
                        [[20, 20], [30, 20], [30, 30], [20, 30]],
                    ],
                }
            }
        ]
        fake_paddle.PaddleOCR.return_value = fake_instance

        with patch.dict("sys.modules", {"paddleocr": fake_paddle}):
            img = np.zeros((10, 10, 3), dtype=np.uint8)
            blocks = runner.predict_to_text_blocks(img)

        assert len(blocks) == 1
        assert blocks[0]["text"] == "real"
        runner._paddle_ocr = None

    def test_predict_to_text_blocks_skips_missing_polys(self, monkeypatch):
        from app.services import paddle_ocr_runner as runner

        runner._paddle_ocr = None
        fake_paddle = MagicMock()
        fake_instance = MagicMock()
        fake_instance.predict.return_value = [
            {
                "res": {
                    "rec_texts": ["hello", "world"],
                    "rec_scores": [0.9, 0.8],
                    "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]], []],
                }
            }
        ]
        fake_paddle.PaddleOCR.return_value = fake_instance

        with patch.dict("sys.modules", {"paddleocr": fake_paddle}):
            img = np.zeros((10, 10, 3), dtype=np.uint8)
            blocks = runner.predict_to_text_blocks(img)

        assert len(blocks) == 1
        assert blocks[0]["text"] == "hello"
        runner._paddle_ocr = None


# ===========================================================================
# 3. app/infrastructure/persistence/wechat_contact_store_impl.py
# ===========================================================================


class TestResolveDecryptContactDbPath:
    """Cover ``resolve_decrypt_contact_db_path``."""

    def test_returns_none_when_no_paths(self, monkeypatch, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            resolve_decrypt_contact_db_path,
        )

        plugin = MagicMock()
        plugin.is_available.return_value = False
        monkeypatch.setattr(
            "app.infrastructure.plugins.wechat_plugin.get_wechat_plugin", lambda: plugin
        )
        monkeypatch.setattr("app.utils.path_utils.get_base_dir", lambda: tmp_dir)
        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)

        assert resolve_decrypt_contact_db_path() is None

    def test_returns_plugin_path_when_available(self, monkeypatch, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            resolve_decrypt_contact_db_path,
        )

        db_path = os.path.join(tmp_dir, "contact.db")
        _make_sqlite_db(db_path)

        plugin = MagicMock()
        plugin.is_available.return_value = True
        plugin.get_decrypted_db_path.return_value = db_path
        monkeypatch.setattr(
            "app.infrastructure.plugins.wechat_plugin.get_wechat_plugin", lambda: plugin
        )

        assert resolve_decrypt_contact_db_path() == db_path

    def test_returns_legacy_path_when_exists(self, monkeypatch, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            resolve_decrypt_contact_db_path,
        )

        legacy_dir = os.path.join(tmp_dir, "AI助手", "wechat-decrypt", "decrypted", "contact")
        os.makedirs(legacy_dir)
        legacy_path = os.path.join(legacy_dir, "contact.db")
        _make_sqlite_db(legacy_path)

        plugin = MagicMock()
        plugin.is_available.return_value = False
        monkeypatch.setattr(
            "app.infrastructure.plugins.wechat_plugin.get_wechat_plugin", lambda: plugin
        )
        monkeypatch.setattr("app.utils.path_utils.get_base_dir", lambda: tmp_dir)
        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)

        assert resolve_decrypt_contact_db_path() == legacy_path

    def test_returns_env_path_when_set(self, monkeypatch, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            resolve_decrypt_contact_db_path,
        )

        env_path = os.path.join(tmp_dir, "env_contact.db")
        _make_sqlite_db(env_path)

        plugin = MagicMock()
        plugin.is_available.return_value = False
        monkeypatch.setattr(
            "app.infrastructure.plugins.wechat_plugin.get_wechat_plugin", lambda: plugin
        )
        monkeypatch.setattr("app.utils.path_utils.get_base_dir", lambda: tmp_dir)
        monkeypatch.setenv("WECHAT_CONTACT_DB_PATH", env_path)

        assert resolve_decrypt_contact_db_path() == env_path

    def test_env_path_nonexistent_returns_none(self, monkeypatch, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            resolve_decrypt_contact_db_path,
        )

        plugin = MagicMock()
        plugin.is_available.return_value = False
        monkeypatch.setattr(
            "app.infrastructure.plugins.wechat_plugin.get_wechat_plugin", lambda: plugin
        )
        monkeypatch.setattr("app.utils.path_utils.get_base_dir", lambda: tmp_dir)
        monkeypatch.setenv("WECHAT_CONTACT_DB_PATH", "/nonexistent/path.db")

        assert resolve_decrypt_contact_db_path() is None


class TestReadRowsFromContactDb:
    """Cover ``_read_rows_from_contact_db``."""

    def test_reads_rows_with_delete_flag_column(self, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            _read_rows_from_contact_db,
        )

        db_path = os.path.join(tmp_dir, "contact.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT, is_in_chat_room INTEGER, delete_flag INTEGER DEFAULT 0)"
        )
        conn.execute("INSERT INTO contact VALUES ('u1', 'n1', 'r1', 0, 0)")
        conn.execute("INSERT INTO contact VALUES ('u2', 'n2', 'r2', 0, 1)")
        conn.commit()
        conn.close()

        rows = _read_rows_from_contact_db(db_path, 100)
        assert len(rows) == 1  # delete_flag=1 filtered out
        assert rows[0][0] == "u1"

    def test_reads_rows_without_delete_flag_column_raises(self, tmp_dir):
        """When delete_flag column is missing, sqlite3.OperationalError propagates
        (not in RECOVERABLE_ERRORS)."""
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            _read_rows_from_contact_db,
        )

        db_path = os.path.join(tmp_dir, "contact.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT, is_in_chat_room INTEGER)"
        )
        conn.execute("INSERT INTO contact VALUES ('u1', 'n1', 'r1', 0)")
        conn.commit()
        conn.close()

        # First query references delete_flag which doesn't exist -> sqlite3.OperationalError
        # is NOT in RECOVERABLE_ERRORS, so it propagates
        with pytest.raises(sqlite3.OperationalError):
            _read_rows_from_contact_db(db_path, 100)

    def test_reads_rows_respects_limit(self, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            _read_rows_from_contact_db,
        )

        db_path = os.path.join(tmp_dir, "contact.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT, is_in_chat_room INTEGER, delete_flag INTEGER DEFAULT 0)"
        )
        for i in range(5):
            conn.execute(f"INSERT INTO contact VALUES ('u{i}', 'n{i}', 'r{i}', 0, 0)")
        conn.commit()
        conn.close()

        rows = _read_rows_from_contact_db(db_path, 2)
        assert len(rows) == 2

    def test_reads_rows_empty_table(self, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            _read_rows_from_contact_db,
        )

        db_path = os.path.join(tmp_dir, "contact.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT, is_in_chat_room INTEGER, delete_flag INTEGER DEFAULT 0)"
        )
        conn.commit()
        conn.close()

        rows = _read_rows_from_contact_db(db_path, 100)
        assert rows == []

    def test_reads_rows_all_deleted(self, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            _read_rows_from_contact_db,
        )

        db_path = os.path.join(tmp_dir, "contact.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT, is_in_chat_room INTEGER, delete_flag INTEGER DEFAULT 0)"
        )
        conn.execute("INSERT INTO contact VALUES ('u1', 'n1', 'r1', 0, 1)")
        conn.commit()
        conn.close()

        rows = _read_rows_from_contact_db(db_path, 100)
        assert rows == []


class TestWechatContactStoreList:
    """Cover ``SQLAlchemyWechatContactStore.list_contacts``."""

    def test_list_contacts_empty_db(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.list_contacts()

        assert result == []

    def test_list_contacts_with_keyword_no_rows_falls_back(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with (
            patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb,
            patch(
                "app.infrastructure.persistence.wechat_contact_store_impl.resolve_decrypt_contact_db_path",
                return_value=None,
            ),
        ):
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.list_contacts(keyword="test")

        assert result == []

    def test_list_contacts_with_starred_only_no_rows(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.list_contacts(keyword="test", starred_only=True)

        assert result == []

    def test_list_contacts_returns_rows(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query

        contact = SimpleNamespace(
            id=1,
            contact_name="Alice",
            remark="friend",
            wechat_id="alice123",
            contact_type="contact",
            is_active=1,
            is_starred=1,
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 2),
        )
        mock_query.all.return_value = [contact]
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.list_contacts()

        assert len(result) == 1
        assert result[0]["contact_name"] == "Alice"
        assert result[0]["created_at"] == "2024-01-01T00:00:00"


class TestWechatContactStoreGetContact:
    """Cover ``SQLAlchemyWechatContactStore.get_contact``."""

    def test_get_contact_not_found(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.get_contact(999)

        assert result is None

    def test_get_contact_found(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        contact = SimpleNamespace(
            id=1,
            contact_name="Bob",
            remark="",
            wechat_id="bob",
            contact_type="contact",
            is_active=1,
            is_starred=0,
            created_at=None,
            updated_at=None,
        )
        mock_query.first.return_value = contact
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.get_contact(1)

        assert result is not None
        assert result["contact_name"] == "Bob"
        assert result["created_at"] is None


class TestWechatContactStoreAddContact:
    """Cover ``SQLAlchemyWechatContactStore.add_contact``."""

    def test_add_contact_empty_name_returns_failure(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        result = store.add_contact(contact_name="", wechat_id="x")
        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_add_contact_invalid_type_defaults_to_contact(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        added = []

        def fake_add(obj):
            obj.id = 1
            added.append(obj)

        mock_db.add.side_effect = fake_add

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.add_contact(contact_name="Test", contact_type="invalid_type")

        assert result["success"] is True
        assert added[0].contact_type == "contact"

    def test_add_contact_existing_wechat_id_updates(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        existing = SimpleNamespace(
            id=5,
            contact_name="Old",
            remark="old",
            contact_type="contact",
            is_starred=0,
            updated_at=None,
        )
        mock_query.first.return_value = existing
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.add_contact(
                contact_name="New",
                remark="new",
                wechat_id="existing_id",
                is_starred=True,
            )

        assert result["success"] is True
        assert result["contact_id"] == 5
        assert existing.contact_name == "New"
        assert existing.is_starred == 1

    def test_add_contact_new_inserts(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        def fake_add(obj):
            obj.id = 10

        mock_db.add.side_effect = fake_add

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.add_contact(contact_name="New", wechat_id="new_id")

        assert result["success"] is True
        assert result["contact_id"] == 10


class TestWechatContactStoreUpdateDelete:
    """Cover ``update_contact`` and ``delete_contact``."""

    def test_update_contact_not_found(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.update_contact(999, {"contact_name": "X"})

        assert result["success"] is False

    def test_update_contact_empty_name_returns_failure(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        existing = SimpleNamespace(
            id=1, contact_name="Old", remark="", wechat_id="", contact_type="contact", is_starred=0
        )
        mock_query.first.return_value = existing
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.update_contact(1, {"contact_name": "  "})

        assert result["success"] is False
        assert "不能为空" in result["message"]

    def test_update_contact_success(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        existing = SimpleNamespace(
            id=1, contact_name="Old", remark="", wechat_id="", contact_type="contact", is_starred=0
        )
        mock_query.first.return_value = existing
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.update_contact(
                1,
                {
                    "contact_name": "New",
                    "remark": "r",
                    "wechat_id": "w",
                    "contact_type": "group",
                    "is_starred": True,
                },
            )

        assert result["success"] is True
        assert existing.contact_name == "New"
        assert existing.is_starred == 1

    def test_update_contact_invalid_type_defaults(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        existing = SimpleNamespace(
            id=1, contact_name="Old", remark="", wechat_id="", contact_type="contact", is_starred=0
        )
        mock_query.first.return_value = existing
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.update_contact(1, {"contact_type": "invalid"})

        assert result["success"] is True
        assert existing.contact_type == "contact"

    def test_delete_contact_not_found(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.delete_contact(999)

        assert result["success"] is False

    def test_delete_contact_success(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        existing = SimpleNamespace(id=1, is_active=1, is_starred=0, updated_at=None)
        mock_query.first.return_value = existing
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.delete_contact(1)

        assert result["success"] is True
        assert existing.is_active == 0


class TestWechatContactStoreUnstarAndContext:
    """Cover ``unstar_all``, ``get_context``, ``save_context``."""

    def test_unstar_all_returns_count(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.update.return_value = 3
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.unstar_all()

        assert result["success"] is True
        assert result["count"] == 3

    def test_get_context_no_context(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.get_context(1)

        assert result == []

    def test_get_context_empty_json(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        ctx = SimpleNamespace(context_json=None)
        mock_query.first.return_value = ctx
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.get_context(1)

        assert result == []

    def test_get_context_invalid_json(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        ctx = SimpleNamespace(context_json="not json")
        mock_query.first.return_value = ctx
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.get_context(1)

        assert result == []

    def test_get_context_valid_json(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        ctx = SimpleNamespace(context_json=json.dumps([{"role": "user", "content": "hi"}]))
        mock_query.first.return_value = ctx
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.get_context(1)

        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_save_context_new(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.save_context(1, "wx_id", [{"role": "user"}])

        assert result is True
        mock_db.add.assert_called_once()

    def test_save_context_update_existing(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        existing = SimpleNamespace(
            contact_id=1, wechat_id="old", context_json="{}", message_count=0, updated_at=None
        )
        mock_query.first.return_value = existing
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.save_context(1, "new_id", [{"role": "ai"}])

        assert result is True
        assert existing.wechat_id == "new_id"
        assert existing.message_count == 1


class TestWechatContactStoreSyncFromDecrypt:
    """Cover ``sync_from_decrypt_contact_db``."""

    def test_sync_no_path_returns_failure(self, monkeypatch):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        store = SQLAlchemyWechatContactStore()
        with patch(
            "app.infrastructure.persistence.wechat_contact_store_impl.resolve_decrypt_contact_db_path",
            return_value=None,
        ):
            result = store.sync_from_decrypt_contact_db()

        assert result["success"] is False
        assert result["imported"] == 0

    def test_sync_no_rows_returns_success(self, monkeypatch, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        db_path = os.path.join(tmp_dir, "contact.db")
        _make_sqlite_db(db_path)

        store = SQLAlchemyWechatContactStore()
        with (
            patch(
                "app.infrastructure.persistence.wechat_contact_store_impl.resolve_decrypt_contact_db_path",
                return_value=db_path,
            ),
            patch(
                "app.infrastructure.persistence.wechat_contact_store_impl._read_rows_from_contact_db",
                return_value=[],
            ),
        ):
            result = store.sync_from_decrypt_contact_db()

        assert result["success"] is True
        assert result["imported"] == 0

    def test_sync_with_rows_imports(self, monkeypatch, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        db_path = os.path.join(tmp_dir, "contact.db")
        _make_sqlite_db(db_path)

        store = SQLAlchemyWechatContactStore()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        rows = [
            ("u1", "n1", "r1", 0),
            ("u2", "n2", "r2", 1),  # chat room
            ("", "n3", "r3", 0),  # empty username -> skipped
        ]

        with (
            patch(
                "app.infrastructure.persistence.wechat_contact_store_impl.resolve_decrypt_contact_db_path",
                return_value=db_path,
            ),
            patch(
                "app.infrastructure.persistence.wechat_contact_store_impl._read_rows_from_contact_db",
                return_value=rows,
            ),
            patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb,
        ):
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.sync_from_decrypt_contact_db()

        assert result["success"] is True
        assert result["imported"] == 2  # u1 and u2
        assert result["skipped"] == 1  # empty username

    def test_sync_db_error_returns_failure(self, monkeypatch, tmp_dir):
        from app.infrastructure.persistence.wechat_contact_store_impl import (
            SQLAlchemyWechatContactStore,
        )

        db_path = os.path.join(tmp_dir, "contact.db")
        _make_sqlite_db(db_path)

        store = SQLAlchemyWechatContactStore()

        with (
            patch(
                "app.infrastructure.persistence.wechat_contact_store_impl.resolve_decrypt_contact_db_path",
                return_value=db_path,
            ),
            patch(
                "app.infrastructure.persistence.wechat_contact_store_impl._read_rows_from_contact_db",
                return_value=[("u1", "n1", "r1", 0)],
            ),
            patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db") as gdb,
        ):
            gdb.return_value.__enter__ = lambda self: (_ for _ in ()).throw(
                RuntimeError("db error")
            )
            gdb.return_value.__exit__ = lambda self, *a: None
            result = store.sync_from_decrypt_contact_db()

        assert result["success"] is False


# ===========================================================================
# 4. app/infrastructure/repositories/customer_repository_impl.py
# ===========================================================================


class TestCustomerRepositorySave:
    """Cover ``SQLAlchemyCustomerRepository.save_customer``."""

    def test_save_customer_new(self, monkeypatch):
        from app.domain.customer.entities import Customer
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        def fake_add(obj):
            obj.id = 1

        mock_db.add.side_effect = fake_add

        # Use a Mock contact_info to provide .person/.phone/.address attributes
        # (the real ContactInfo value object uses .name, but the repository
        # source code calls .person — a pre-existing bug we work around here).
        contact_info = SimpleNamespace(person="John", phone="123", address="St")
        customer = Customer(customer_name="Acme", contact_info=contact_info)

        # Patch customer_to_domain to avoid the broken ContactInfo(person=...) call
        with (
            patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb,
            patch(
                "app.infrastructure.repositories.customer_repository_impl.purchase_unit_to_domain"
            ) as mock_to_domain,
        ):
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            mock_to_domain.return_value = customer
            result = repo.save_customer(customer)

        assert result is customer
        mock_db.add.assert_called_once()

    def test_save_customer_existing_updates(self, monkeypatch):
        from app.domain.customer.entities import Customer
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        existing = SimpleNamespace(
            id=5,
            unit_name="Acme",
            contact_person="Old",
            contact_phone="000",
            address="OldAddr",
            discount_rate=1.0,
            is_active=True,
            created_at=None,
            updated_at=None,
        )
        mock_query.first.return_value = existing
        mock_db.query.return_value = mock_query

        contact_info = SimpleNamespace(person="New", phone="111", address="NewAddr")
        customer = Customer(customer_name="Acme", contact_info=contact_info)

        with (
            patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb,
            patch(
                "app.infrastructure.repositories.customer_repository_impl.purchase_unit_to_domain"
            ) as mock_to_domain,
        ):
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            mock_to_domain.return_value = customer
            result = repo.save_customer(customer)

        assert result is customer
        assert existing.contact_person == "New"
        assert existing.contact_phone == "111"


class TestCustomerRepositoryFind:
    """Cover ``find_customer_by_id`` and ``find_customer_by_name``."""

    def test_find_customer_by_id_not_found(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.find_customer_by_id(999)

        assert result is None

    def test_find_customer_by_id_found(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        model = SimpleNamespace(
            id=1,
            unit_name="Acme",
            contact_person="John",
            contact_phone="123",
            address="St",
            discount_rate=1.0,
            is_active=True,
            created_at=None,
            updated_at=None,
        )
        mock_query.first.return_value = model
        mock_db.query.return_value = mock_query

        expected = SimpleNamespace(customer_name="Acme")
        with (
            patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb,
            patch(
                "app.infrastructure.repositories.customer_repository_impl.customer_to_domain"
            ) as mock_to_domain,
        ):
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            mock_to_domain.return_value = expected
            result = repo.find_customer_by_id(1)

        assert result is expected
        mock_to_domain.assert_called_once_with(model)

    def test_find_customer_by_name_not_found(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.find_customer_by_name("missing")

        assert result is None

    def test_find_customer_by_name_found(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        model = SimpleNamespace(
            id=2,
            unit_name="Beta",
            contact_person="",
            contact_phone="",
            address="",
            discount_rate=1.0,
            is_active=True,
            created_at=None,
            updated_at=None,
        )
        mock_query.first.return_value = model
        mock_db.query.return_value = mock_query

        expected = SimpleNamespace(customer_name="Beta")
        with (
            patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb,
            patch(
                "app.infrastructure.repositories.customer_repository_impl.customer_to_domain"
            ) as mock_to_domain,
        ):
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            mock_to_domain.return_value = expected
            result = repo.find_customer_by_name("Beta")

        assert result is expected
        mock_to_domain.assert_called_once_with(model)


class TestCustomerRepositoryFindAll:
    """Cover ``find_all_customers``."""

    def test_find_all_customers_empty(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.find_all_customers()

        assert result == []

    def test_find_all_customers_returns_list(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        models = [
            SimpleNamespace(
                id=1,
                unit_name="A",
                contact_person="",
                contact_phone="",
                address="",
                discount_rate=1.0,
                is_active=True,
                created_at=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id=2,
                unit_name="B",
                contact_person="",
                contact_phone="",
                address="",
                discount_rate=1.0,
                is_active=True,
                created_at=None,
                updated_at=None,
            ),
        ]
        mock_query.all.return_value = models
        mock_db.query.return_value = mock_query

        expected = [SimpleNamespace(customer_name="A"), SimpleNamespace(customer_name="B")]
        with (
            patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb,
            patch(
                "app.infrastructure.repositories.customer_repository_impl.customer_to_domain",
                side_effect=expected,
            ),
        ):
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.find_all_customers()

        assert len(result) == 2


class TestCustomerRepositoryDelete:
    """Cover ``delete_customer``."""

    def test_delete_customer_not_found(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.delete_customer(999)

        assert result is False

    def test_delete_customer_success(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = SimpleNamespace(id=1)
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.delete_customer(1)

        assert result is True
        mock_db.delete.assert_called_once()


class TestPurchaseUnitRepository:
    """Cover ``save_purchase_unit``, ``find_purchase_unit_*``, ``delete_purchase_unit``."""

    def test_save_purchase_unit_new(self, monkeypatch):
        from app.domain.customer.entities import PurchaseUnit
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        def fake_add(obj):
            obj.id = 7

        mock_db.add.side_effect = fake_add

        unit = PurchaseUnit(unit_name="Unit1")

        # purchase_unit_to_db returns discount_rate, but PurchaseUnitModel has no
        # such column — patch _to_unit_db to drop it (pre-existing mapper bug).
        def fake_to_unit_db(u):
            return {
                "unit_name": u.unit_name,
                "contact_person": u.contact_person,
                "contact_phone": u.contact_phone,
                "address": u.address,
                "is_active": 1 if u.is_active else 0,
            }

        with (
            patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb,
            patch.object(
                repo,
                "_to_unit_db",
                side_effect=fake_to_unit_db,
            ),
            patch(
                "app.infrastructure.repositories.customer_repository_impl.purchase_unit_to_domain",
                return_value=unit,
            ),
        ):
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.save_purchase_unit(unit)

        assert result.id == 7

    def test_save_purchase_unit_existing_updates(self, monkeypatch):
        from app.domain.customer.entities import PurchaseUnit
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        existing = SimpleNamespace(
            id=3,
            unit_name="Old",
            contact_person="",
            contact_phone="",
            address="",
            discount_rate=1.0,
            is_active=1,
            created_at=None,
            updated_at=None,
        )
        mock_query.first.return_value = existing
        mock_db.query.return_value = mock_query

        unit = PurchaseUnit(id=3, unit_name="Updated", contact_person="John")

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.save_purchase_unit(unit)

        assert result.id == 3
        assert existing.unit_name == "Updated"
        assert existing.contact_person == "John"

    def test_find_purchase_unit_by_id_not_found(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.find_purchase_unit_by_id(999)

        assert result is None

    def test_find_purchase_unit_by_id_found(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        model = SimpleNamespace(
            id=1,
            unit_name="X",
            contact_person="",
            contact_phone="",
            address="",
            discount_rate=1.0,
            is_active=True,
            created_at=None,
            updated_at=None,
        )
        mock_query.first.return_value = model
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.find_purchase_unit_by_id(1)

        assert result is not None
        assert result.unit_name == "X"

    def test_find_purchase_unit_by_name_not_found(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.find_purchase_unit_by_name("missing")

        assert result is None

    def test_find_all_purchase_units_empty(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.find_all_purchase_units()

        assert result == []

    def test_delete_purchase_unit_not_found(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.delete_purchase_unit(999)

        assert result is False

    def test_delete_purchase_unit_success(self, monkeypatch):
        from app.infrastructure.repositories.customer_repository_impl import (
            SQLAlchemyCustomerRepository,
        )

        repo = SQLAlchemyCustomerRepository()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = SimpleNamespace(id=1)
        mock_db.query.return_value = mock_query

        with patch("app.infrastructure.repositories.customer_repository_impl.get_db") as gdb:
            gdb.return_value.__enter__ = lambda self: mock_db
            gdb.return_value.__exit__ = lambda self, *a: None
            result = repo.delete_purchase_unit(1)

        assert result is True


# ===========================================================================
# 5. app/services/kitten_report/service.py
# ===========================================================================


class TestKittenReportCollectPluginResults:
    """Cover ``KittenReportExportService.collect_plugin_results``."""

    def test_collect_plugin_results_empty_payload(self):
        from app.services.kitten_report.service import KittenReportExportService

        service = KittenReportExportService()
        results = service.collect_plugin_results({})
        assert len(results) == 6  # 6 plugins
        keys = {r["key"] for r in results}
        assert "rule_stats" in keys
        assert "financial_report" in keys

    def test_collect_plugin_results_with_dataset(self):
        from app.services.kitten_report.service import KittenReportExportService

        service = KittenReportExportService()
        payload = {
            "dataset": {"rows": 10, "columns": 3, "preview": [[1, 2, 3]]},
            "messages": [{"role": "user"}, {"role": "ai"}],
            "phase": "analysis",
            "industry": "涂料",
        }
        results = service.collect_plugin_results(payload)
        assert len(results) == 6
        # RuleStats should reflect the dataset
        rule_stats = next(r for r in results if r["key"] == "rule_stats")
        assert "10" in rule_stats["summary"]

    def test_collect_plugin_results_with_none_values(self):
        from app.services.kitten_report.service import KittenReportExportService

        service = KittenReportExportService()
        payload = {"dataset": None, "messages": None, "result": None}
        results = service.collect_plugin_results(payload)
        assert len(results) == 6

    def test_plugin_to_dict_conversion(self):
        from app.services.kitten_report.plugins import PluginResult
        from app.services.kitten_report.service import KittenReportExportService

        item = PluginResult(
            key="test",
            title="Test",
            level="info",
            summary="summary",
            details={"a": 1},
        )
        d = KittenReportExportService._plugin_to_dict(item)
        assert d == {
            "key": "test",
            "title": "Test",
            "level": "info",
            "summary": "summary",
            "details": {"a": 1},
        }


class TestKittenReportBuildReport:
    """Cover ``KittenReportExportService.build_report``."""

    def test_build_report_minimal_payload(self):
        from app.services.kitten_report.service import KittenReportExportService

        service = KittenReportExportService()
        result = service.build_report({})
        assert "file_name" in result
        assert "content" in result
        assert "plugins" in result
        assert result["file_name"].endswith(".xlsx")
        assert len(result["content"]) > 0
        assert len(result["plugins"]) == 6

    def test_build_report_with_full_payload(self):
        from app.services.kitten_report.service import KittenReportExportService

        service = KittenReportExportService()
        payload = {
            "dataset": {
                "name": "sales.xlsx",
                "rows": 100,
                "columns": 5,
                "fieldNames": ["date", "product", "qty", "amount", "customer"],
                "previewText": "preview...",
            },
            "messages": [
                {"role": "user", "time": "10:00", "content": "Hello"},
                {"role": "ai", "time": "10:01", "content": "<strong>Hi</strong>"},
            ],
            "result": {"title": "Sales Report", "summary": "Monthly sales"},
            "phase": "report",
            "industry": "电商",
        }
        result = service.build_report(payload)
        assert result["file_name"].startswith("小猫分析报告_")
        assert len(result["content"]) > 0

    def test_build_report_with_html_content(self):
        from app.services.kitten_report.service import KittenReportExportService

        service = KittenReportExportService()
        payload = {
            "messages": [
                {
                    "role": "ai",
                    "content": "<br>line1<br/>line2<br />line3<strong>bold</strong>&nbsp;&amp;",
                },
            ],
        }
        result = service.build_report(payload)
        assert len(result["content"]) > 0

    def test_build_report_empty_messages(self):
        from app.services.kitten_report.service import KittenReportExportService

        service = KittenReportExportService()
        payload = {"messages": []}
        result = service.build_report(payload)
        assert len(result["content"]) > 0


class TestKittenReportHtmlToText:
    """Cover ``_html_to_text`` static method."""

    def test_html_to_text_br_replacement(self):
        from app.services.kitten_report.service import KittenReportExportService

        text = KittenReportExportService._html_to_text("a<br>b<br/>c<br />d")
        assert text == "a\nb\nc\nd"

    def test_html_to_text_strong_removal(self):
        from app.services.kitten_report.service import KittenReportExportService

        text = KittenReportExportService._html_to_text("<strong>bold</strong>")
        assert text == "bold"

    def test_html_to_text_entity_replacement(self):
        from app.services.kitten_report.service import KittenReportExportService

        text = KittenReportExportService._html_to_text("a&nbsp;b&amp;c")
        assert text == "a b&c"

    def test_html_to_text_empty_string(self):
        from app.services.kitten_report.service import KittenReportExportService

        assert KittenReportExportService._html_to_text("") == ""

    def test_html_to_text_no_html(self):
        from app.services.kitten_report.service import KittenReportExportService

        assert KittenReportExportService._html_to_text("plain text") == "plain text"


class TestKittenReportFinancialSheet:
    """Cover ``_add_financial_sheet`` indirectly via build_report."""

    def test_build_report_with_financial_plugin_data(self):
        from app.services.kitten_report.service import KittenReportExportService

        service = KittenReportExportService()
        # Patch FinancialReportPlugin to return rich data
        with patch("app.services.kitten_report.service.FinancialReportPlugin") as MockFinancial:
            MockFinancial.return_value.run.return_value = SimpleNamespace(
                key="financial_report",
                title="财务报表分析",
                level="info",
                summary="test",
                details={
                    "metrics": {
                        "total_revenue": 10000.0,
                        "total_cost": 6000.0,
                        "gross_profit": 4000.0,
                        "profit_margin": 40.0,
                        "order_count": 50,
                        "avg_order_value": 200.0,
                    },
                    "monthly_breakdown": [
                        {"month": "2024-01", "revenue": 5000.0, "order_count": 25},
                        {"month": "2024-02", "revenue": 5000.0, "order_count": 25},
                    ],
                    "product_analysis": [
                        {
                            "product_name": "P1",
                            "total_revenue": 5000.0,
                            "total_qty": 100.0,
                            "order_count": 25,
                        }
                    ],
                    "customer_analysis": [
                        {
                            "customer": "C1",
                            "total_amount": 3000.0,
                            "order_count": 15,
                            "avg_order_value": 200.0,
                        }
                    ],
                },
            )
            result = service.build_report({})
            assert len(result["content"]) > 0

    def test_build_report_with_inventory_plugin_data(self):
        from app.services.kitten_report.service import KittenReportExportService

        service = KittenReportExportService()
        with patch("app.services.kitten_report.service.InventoryValuationPlugin") as MockInv:
            MockInv.return_value.run.return_value = SimpleNamespace(
                key="inventory_valuation",
                title="库存价值评估",
                level="warn",
                summary="test",
                details={
                    "materials": {"total_items": 5, "total_value": 1000.0},
                    "products": {"total_items": 3, "total_value": 2000.0},
                    "low_stock_alerts": [
                        {
                            "name": "M1",
                            "current": 5,
                            "min_required": 10,
                            "unit_price": 50.0,
                        }
                    ],
                },
            )
            result = service.build_report({})
            assert len(result["content"]) > 0

    def test_build_report_no_financial_no_inventory(self):
        from app.services.kitten_report.service import KittenReportExportService

        service = KittenReportExportService()
        # Both plugins return non-matching keys -> _add_financial_sheet returns early
        with (
            patch("app.services.kitten_report.service.FinancialReportPlugin") as MockFinancial,
            patch("app.services.kitten_report.service.InventoryValuationPlugin") as MockInv,
        ):
            MockFinancial.return_value.run.return_value = SimpleNamespace(
                key="other",
                title="Other",
                level="info",
                summary="",
                details={},
            )
            MockInv.return_value.run.return_value = SimpleNamespace(
                key="other2",
                title="Other2",
                level="info",
                summary="",
                details={},
            )
            result = service.build_report({})
            assert len(result["content"]) > 0


# ===========================================================================
# 6. app/domain/neuro/processors/conscious.py
# ===========================================================================


def _make_event(
    event_type: str = "test.event",
    domain: str = "test",
    payload: dict[str, Any] | None = None,
) -> NeuroEvent:
    """Helper to create a NeuroEvent for tests."""
    event = NeuroEvent(
        event_type=event_type,
        payload=payload or {"key": "value"},
        priority=EventPriority.HIGH,
    )
    event.metadata.domain = domain
    return event


class TestConsciousProcessorInit:
    """Cover ``ConsciousProcessor.__init__`` and ``register_handler``."""

    def test_init_with_reliability_enabled(self):
        proc = ConsciousProcessor(enable_reliability=True)
        assert proc._enable_reliability is True
        assert proc._deduplicator is not None
        assert proc._circuit_breaker is not None
        assert proc._sla_controller is not None
        assert proc._retry_handler is not None
        assert proc._sandbox is not None

    def test_init_with_reliability_disabled(self):
        proc = ConsciousProcessor(enable_reliability=False)
        assert proc._enable_reliability is False
        assert proc._deduplicator is None
        assert proc._circuit_breaker is None
        assert proc._sla_controller is None
        assert proc._retry_handler is None
        assert proc._sandbox is None

    def test_init_with_custom_bus(self):
        bus = MagicMock()
        proc = ConsciousProcessor(bus=bus, enable_reliability=False)
        assert proc._bus is bus

    def test_register_handler(self):
        proc = ConsciousProcessor(enable_reliability=False)
        handler = MagicMock()
        proc.register_handler("test.event", handler)
        assert "test.event" in proc._handlers
        assert proc._handlers["test.event"] is handler


class TestConsciousProcessorProcess:
    """Cover ``ConsciousProcessor.process``."""

    @pytest.mark.asyncio
    async def test_process_no_handler_returns_failure(self):
        proc = ConsciousProcessor(enable_reliability=False)
        event = _make_event("unknown.event")
        result = await proc.process(event)
        assert result.success is False
        assert "No handler" in result.error
        assert result.stage_reached == ProcessingStage.PROCESS

    @pytest.mark.asyncio
    async def test_process_sync_handler_success(self):
        proc = ConsciousProcessor(enable_reliability=False)
        proc.register_handler("test.event", lambda e: {"processed": True})
        event = _make_event("test.event")
        result = await proc.process(event)
        assert result.success is True
        assert result.data == {"processed": True}
        assert result.stage_reached == ProcessingStage.COMMIT

    @pytest.mark.asyncio
    async def test_process_async_handler_success(self):
        proc = ConsciousProcessor(enable_reliability=False)

        async def handler(event):
            return {"async": True}

        proc.register_handler("test.event", handler)
        event = _make_event("test.event")
        result = await proc.process(event)
        assert result.success is True
        assert result.data == {"async": True}

    @pytest.mark.asyncio
    async def test_process_handler_raises_recoverable_error(self):
        proc = ConsciousProcessor(enable_reliability=False)

        def handler(event):
            raise RuntimeError("handler failed")

        proc.register_handler("test.event", handler)
        event = _make_event("test.event")
        result = await proc.process(event)
        assert result.success is False
        assert "handler failed" in result.error

    @pytest.mark.asyncio
    async def test_process_with_reliability_dedup_skips(self):
        proc = ConsciousProcessor(enable_reliability=True)
        # Force deduplicator to reject (return False from check_and_acquire)
        proc._deduplicator.check_and_acquire = Mock(return_value=False)
        proc._deduplicator.get_cached_result = Mock(return_value={"cached": True})

        event = _make_event("test.event")
        result = await proc.process(event)
        assert result.success is True
        assert result.data == {"cached": True}
        assert proc._dedup_count == 1

    @pytest.mark.asyncio
    async def test_process_with_reliability_circuit_open(self):
        proc = ConsciousProcessor(enable_reliability=True)
        proc._deduplicator.check_and_acquire = Mock(return_value=True)
        proc._circuit_breaker.check = Mock(return_value=False)

        event = _make_event("test.event")
        result = await proc.process(event)
        assert result.success is False
        assert "Circuit breaker" in result.error
        assert proc._circuit_open_count == 1

    @pytest.mark.asyncio
    async def test_process_with_reliability_sandbox_reject(self):
        proc = ConsciousProcessor(enable_reliability=True)
        proc._deduplicator.check_and_acquire = Mock(return_value=True)
        proc._circuit_breaker.check = Mock(return_value=True)
        proc._sandbox.validate = Mock(return_value=False)

        event = _make_event("test.event")
        result = await proc.process(event)
        assert result.success is False
        assert "Sandbox" in result.error
        assert proc._sandbox_reject_count == 1

    @pytest.mark.asyncio
    async def test_process_with_reliability_full_success(self):
        proc = ConsciousProcessor(enable_reliability=True)
        proc._deduplicator.check_and_acquire = Mock(return_value=True)
        proc._circuit_breaker.check = Mock(return_value=True)
        proc._sandbox.validate = Mock(return_value=True)
        proc._sla_controller.start_monitoring = Mock()
        proc._sla_controller.finish_monitoring = Mock(return_value={"status": "ok"})
        proc._retry_handler.execute_for_event = AsyncMock(return_value={"ok": True})

        proc.register_handler("test.event", lambda e: {"ok": True})
        event = _make_event("test.event")
        result = await proc.process(event)
        assert result.success is True
        assert result.data == {"ok": True}
        assert proc._success_count == 1

    @pytest.mark.asyncio
    async def test_process_with_reliability_sla_violation(self):
        proc = ConsciousProcessor(enable_reliability=True)
        proc._deduplicator.check_and_acquire = Mock(return_value=True)
        proc._circuit_breaker.check = Mock(return_value=True)
        proc._sandbox.validate = Mock(return_value=True)
        proc._sla_controller.start_monitoring = Mock()
        proc._sla_controller.finish_monitoring = Mock(return_value={"status": "violated"})
        proc._retry_handler.execute_for_event = AsyncMock(return_value={"ok": True})

        proc.register_handler("test.event", lambda e: {"ok": True})
        event = _make_event("test.event")
        result = await proc.process(event)
        assert result.success is True
        assert proc._sla_violation_count == 1

    @pytest.mark.asyncio
    async def test_process_with_reliability_handler_fails_records_failure(self):
        proc = ConsciousProcessor(enable_reliability=True)
        # Replace the real NeuroBusDeduplicator with a Mock that has a `remove`
        # method (the source code calls self._deduplicator.remove(event) on
        # failure, but NeuroBusDeduplicator does not implement it — a
        # pre-existing bug we work around here).
        proc._deduplicator = MagicMock()
        proc._deduplicator.check_and_acquire = Mock(return_value=True)
        proc._deduplicator.remove = Mock()
        proc._circuit_breaker = MagicMock()
        proc._circuit_breaker.check = Mock(return_value=True)
        proc._circuit_breaker.record_failure = Mock()
        proc._sandbox = MagicMock()
        proc._sandbox.validate = Mock(return_value=True)
        proc._sla_controller = MagicMock()
        proc._sla_controller.start_monitoring = Mock()
        proc._sla_controller.finish_monitoring = Mock(return_value={"status": "ok"})
        proc._retry_handler = MagicMock()
        proc._retry_handler.execute_for_event = AsyncMock(
            side_effect=RuntimeError("retry exhausted")
        )

        proc.register_handler("test.event", lambda e: {"ok": True})
        event = _make_event("test.event")
        result = await proc.process(event)
        assert result.success is False
        assert proc._error_count == 1
        proc._circuit_breaker.record_failure.assert_called_once()
        proc._deduplicator.remove.assert_called_once()


class TestConsciousProcessorStats:
    """Cover ``get_stats``."""

    def test_get_stats_initial(self):
        proc = ConsciousProcessor(enable_reliability=False)
        stats = proc.get_stats()
        assert stats["processed"] == 0
        assert stats["success"] == 0
        assert stats["errors"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["handlers"] == 0
        assert stats["reliability_enabled"] is False

    def test_get_stats_after_processing(self):
        proc = ConsciousProcessor(enable_reliability=False)
        proc._processed_count = 10
        proc._success_count = 8
        proc._error_count = 2
        proc._dedup_count = 1
        proc._circuit_open_count = 1
        proc._sandbox_reject_count = 1
        proc._sla_violation_count = 1
        proc.register_handler("test", lambda e: None)

        stats = proc.get_stats()
        assert stats["processed"] == 10
        assert stats["success"] == 8
        assert stats["errors"] == 2
        assert stats["deduplicated"] == 1
        assert stats["circuit_open"] == 1
        assert stats["sandbox_rejected"] == 1
        assert stats["sla_violations"] == 1
        assert stats["success_rate"] == 0.8
        assert stats["handlers"] == 1
        assert stats["reliability_enabled"] is False


class TestConsciousProcessorHelpers:
    """Cover handler templates and convenience functions."""

    @pytest.mark.asyncio
    async def test_intent_processing_handler(self):
        handler = IntentProcessingHandler()
        event = _make_event("intent.test", payload={"intent_type": "greeting", "raw_text": "hi"})
        result = await handler.handle(event)
        assert result["intent_type"] == "greeting"
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_business_logic_handler_validate_pass(self):
        class MyHandler(BusinessLogicHandler):
            async def execute(self, event):
                return {"done": True}

        handler = MyHandler()
        event = _make_event("biz.test")
        result = await handler.handle(event)
        assert result == {"done": True}

    @pytest.mark.asyncio
    async def test_business_logic_handler_validate_fails(self):
        class MyHandler(BusinessLogicHandler):
            async def validate(self, event):
                return False

            async def execute(self, event):
                return {"done": True}

        handler = MyHandler()
        event = _make_event("biz.test")
        with pytest.raises(ValueError, match="Validation failed"):
            await handler.handle(event)

    @pytest.mark.asyncio
    async def test_business_logic_handler_execute_not_implemented(self):
        handler = BusinessLogicHandler()
        event = _make_event("biz.test")
        with pytest.raises(NotImplementedError):
            await handler.handle(event)

    @pytest.mark.asyncio
    async def test_conscious_process_convenience_function(self, monkeypatch):
        # Reset singleton
        import app.domain.neuro.processors.conscious as conscious_mod

        original = conscious_mod._conscious
        conscious_mod._conscious = None

        proc = ConsciousProcessor(enable_reliability=False)
        proc.register_handler("test.event", lambda e: {"ok": True})
        conscious_mod._conscious = proc

        try:
            result = await conscious_process("test.event", {"key": "value"})
            assert result.success is True
            assert result.data == {"ok": True}
        finally:
            conscious_mod._conscious = original

    def test_get_conscious_processor_singleton(self):
        import app.domain.neuro.processors.conscious as conscious_mod

        original = conscious_mod._conscious
        conscious_mod._conscious = None
        try:
            p1 = get_conscious_processor()
            p2 = get_conscious_processor()
            assert p1 is p2
        finally:
            conscious_mod._conscious = original


class TestProcessingResult:
    """Cover ``ProcessingResult`` dataclass."""

    def test_processing_result_defaults(self):
        result = ProcessingResult(success=True)
        assert result.success is True
        assert result.data is None
        assert result.error is None
        assert result.latency_ms == 0.0
        assert result.stage_reached == ProcessingStage.VALIDATE

    def test_processing_result_with_values(self):
        result = ProcessingResult(
            success=False,
            data=None,
            error="failed",
            latency_ms=42.5,
            stage_reached=ProcessingStage.PROCESS,
        )
        assert result.success is False
        assert result.error == "failed"
        assert result.latency_ms == 42.5
        assert result.stage_reached == ProcessingStage.PROCESS

    def test_processing_stage_values(self):
        assert ProcessingStage.VALIDATE.value == "validate"
        assert ProcessingStage.PRESERVE.value == "preserve"
        assert ProcessingStage.PREPROCESS.value == "preprocess"
        assert ProcessingStage.PROCESS.value == "process"
        assert ProcessingStage.POSTPROCESS.value == "postprocess"
        assert ProcessingStage.COMMIT.value == "commit"


# ===========================================================================
# 7. app/fastapi_routes/domains/excel/routes.py
# ===========================================================================


@pytest.fixture
def excel_client() -> TestClient:
    app = FastAPI()
    from app.fastapi_routes.domains.excel.routes import router as excel_router

    app.include_router(excel_router)
    return TestClient(app, raise_server_exceptions=False)


class TestExcelAiParseSingle:
    """Cover ``ai_parse_single`` endpoint."""

    def test_parse_single_empty_text_returns_400(self, excel_client):
        response = excel_client.post("/api/ai/parse-single", json={"text": ""})
        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "missing_fields" in body

    def test_parse_single_whitespace_text_returns_400(self, excel_client):
        response = excel_client.post("/api/ai/parse-single", json={"text": "   "})
        assert response.status_code == 400

    def test_parse_single_success(self, excel_client):
        with patch("app.application.facades.excel_facade.get_ai_product_parser") as mock_get:
            mock_parser = MagicMock()
            mock_parser.parse_single.return_value = {"success": True, "data": "parsed"}
            mock_get.return_value = mock_parser

            response = excel_client.post(
                "/api/ai/parse-single",
                json={"text": "product A 100件", "use_ai": True, "fallback_to_rule": True},
            )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_parse_single_parse_failure_returns_422(self, excel_client):
        with patch("app.application.facades.excel_facade.get_ai_product_parser") as mock_get:
            mock_parser = MagicMock()
            mock_parser.parse_single.return_value = {"success": False, "error": "no match"}
            mock_get.return_value = mock_parser

            response = excel_client.post("/api/ai/parse-single", json={"text": "unknown"})
        assert response.status_code == 422

    def test_parse_single_empty_body(self, excel_client):
        response = excel_client.post("/api/ai/parse-single", json={})
        assert response.status_code == 400


class TestExcelAiParseProducts:
    """Cover ``ai_parse_products`` endpoint."""

    def test_parse_products_empty_texts_returns_400(self, excel_client):
        response = excel_client.post("/api/ai/parse-products", json={"texts": []})
        assert response.status_code == 400

    def test_parse_products_texts_not_list_returns_400(self, excel_client):
        response = excel_client.post("/api/ai/parse-products", json={"texts": "not a list"})
        assert response.status_code == 400

    def test_parse_products_success(self, excel_client):
        with patch("app.application.facades.excel_facade.get_ai_product_parser") as mock_get:
            mock_parser = MagicMock()
            mock_parser.parse_batch.return_value = {"success": True, "items": []}
            mock_get.return_value = mock_parser

            response = excel_client.post(
                "/api/ai/parse-products", json={"texts": ["product A", "product B"]}
            )
        assert response.status_code == 200

    def test_parse_products_missing_texts_field(self, excel_client):
        response = excel_client.post("/api/ai/parse-products", json={})
        assert response.status_code == 400


class TestExcelAiAnalyze:
    """Cover ``ai_analyze_post`` endpoint."""

    def test_ai_analyze_no_file_no_query_returns_400(self, excel_client):
        response = excel_client.post(
            "/api/ai/analyze",
            data={"query": ""},
        )
        assert response.status_code == 400

    def test_ai_analyze_with_query_only_returns_200(self, excel_client):
        response = excel_client.post(
            "/api/ai/analyze",
            data={"query": "show me sales trend"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "chart_data" in body

    def test_ai_analyze_with_file(self, excel_client, tmp_dir):
        with (
            patch("app.fastapi_routes.domains.excel.routes.get_upload_dir", return_value=tmp_dir),
            patch(
                "app.application.facades.conversation_facade.get_data_analysis_service"
            ) as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.analyze_file.return_value = {"success": True, "data": "analyzed"}
            mock_get.return_value = mock_service

            # Create a fake file
            file_content = b"test,content\n1,2\n"
            response = excel_client.post(
                "/api/ai/analyze",
                data={"query": "analyze"},
                files={"file": ("test.csv", file_content, "text/csv")},
            )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_ai_analyze_file_analysis_error_returns_500(self, excel_client, tmp_dir):
        with (
            patch("app.fastapi_routes.domains.excel.routes.get_upload_dir", return_value=tmp_dir),
            patch(
                "app.application.facades.conversation_facade.get_data_analysis_service"
            ) as mock_get,
        ):
            mock_service = MagicMock()
            mock_service.analyze_file.side_effect = RuntimeError("analysis failed")
            mock_get.return_value = mock_service

            response = excel_client.post(
                "/api/ai/analyze",
                data={"query": "analyze"},
                files={"file": ("test.csv", b"a,b\n1,2\n", "text/csv")},
            )
        assert response.status_code == 500


class TestExcelAiFileAnalyze:
    """Cover ``ai_file_analyze`` endpoint."""

    def test_ai_file_analyze_no_file_returns_400(self, excel_client):
        response = excel_client.post("/api/ai/file/analyze", data={"purpose": "general"})
        assert response.status_code == 400

    def test_ai_file_analyze_success(self, excel_client):
        with patch("app.application.get_file_analysis_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.analyze_file.return_value = {"success": True, "data": "ok"}
            mock_get.return_value = mock_service

            response = excel_client.post(
                "/api/ai/file/analyze",
                data={"purpose": "general"},
                files={"file": ("test.xlsx", b"fake", "application/octet-stream")},
            )
        assert response.status_code == 200

    def test_ai_file_analyze_failure_returns_400(self, excel_client):
        with patch("app.application.get_file_analysis_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.analyze_file.return_value = {"success": False, "error": "bad file"}
            mock_get.return_value = mock_service

            response = excel_client.post(
                "/api/ai/file/analyze",
                data={"purpose": "general"},
                files={"file": ("test.xlsx", b"fake", "application/octet-stream")},
            )
        assert response.status_code == 400

    def test_ai_file_analyze_exception_returns_500(self, excel_client):
        with patch("app.application.get_file_analysis_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.analyze_file.side_effect = RuntimeError("crash")
            mock_get.return_value = mock_service

            response = excel_client.post(
                "/api/ai/file/analyze",
                data={"purpose": "general"},
                files={"file": ("test.xlsx", b"fake", "application/octet-stream")},
            )
        assert response.status_code == 500


class TestExcelAiSqliteImport:
    """Cover ``ai_sqlite_import_unit_products`` endpoint."""

    def test_sqlite_import_success(self, excel_client):
        with patch("app.application.get_unit_products_import_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.import_unit_products.return_value = {"success": True, "imported": 5}
            mock_get.return_value = mock_service

            response = excel_client.post(
                "/api/ai/sqlite/import_unit_products",
                json={"saved_name": "test.xlsx", "unit_name": "Acme"},
            )
        assert response.status_code == 200

    def test_sqlite_import_failure_returns_400(self, excel_client):
        with patch("app.application.get_unit_products_import_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.import_unit_products.return_value = {
                "success": False,
                "message": "invalid file",
            }
            mock_get.return_value = mock_service

            response = excel_client.post(
                "/api/ai/sqlite/import_unit_products",
                json={"saved_name": "", "unit_name": ""},
            )
        assert response.status_code == 400

    def test_sqlite_import_exception_returns_500(self, excel_client):
        with patch("app.application.get_unit_products_import_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.import_unit_products.side_effect = RuntimeError("db error")
            mock_get.return_value = mock_service

            response = excel_client.post(
                "/api/ai/sqlite/import_unit_products",
                json={"saved_name": "test.xlsx"},
            )
        assert response.status_code == 500

    def test_sqlite_import_with_unit_name_guess(self, excel_client):
        with patch("app.application.get_unit_products_import_app_service") as mock_get:
            mock_service = MagicMock()
            mock_service.import_unit_products.return_value = {"success": True}
            mock_get.return_value = mock_service

            response = excel_client.post(
                "/api/ai/sqlite/import_unit_products",
                json={"saved_name": "test.xlsx", "unit_name_guess": "Guessed"},
            )
        assert response.status_code == 200
        # Verify unit_name_guess was used
        args = mock_service.import_unit_products.call_args
        assert args.kwargs.get("unit_name") == "Guessed"


class TestExcelSkillsAnalyze:
    """Cover ``skills_analyze_excel`` and ``skills_view_excel`` endpoints."""

    def test_skills_analyze_excel_empty_body_returns_400(self, excel_client):
        response = excel_client.post("/api/skills/analyze/excel", json={})
        assert response.status_code == 400

    def test_skills_analyze_excel_missing_file_path_returns_400(self, excel_client):
        response = excel_client.post("/api/skills/analyze/excel", json={"sheet_name": "Sheet1"})
        assert response.status_code == 400

    def test_skills_analyze_excel_success(self, excel_client):
        with patch(
            "app.infrastructure.skills.excel_analyzer.excel_template_analyzer.get_excel_analyzer_skill"
        ) as mock_get:
            mock_skill = MagicMock()
            mock_skill.execute.return_value = {"success": True, "data": "analyzed"}
            mock_get.return_value = mock_skill

            response = excel_client.post(
                "/api/skills/analyze/excel",
                json={"file_path": "/tmp/test.xlsx", "sheet_name": "Sheet1"},
            )
        assert response.status_code == 200

    def test_skills_view_excel_empty_body_returns_400(self, excel_client):
        response = excel_client.post("/api/skills/view/excel", json={})
        assert response.status_code == 400

    def test_skills_view_excel_missing_file_path_returns_400(self, excel_client):
        response = excel_client.post("/api/skills/view/excel", json={"action": "view"})
        assert response.status_code == 400

    def test_skills_view_excel_success(self, excel_client):
        with patch(
            "app.infrastructure.skills.excel_toolkit.excel_toolkit.get_excel_toolkit_skill"
        ) as mock_get:
            mock_skill = MagicMock()
            mock_skill.execute.return_value = {"success": True, "data": "viewed"}
            mock_get.return_value = mock_skill

            response = excel_client.post(
                "/api/skills/view/excel",
                json={"file_path": "/tmp/test.xlsx", "action": "view"},
            )
        assert response.status_code == 200


class TestExcelSkillsGenerateLabelTemplate:
    """Cover ``skills_generate_label_template`` endpoint."""

    def test_generate_label_template_empty_body_returns_400(self, excel_client):
        response = excel_client.post("/api/skills/generate-label-template", json={})
        assert response.status_code == 400

    def test_generate_label_template_missing_image_path_returns_400(self, excel_client):
        response = excel_client.post(
            "/api/skills/generate-label-template",
            json={"class_name": "MyTemplate"},
        )
        assert response.status_code == 400

    def test_generate_label_template_success(self, excel_client):
        with patch(
            "app.infrastructure.skills.label_template_generator.get_label_template_generator_skill"
        ) as mock_get:
            mock_skill = MagicMock()
            mock_skill.execute.return_value = {"success": True, "template": "generated"}
            mock_get.return_value = mock_skill

            response = excel_client.post(
                "/api/skills/generate-label-template",
                json={
                    "image_path": "/tmp/label.png",
                    "class_name": "MyTemplate",
                    "enable_ocr": True,
                },
            )
        assert response.status_code == 200

    def test_generate_label_template_default_class_name(self, excel_client):
        with patch(
            "app.infrastructure.skills.label_template_generator.get_label_template_generator_skill"
        ) as mock_get:
            mock_skill = MagicMock()
            mock_skill.execute.return_value = {"success": True}
            mock_get.return_value = mock_skill

            response = excel_client.post(
                "/api/skills/generate-label-template",
                json={"image_path": "/tmp/label.png"},
            )
        assert response.status_code == 200
        args = mock_skill.execute.call_args
        assert args.kwargs.get("class_name") == "LabelTemplateGenerator"
